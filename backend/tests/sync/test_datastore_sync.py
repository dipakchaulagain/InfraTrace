"""
Unit tests for the shared upsert_datastores helper (app/sync/datastore_sync.py)
against a real (in-memory SQLite) session — this exercises the actual
query/insert/delete logic, not just the in-memory dict shape.
"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
import pytest

from app.database import Base
from app.models.inventory import (
    SourceSystem, DatastoreCurrent, DatastoreMetricsHistory, DatastoreMetricsHistoryRollup,
)
from app.sync.datastore_sync import upsert_datastores, update_datastore_metrics, rollup_and_prune_datastore_metrics


@pytest.fixture
def session():
    engine = sa.create_engine("sqlite:///:memory:")
    SourceSystem.__table__.create(engine)
    DatastoreCurrent.__table__.create(engine)
    DatastoreMetricsHistory.__table__.create(engine)
    DatastoreMetricsHistoryRollup.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False)   # matches app/database.py's SessionLocal
    s = Session()
    s.add(SourceSystem(id="src-1", platform="vmware", display_name="test", base_url="https://x"))
    s.commit()
    yield s
    s.close()


def _rec(source_id, name="ds", connectivity_type="ISCSI", is_shared=True):
    return {
        "source_id": source_id, "name": name,
        "capacity_gb": 100.0, "used_gb": 40.0, "free_gb": 60.0,
        "type": "VMFS", "connectivity_type": connectivity_type, "is_shared": is_shared,
    }


def test_creates_new_rows(session):
    upsert_datastores(session, "src-1", [_rec("url-1", name="ds1")])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1
    assert rows[0].name == "ds1"
    assert rows[0].source_id == "url-1"


def test_updates_existing_row_on_resync(session):
    upsert_datastores(session, "src-1", [_rec("url-1", connectivity_type="UNKNOWN")])
    session.commit()
    upsert_datastores(session, "src-1", [_rec("url-1", connectivity_type="ISCSI")])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1
    assert rows[0].connectivity_type == "ISCSI"


def test_duplicate_source_id_within_one_call_collapses_to_one_row(session):
    # Same physical datastore seen twice in one sync pass (e.g. mounted into
    # two Datacenters, each producing a separate vim.Datastore object with
    # its own moId but the same storage-identity source_id) — must not
    # duplicate. SessionLocal uses autoflush=False, so this only works
    # because upsert_datastores flushes after each insert.
    upsert_datastores(session, "src-1", [
        _rec("shared-url", name="DELL-EMC-R5-12.23", connectivity_type="ISCSI"),
        _rec("shared-url", name="DELL-EMC-R5-12.23", connectivity_type="UNKNOWN"),
    ])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1


def test_prunes_rows_not_seen_in_latest_run(session):
    upsert_datastores(session, "src-1", [_rec("url-old", name="gone")])
    session.commit()
    upsert_datastores(session, "src-1", [_rec("url-new", name="current")])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1
    assert rows[0].source_id == "url-new"


def test_empty_call_does_not_wipe_existing_rows(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    upsert_datastores(session, "src-1", [])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1


def test_prune_is_scoped_to_source_system(session):
    session.add(SourceSystem(id="src-2", platform="vmware", display_name="other", base_url="https://y"))
    session.commit()
    upsert_datastores(session, "src-1", [_rec("url-1")])
    upsert_datastores(session, "src-2", [_rec("url-2")])
    session.commit()
    # Re-sync src-1 without url-1 present — must not touch src-2's row.
    upsert_datastores(session, "src-1", [_rec("url-1-renamed")])
    session.commit()
    rows = {r.source_system_id: r.source_id for r in session.query(DatastoreCurrent).all()}
    assert rows == {"src-1": "url-1-renamed", "src-2": "url-2"}


# ---------------------------------------------------------------------------
# update_datastore_metrics — the lightweight, more-frequent companion pull.
# Only ever touches capacity/used/free/is_shared on rows a prior full sync
# already discovered; never creates rows, never touches
# connectivity_type/type/name.
# ---------------------------------------------------------------------------

def _metrics_rec(source_id, capacity_gb=200.0, used_gb=80.0, free_gb=120.0, is_shared=True):
    return {"source_id": source_id, "capacity_gb": capacity_gb, "used_gb": used_gb,
            "free_gb": free_gb, "is_shared": is_shared}


def test_metrics_updates_capacity_fields_on_existing_row(session):
    upsert_datastores(session, "src-1", [_rec("url-1", name="ds1", connectivity_type="ISCSI")])
    session.commit()
    updated = update_datastore_metrics(session, "src-1", [_metrics_rec("url-1", capacity_gb=999.0, used_gb=500.0, free_gb=499.0)])
    session.commit()
    assert updated == 1
    row = session.query(DatastoreCurrent).one()
    assert row.capacity_gb == 999.0
    assert row.used_gb == 500.0
    assert row.free_gb == 499.0


def test_metrics_never_creates_new_rows(session):
    updated = update_datastore_metrics(session, "src-1", [_metrics_rec("url-never-discovered")])
    session.commit()
    assert updated == 0
    assert session.query(DatastoreCurrent).count() == 0


def test_metrics_never_touches_connectivity_type_or_name(session):
    upsert_datastores(session, "src-1", [_rec("url-1", name="original-name", connectivity_type="FC")])
    session.commit()
    update_datastore_metrics(session, "src-1", [_metrics_rec("url-1")])
    session.commit()
    row = session.query(DatastoreCurrent).one()
    assert row.connectivity_type == "FC"
    assert row.name == "original-name"
    assert row.type == "VMFS"


def test_metrics_updates_is_shared(session):
    upsert_datastores(session, "src-1", [_rec("url-1", is_shared=False)])
    session.commit()
    update_datastore_metrics(session, "src-1", [_metrics_rec("url-1", is_shared=True)])
    session.commit()
    assert session.query(DatastoreCurrent).one().is_shared is True


# ---------------------------------------------------------------------------
# History recording — both upsert_datastores (full sync) and
# update_datastore_metrics (lightweight pull) write a DatastoreMetricsHistory
# row on every capacity/used/free write, powering the detail-page trend chart.
# ---------------------------------------------------------------------------

def test_upsert_records_history_on_new_datastore(session):
    upsert_datastores(session, "src-1", [_rec("url-1", name="ds1")])
    session.commit()
    ds = session.query(DatastoreCurrent).one()
    history = session.query(DatastoreMetricsHistory).all()
    assert len(history) == 1
    assert history[0].datastore_id == ds.id
    assert history[0].capacity_gb == 100.0
    assert history[0].used_gb == 40.0
    assert history[0].free_gb == 60.0


def test_upsert_records_history_on_resync(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    assert session.query(DatastoreMetricsHistory).count() == 2


def test_metrics_pull_records_history(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    update_datastore_metrics(session, "src-1", [_metrics_rec("url-1", capacity_gb=500.0, used_gb=200.0, free_gb=300.0)])
    session.commit()
    history = session.query(DatastoreMetricsHistory).order_by(DatastoreMetricsHistory.captured_at).all()
    assert len(history) == 2   # one from the initial upsert, one from the metrics pull
    assert history[-1].capacity_gb == 500.0
    assert history[-1].used_gb == 200.0
    assert history[-1].free_gb == 300.0


def test_no_history_row_when_all_metrics_none(session):
    rec = {"source_id": "url-1", "name": "ds-no-metrics", "capacity_gb": None,
           "used_gb": None, "free_gb": None, "type": "VMFS",
           "connectivity_type": "UNKNOWN", "is_shared": False}
    upsert_datastores(session, "src-1", [rec])
    session.commit()
    assert session.query(DatastoreCurrent).count() == 1
    assert session.query(DatastoreMetricsHistory).count() == 0


# ---------------------------------------------------------------------------
# rollup_and_prune_datastore_metrics — folds raw rows older than 1 hour into
# hourly min/max/avg buckets, preserving spikes a plain average would
# smooth away, and prunes rollup buckets past the retention window.
# ---------------------------------------------------------------------------

def _seed_raw_history(session, datastore_id, points):
    """points: list of (captured_at, capacity_gb, used_gb, free_gb)."""
    for captured_at, capacity_gb, used_gb, free_gb in points:
        session.add(DatastoreMetricsHistory(
            datastore_id=datastore_id, captured_at=captured_at,
            capacity_gb=capacity_gb, used_gb=used_gb, free_gb=free_gb,
        ))
    session.commit()


def test_rollup_leaves_last_hour_raw_untouched(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    ds = session.query(DatastoreCurrent).one()
    now = datetime.now(timezone.utc)
    _seed_raw_history(session, ds.id, [(now - timedelta(minutes=30), 100.0, 40.0, 60.0)])

    rollup_and_prune_datastore_metrics(session, retention_days=90)
    session.commit()

    # 2 raw rows total: the one from upsert (just now) + the seeded 30-min-old one.
    assert session.query(DatastoreMetricsHistory).count() == 2
    assert session.query(DatastoreMetricsHistoryRollup).count() == 0


def test_rollup_folds_old_rows_into_hourly_bucket_with_min_max(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    ds = session.query(DatastoreCurrent).one()

    # All within the same hour, 2 hours ago — a spike (50) in the middle
    # that a plain average would hide.
    hour_start = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    _seed_raw_history(session, ds.id, [
        (hour_start + timedelta(minutes=5), 100.0, 10.0, 90.0),
        (hour_start + timedelta(minutes=25), 100.0, 50.0, 50.0),
        (hour_start + timedelta(minutes=45), 100.0, 12.0, 88.0),
    ])

    result = rollup_and_prune_datastore_metrics(session, retention_days=90)
    session.commit()

    assert result["buckets_touched"] == 1
    bucket = session.query(DatastoreMetricsHistoryRollup).one()
    assert bucket.used_gb_min == 10.0
    assert bucket.used_gb_max == 50.0
    assert abs(bucket.used_gb_avg - 24.0) < 0.01
    assert bucket.sample_count == 3

    # The 3 seeded rows are gone; only the fresh one from upsert (just now) remains raw.
    assert session.query(DatastoreMetricsHistory).count() == 1


def test_rollup_merges_into_existing_bucket_on_partial_reruns(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    ds = session.query(DatastoreCurrent).one()

    hour_start = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

    _seed_raw_history(session, ds.id, [(hour_start + timedelta(minutes=5), 100.0, 10.0, 90.0)])
    rollup_and_prune_datastore_metrics(session, retention_days=90)
    session.commit()

    _seed_raw_history(session, ds.id, [(hour_start + timedelta(minutes=55), 100.0, 50.0, 50.0)])
    rollup_and_prune_datastore_metrics(session, retention_days=90)
    session.commit()

    bucket = session.query(DatastoreMetricsHistoryRollup).one()
    assert bucket.sample_count == 2
    assert bucket.used_gb_min == 10.0
    assert bucket.used_gb_max == 50.0
    assert abs(bucket.used_gb_avg - 30.0) < 0.01


def test_prune_removes_rollup_buckets_past_retention(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    ds = session.query(DatastoreCurrent).one()

    old_bucket_start = datetime.now(timezone.utc) - timedelta(days=100)
    session.add(DatastoreMetricsHistoryRollup(
        datastore_id=ds.id, bucket_start=old_bucket_start,
        capacity_gb_avg=100.0, capacity_gb_min=100.0, capacity_gb_max=100.0,
        used_gb_avg=40.0, used_gb_min=40.0, used_gb_max=40.0,
        free_gb_avg=60.0, free_gb_min=60.0, free_gb_max=60.0, sample_count=1,
    ))
    session.commit()

    result = rollup_and_prune_datastore_metrics(session, retention_days=90)
    session.commit()

    assert result["buckets_pruned"] == 1
    assert session.query(DatastoreMetricsHistoryRollup).count() == 0
