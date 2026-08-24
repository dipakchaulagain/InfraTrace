"""
Unit tests for host_metrics_sync.py against a real (in-memory SQLite)
session — mirrors test_datastore_sync.py's approach and coverage, applied
to host CPU/memory usage instead of datastore capacity.
"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
import pytest

from app.models.inventory import (
    SourceSystem, HostCurrent, HostMetricsHistory, HostMetricsHistoryRollup,
)
from app.sync.host_metrics_sync import (
    update_host_metrics, rollup_and_prune_host_metrics,
)


@pytest.fixture
def session():
    engine = sa.create_engine("sqlite:///:memory:")
    SourceSystem.__table__.create(engine)
    HostCurrent.__table__.create(engine)
    HostMetricsHistory.__table__.create(engine)
    HostMetricsHistoryRollup.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False)   # matches app/database.py's SessionLocal
    s = Session()
    s.add(SourceSystem(id="src-1", platform="vmware", display_name="test", base_url="https://x"))
    s.commit()
    yield s
    s.close()


def _add_host(session, source_id="host-1", cpu_capacity_ghz=20.0, memory_capacity_gb=128.0):
    h = HostCurrent(
        source_system_id="src-1", source_id=source_id, name=f"esxi-{source_id}",
        cpu_capacity_ghz=cpu_capacity_ghz, memory_capacity_gb=memory_capacity_gb,
    )
    session.add(h)
    session.commit()
    return h


def _metrics_rec(source_id, cpu_usage_mhz=5000, memory_usage_mb=40000):
    return {"source_id": source_id, "cpu_usage_mhz": cpu_usage_mhz, "memory_usage_mb": memory_usage_mb}


# ---------------------------------------------------------------------------
# update_host_metrics
# ---------------------------------------------------------------------------

def test_updates_existing_host(session):
    _add_host(session, "host-1")
    updated = update_host_metrics(session, "src-1", [_metrics_rec("host-1", cpu_usage_mhz=9999)])
    session.commit()
    assert updated == 1
    host = session.query(HostCurrent).one()
    assert host.cpu_usage_mhz == 9999


def test_never_creates_new_hosts(session):
    updated = update_host_metrics(session, "src-1", [_metrics_rec("host-never-discovered")])
    session.commit()
    assert updated == 0
    assert session.query(HostCurrent).count() == 0


def test_records_history_using_existing_capacity(session):
    _add_host(session, "host-1", cpu_capacity_ghz=32.0, memory_capacity_gb=256.0)
    update_host_metrics(session, "src-1", [_metrics_rec("host-1", cpu_usage_mhz=1000, memory_usage_mb=2000)])
    session.commit()
    point = session.query(HostMetricsHistory).one()
    assert point.cpu_usage_mhz == 1000
    assert point.memory_usage_mb == 2000
    # Capacity for the history point is read from the existing host row, not re-supplied.
    assert point.cpu_capacity_ghz == 32.0
    assert point.memory_capacity_gb == 256.0


def test_does_not_touch_other_host_fields(session):
    h = _add_host(session, "host-1")
    h.hypervisor_version = "ESXi 8.0"
    h.connection_state = "connected"
    session.commit()
    update_host_metrics(session, "src-1", [_metrics_rec("host-1")])
    session.commit()
    host = session.query(HostCurrent).one()
    assert host.hypervisor_version == "ESXi 8.0"
    assert host.connection_state == "connected"


# ---------------------------------------------------------------------------
# rollup_and_prune_host_metrics
# ---------------------------------------------------------------------------

def _seed_raw_history(session, host_id, points):
    """points: list of (captured_at, cpu_usage_mhz, cpu_capacity_ghz, memory_usage_mb, memory_capacity_gb)."""
    for captured_at, cpu_usage, cpu_cap, mem_usage, mem_cap in points:
        session.add(HostMetricsHistory(
            host_id=host_id, captured_at=captured_at,
            cpu_usage_mhz=cpu_usage, cpu_capacity_ghz=cpu_cap,
            memory_usage_mb=mem_usage, memory_capacity_gb=mem_cap,
        ))
    session.commit()


def test_rollup_leaves_last_hour_raw_untouched(session):
    h = _add_host(session, "host-1")
    update_host_metrics(session, "src-1", [_metrics_rec("host-1")])
    session.commit()
    now = datetime.now(timezone.utc)
    _seed_raw_history(session, h.id, [(now - timedelta(minutes=30), 4000, 20.0, 30000, 128.0)])

    rollup_and_prune_host_metrics(session, retention_days=90)
    session.commit()

    assert session.query(HostMetricsHistory).count() == 2
    assert session.query(HostMetricsHistoryRollup).count() == 0


def test_rollup_folds_old_rows_into_hourly_bucket_with_min_max(session):
    h = _add_host(session, "host-1")

    # A CPU spike in the middle of the hour that a plain average would hide.
    hour_start = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    _seed_raw_history(session, h.id, [
        (hour_start + timedelta(minutes=5), 2000, 20.0, 20000, 128.0),
        (hour_start + timedelta(minutes=25), 18000, 20.0, 20000, 128.0),
        (hour_start + timedelta(minutes=45), 2200, 20.0, 20000, 128.0),
    ])

    result = rollup_and_prune_host_metrics(session, retention_days=90)
    session.commit()

    assert result["buckets_touched"] == 1
    bucket = session.query(HostMetricsHistoryRollup).one()
    assert bucket.cpu_usage_mhz_min == 2000
    assert bucket.cpu_usage_mhz_max == 18000
    assert abs(bucket.cpu_usage_mhz_avg - (2000 + 18000 + 2200) / 3) < 0.01
    assert bucket.sample_count == 3
    assert session.query(HostMetricsHistory).filter(HostMetricsHistory.host_id == h.id).count() == 0


def test_rollup_merges_into_existing_bucket_on_partial_reruns(session):
    h = _add_host(session, "host-1")
    hour_start = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

    _seed_raw_history(session, h.id, [(hour_start + timedelta(minutes=5), 2000, 20.0, 20000, 128.0)])
    rollup_and_prune_host_metrics(session, retention_days=90)
    session.commit()

    _seed_raw_history(session, h.id, [(hour_start + timedelta(minutes=55), 18000, 20.0, 20000, 128.0)])
    rollup_and_prune_host_metrics(session, retention_days=90)
    session.commit()

    bucket = session.query(HostMetricsHistoryRollup).one()
    assert bucket.sample_count == 2
    assert bucket.cpu_usage_mhz_min == 2000
    assert bucket.cpu_usage_mhz_max == 18000


def test_prune_removes_rollup_buckets_past_retention(session):
    h = _add_host(session, "host-1")
    old_bucket_start = datetime.now(timezone.utc) - timedelta(days=100)
    session.add(HostMetricsHistoryRollup(
        host_id=h.id, bucket_start=old_bucket_start,
        cpu_usage_mhz_avg=4000, cpu_usage_mhz_min=4000, cpu_usage_mhz_max=4000, cpu_capacity_ghz_avg=20.0,
        memory_usage_mb_avg=30000, memory_usage_mb_min=30000, memory_usage_mb_max=30000, memory_capacity_gb_avg=128.0,
        sample_count=1,
    ))
    session.commit()

    result = rollup_and_prune_host_metrics(session, retention_days=90)
    session.commit()

    assert result["buckets_pruned"] == 1
    assert session.query(HostMetricsHistoryRollup).count() == 0
