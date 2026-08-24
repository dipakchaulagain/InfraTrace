"""
host_metrics_sync.py — Shared helpers for host CPU/memory usage history.

Mirrors datastore_sync.py's design exactly, applied to hosts instead of
datastores: _record_metrics_history is called from both the full inventory
sync (in vmware_adapter.run_vmware_sync / nutanix_adapter.run_nutanix_sync,
wherever HostCurrent rows get their cpu_usage_mhz/memory_usage_mb written)
and the lightweight host-metrics pull (update_host_metrics). Only the last
hour is kept at raw resolution; rollup_and_prune_host_metrics (called
periodically by the scheduler) folds anything older into hourly min/max/avg
buckets so the table stays small regardless of retention.
"""
from datetime import datetime, timedelta, timezone

import structlog

log = structlog.get_logger()

_RAW_RETENTION = timedelta(hours=1)


def _record_metrics_history(db_session, host_id: str, cpu_usage_mhz, cpu_capacity_ghz,
                              memory_usage_mb, memory_capacity_gb, when: datetime) -> None:
    """One observation row per (re)write of a host's CPU/memory usage.
    Skipped when both usage values are None (nothing meaningful to plot)."""
    if cpu_usage_mhz is None and memory_usage_mb is None:
        return
    from app.models.inventory import HostMetricsHistory
    db_session.add(HostMetricsHistory(
        host_id=host_id,
        captured_at=when,
        cpu_usage_mhz=cpu_usage_mhz,
        cpu_capacity_ghz=cpu_capacity_ghz,
        memory_usage_mb=memory_usage_mb,
        memory_capacity_gb=memory_capacity_gb,
    ))


def update_host_metrics(db_session, source_system_id: str, records: list[dict]) -> int:
    """
    Lightweight companion to the full sync's host upsert, for the
    separately-scheduled, more frequent host-metrics pull (Settings ->
    Sync Engine -> Host metrics interval). Updates ONLY cpu_usage_mhz/
    memory_usage_mb/last_synced_at on rows that already exist.

    Deliberately never creates new rows and never touches any other host
    field (hypervisor_version, connection_state, cluster, capacity, etc.)
    — discovery and full inventory refresh stay the full sync's job. That's
    what makes this safe to run on a much shorter interval.

    Each dict should have: source_id, cpu_usage_mhz, memory_usage_mb.
    Capacity fields for the history point are read from the existing
    HostCurrent row (rarely changes, so not worth re-fetching here).
    Returns the count of rows actually updated (rows not yet known from a
    prior full sync are silently skipped, not created).
    """
    from app.models.inventory import HostCurrent

    now = datetime.now(timezone.utc)
    updated = 0

    for rec in records:
        source_id = rec.get("source_id")
        if not source_id:
            continue

        existing = db_session.query(HostCurrent).filter_by(
            source_system_id=source_system_id,
            source_id=source_id,
        ).first()
        if not existing:
            continue

        cpu_usage_mhz = rec.get("cpu_usage_mhz")
        memory_usage_mb = rec.get("memory_usage_mb")
        existing.cpu_usage_mhz = cpu_usage_mhz
        existing.memory_usage_mb = memory_usage_mb
        existing.last_synced_at = now
        _record_metrics_history(
            db_session, existing.id, cpu_usage_mhz, existing.cpu_capacity_ghz,
            memory_usage_mb, existing.memory_capacity_gb, now,
        )
        updated += 1

    db_session.flush()
    log.info("host_metrics_updated", source_system_id=source_system_id, count=updated)
    return updated


def _merge_stat(prev_avg, prev_min, prev_max, prev_count: int, new_values: list[float]):
    """Identical to datastore_sync._merge_stat — see there for the full
    rationale (folding late stragglers into an already-rolled-up bucket)."""
    if not new_values:
        return prev_avg, prev_min, prev_max
    total_prior = (prev_avg or 0) * prev_count
    avg = (total_prior + sum(new_values)) / (prev_count + len(new_values))
    mn = min(new_values) if prev_min is None else min(prev_min, min(new_values))
    mx = max(new_values) if prev_max is None else max(prev_max, max(new_values))
    return avg, mn, mx


def _merge_avg(prev_avg, prev_count: int, new_values: list[float]):
    """Weighted-average-only merge, for capacity fields where min/max isn't
    tracked (capacity essentially never changes within an hour)."""
    if not new_values:
        return prev_avg
    total_prior = (prev_avg or 0) * prev_count
    return (total_prior + sum(new_values)) / (prev_count + len(new_values))


def rollup_and_prune_host_metrics(db_session, retention_days: int) -> dict:
    """
    Same two-job pass as datastore_sync.rollup_and_prune_datastore_metrics,
    applied to HostMetricsHistory/HostMetricsHistoryRollup: fold raw rows
    older than 1 hour into hourly buckets (min/max/avg for usage, avg for
    capacity), delete the raw rows, then prune rollup buckets older than
    retention_days.
    """
    from app.models.inventory import HostMetricsHistory, HostMetricsHistoryRollup

    now = datetime.now(timezone.utc)
    raw_cutoff = now - _RAW_RETENTION
    retention_cutoff = now - timedelta(days=retention_days)

    raw_rows = (
        db_session.query(HostMetricsHistory)
        .filter(HostMetricsHistory.captured_at < raw_cutoff)
        .all()
    )

    buckets: dict[tuple[str, datetime], list] = {}
    for row in raw_rows:
        bucket_start = row.captured_at.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault((row.host_id, bucket_start), []).append(row)

    rolled_up_buckets = 0
    for (host_id, bucket_start), rows in buckets.items():
        cpu_vals = [r.cpu_usage_mhz for r in rows if r.cpu_usage_mhz is not None]
        mem_vals = [r.memory_usage_mb for r in rows if r.memory_usage_mb is not None]
        cpu_cap_vals = [r.cpu_capacity_ghz for r in rows if r.cpu_capacity_ghz is not None]
        mem_cap_vals = [r.memory_capacity_gb for r in rows if r.memory_capacity_gb is not None]

        bucket = db_session.query(HostMetricsHistoryRollup).filter_by(
            host_id=host_id, bucket_start=bucket_start,
        ).first()
        if not bucket:
            bucket = HostMetricsHistoryRollup(host_id=host_id, bucket_start=bucket_start, sample_count=0)
            db_session.add(bucket)

        prev_count = bucket.sample_count
        bucket.cpu_usage_mhz_avg, bucket.cpu_usage_mhz_min, bucket.cpu_usage_mhz_max = _merge_stat(
            bucket.cpu_usage_mhz_avg, bucket.cpu_usage_mhz_min, bucket.cpu_usage_mhz_max, prev_count, cpu_vals,
        )
        bucket.memory_usage_mb_avg, bucket.memory_usage_mb_min, bucket.memory_usage_mb_max = _merge_stat(
            bucket.memory_usage_mb_avg, bucket.memory_usage_mb_min, bucket.memory_usage_mb_max, prev_count, mem_vals,
        )
        bucket.cpu_capacity_ghz_avg = _merge_avg(bucket.cpu_capacity_ghz_avg, prev_count, cpu_cap_vals)
        bucket.memory_capacity_gb_avg = _merge_avg(bucket.memory_capacity_gb_avg, prev_count, mem_cap_vals)
        bucket.sample_count = prev_count + len(rows)
        rolled_up_buckets += 1

    for row in raw_rows:
        db_session.delete(row)

    pruned = (
        db_session.query(HostMetricsHistoryRollup)
        .filter(HostMetricsHistoryRollup.bucket_start < retention_cutoff)
        .delete(synchronize_session=False)
    )

    db_session.flush()
    log.info(
        "host_metrics_rollup_complete",
        raw_rows_rolled_up=len(raw_rows), buckets_touched=rolled_up_buckets, buckets_pruned=pruned,
    )
    return {"raw_rows_rolled_up": len(raw_rows), "buckets_touched": rolled_up_buckets, "buckets_pruned": pruned}
