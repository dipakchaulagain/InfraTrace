"""
datastore_sync.py — Shared helper to upsert DatastoreCurrent rows.

Called by both platform adapters after fetching their datastore/storage
container data. Keeps the diff/load for datastores in one place, consistent
with network_sync.py's precedent (one shared module, not duplicated per
platform). Also appends a DatastoreMetricsHistory row on every
capacity/used/free write (both here and in update_datastore_metrics) —
see _record_metrics_history — powering the trend chart on the Datastore
detail page. rollup_and_prune_datastore_metrics (called periodically by
the scheduler, not per-sync) folds anything older than 1 hour into hourly
min/max/avg buckets so that table stays small regardless of retention.
"""
from datetime import datetime, timedelta, timezone

import structlog

log = structlog.get_logger()

_RAW_RETENTION = timedelta(hours=1)


def _record_metrics_history(db_session, datastore_id: str, capacity_gb, used_gb, free_gb, when: datetime) -> None:
    """One observation row per (re)write of a datastore's capacity/used/free
    — called from both upsert_datastores (full sync) and
    update_datastore_metrics (lightweight pull), so the trend chart on the
    Datastore detail page reflects both cadences. Skipped when every value
    is None (mapping failed upstream — nothing meaningful to plot)."""
    if capacity_gb is None and used_gb is None and free_gb is None:
        return
    from app.models.inventory import DatastoreMetricsHistory
    db_session.add(DatastoreMetricsHistory(
        datastore_id=datastore_id,
        captured_at=when,
        capacity_gb=capacity_gb,
        used_gb=used_gb,
        free_gb=free_gb,
    ))


def upsert_datastores(db_session, source_system_id: str, datastores: list[dict]) -> int:
    """
    Upsert a list of datastore dicts into DatastoreCurrent, then prune any
    existing row for this source_system_id whose source_id wasn't seen in
    this call.

    Pruning matters because upstream may legitimately hand us the same
    source_id more than once in a single call (e.g. the VMware adapter can
    see one physical datastore mounted into several Datacenters — same
    source_id, several dicts here) — those collapse into one row below.
    Pruning is also what lets a source_id *scheme* change (as happened when
    the VMware adapter switched from per-Datacenter moId to a stable
    storage-URL identity) self-heal: rows keyed under the old scheme stop
    being "seen" and are cleaned up on the next successful sync, without a
    separate migration.

    Each dict should have:
        source_id (str)           — platform-native datastore/container identity
        name (str)                — display name
        capacity_gb (float|None)
        used_gb (float|None)
        free_gb (float|None)
        type (str|None)           — raw platform type (VMFS/NFS/NFS41/vsan/VVOL/NutanixContainer)
        connectivity_type (str)   — ISCSI/FC/LOCAL/SAS/NFS/NFS41/VSAN/VVOL/NUTANIX_CONTAINER/UNKNOWN
        is_shared (bool)

    Returns the count of distinct datastores upserted (post-collapse).
    """
    from app.models.inventory import DatastoreCurrent

    now = datetime.now(timezone.utc)
    seen_source_ids: set[str] = set()

    for ds in datastores:
        source_id = ds.get("source_id")
        if not source_id:
            continue
        seen_source_ids.add(source_id)

        existing = db_session.query(DatastoreCurrent).filter_by(
            source_system_id=source_system_id,
            source_id=source_id,
        ).first()

        capacity_gb, used_gb, free_gb = ds.get("capacity_gb"), ds.get("used_gb"), ds.get("free_gb")

        if existing:
            existing.name = ds.get("name", existing.name)
            existing.capacity_gb = capacity_gb
            existing.used_gb = used_gb
            existing.free_gb = free_gb
            existing.type = ds.get("type")
            existing.connectivity_type = ds.get("connectivity_type") or "UNKNOWN"
            existing.is_shared = bool(ds.get("is_shared", False))
            existing.last_synced_at = now
            _record_metrics_history(db_session, existing.id, capacity_gb, used_gb, free_gb, now)
        else:
            new_row = DatastoreCurrent(
                source_system_id=source_system_id,
                source_id=source_id,
                name=ds.get("name", ""),
                capacity_gb=capacity_gb,
                used_gb=used_gb,
                free_gb=free_gb,
                type=ds.get("type"),
                connectivity_type=ds.get("connectivity_type") or "UNKNOWN",
                is_shared=bool(ds.get("is_shared", False)),
                last_synced_at=now,
            )
            db_session.add(new_row)
            db_session.flush()   # so a later duplicate source_id in this same call finds it via the query above, not autoflush (SessionLocal has autoflush=False)
            _record_metrics_history(db_session, new_row.id, capacity_gb, used_gb, free_gb, now)

    if seen_source_ids:
        db_session.query(DatastoreCurrent).filter(
            DatastoreCurrent.source_system_id == source_system_id,
            DatastoreCurrent.source_id.notin_(seen_source_ids),
        ).delete(synchronize_session=False)

    db_session.flush()
    log.info("datastores_upserted", source_system_id=source_system_id, count=len(seen_source_ids))
    return len(seen_source_ids)


def update_datastore_metrics(db_session, source_system_id: str, records: list[dict]) -> int:
    """
    Lightweight companion to upsert_datastores for the separately-scheduled,
    more frequent datastore-metrics pull (Settings -> Sync Engine ->
    Datastore metrics interval). Updates ONLY capacity_gb/used_gb/free_gb/
    is_shared/last_synced_at on rows that already exist.

    Deliberately never creates new rows, never touches
    connectivity_type/type/name, and never prunes — discovery,
    connectivity classification (the expensive SCSI-topology walk on the
    VMware side), and decommissioning of stale rows all stay the full
    inventory sync's job (upsert_datastores above). That's what makes this
    safe to run on a much shorter interval than the full sync.

    Each dict should have: source_id, capacity_gb, used_gb, free_gb, is_shared.
    Returns the count of rows actually updated (rows not yet known from a
    prior full sync are silently skipped, not created).
    """
    from app.models.inventory import DatastoreCurrent

    now = datetime.now(timezone.utc)
    updated = 0

    for rec in records:
        source_id = rec.get("source_id")
        if not source_id:
            continue

        existing = db_session.query(DatastoreCurrent).filter_by(
            source_system_id=source_system_id,
            source_id=source_id,
        ).first()
        if not existing:
            continue

        capacity_gb, used_gb, free_gb = rec.get("capacity_gb"), rec.get("used_gb"), rec.get("free_gb")
        existing.capacity_gb = capacity_gb
        existing.used_gb = used_gb
        existing.free_gb = free_gb
        existing.is_shared = bool(rec.get("is_shared", existing.is_shared))
        existing.last_synced_at = now
        _record_metrics_history(db_session, existing.id, capacity_gb, used_gb, free_gb, now)
        updated += 1

    db_session.flush()
    log.info("datastore_metrics_updated", source_system_id=source_system_id, count=updated)
    return updated


def _merge_stat(prev_avg, prev_min, prev_max, prev_count: int, new_values: list[float]):
    """Fold new_values into an existing (avg, min, max) — used when an
    hourly bucket already has a rollup row from an earlier, partial run
    (e.g. the rollup job firing slightly more than once an hour) so late
    stragglers still count instead of being silently dropped. prev_count is
    the bucket's total sample_count so far (shared across all three metrics
    — an approximation when a metric has occasional None gaps, acceptable
    since that's the rare/edge case, not the norm)."""
    if not new_values:
        return prev_avg, prev_min, prev_max
    total_prior = (prev_avg or 0) * prev_count
    avg = (total_prior + sum(new_values)) / (prev_count + len(new_values))
    mn = min(new_values) if prev_min is None else min(prev_min, min(new_values))
    mx = max(new_values) if prev_max is None else max(prev_max, max(new_values))
    return avg, mn, mx


def rollup_and_prune_datastore_metrics(db_session, retention_days: int) -> dict:
    """
    Two jobs in one pass, run periodically by the scheduler (not per-sync —
    this is independent of both the full inventory sync and the lightweight
    metrics pull):

    1. Roll up: any DatastoreMetricsHistory (raw) row older than 1 hour gets
       folded into an hourly DatastoreMetricsHistoryRollup bucket — avg/min/
       max/sample_count per datastore per hour — then deleted from the raw
       table. min/max are kept specifically so a brief spike or dip inside
       that hour is still visible on the chart once raw resolution is gone
       (a plain average would smooth it away).
    2. Prune: rollup buckets older than retention_days (Settings -> Sync
       Engine -> Datastore metrics retention, default 90) are deleted
       outright — nothing keeps them past that window.

    Bucketing and aggregation happen in Python rather than SQL (e.g.
    Postgres date_trunc) so this is portable to the SQLite session used in
    tests, and the per-run data volume is small regardless (~1 hour's worth
    of samples across all datastores at a time).
    """
    from app.models.inventory import DatastoreMetricsHistory, DatastoreMetricsHistoryRollup

    now = datetime.now(timezone.utc)
    raw_cutoff = now - _RAW_RETENTION
    retention_cutoff = now - timedelta(days=retention_days)

    raw_rows = (
        db_session.query(DatastoreMetricsHistory)
        .filter(DatastoreMetricsHistory.captured_at < raw_cutoff)
        .all()
    )

    buckets: dict[tuple[str, datetime], list] = {}
    for row in raw_rows:
        bucket_start = row.captured_at.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault((row.datastore_id, bucket_start), []).append(row)

    rolled_up_buckets = 0
    for (datastore_id, bucket_start), rows in buckets.items():
        capacity_vals = [r.capacity_gb for r in rows if r.capacity_gb is not None]
        used_vals = [r.used_gb for r in rows if r.used_gb is not None]
        free_vals = [r.free_gb for r in rows if r.free_gb is not None]

        bucket = db_session.query(DatastoreMetricsHistoryRollup).filter_by(
            datastore_id=datastore_id, bucket_start=bucket_start,
        ).first()
        if not bucket:
            bucket = DatastoreMetricsHistoryRollup(
                datastore_id=datastore_id, bucket_start=bucket_start, sample_count=0,
            )
            db_session.add(bucket)

        prev_count = bucket.sample_count
        bucket.capacity_gb_avg, bucket.capacity_gb_min, bucket.capacity_gb_max = _merge_stat(
            bucket.capacity_gb_avg, bucket.capacity_gb_min, bucket.capacity_gb_max, prev_count, capacity_vals,
        )
        bucket.used_gb_avg, bucket.used_gb_min, bucket.used_gb_max = _merge_stat(
            bucket.used_gb_avg, bucket.used_gb_min, bucket.used_gb_max, prev_count, used_vals,
        )
        bucket.free_gb_avg, bucket.free_gb_min, bucket.free_gb_max = _merge_stat(
            bucket.free_gb_avg, bucket.free_gb_min, bucket.free_gb_max, prev_count, free_vals,
        )
        bucket.sample_count = prev_count + len(rows)
        rolled_up_buckets += 1

    for row in raw_rows:
        db_session.delete(row)

    pruned = (
        db_session.query(DatastoreMetricsHistoryRollup)
        .filter(DatastoreMetricsHistoryRollup.bucket_start < retention_cutoff)
        .delete(synchronize_session=False)
    )

    db_session.flush()
    log.info(
        "datastore_metrics_rollup_complete",
        raw_rows_rolled_up=len(raw_rows), buckets_touched=rolled_up_buckets, buckets_pruned=pruned,
    )
    return {"raw_rows_rolled_up": len(raw_rows), "buckets_touched": rolled_up_buckets, "buckets_pruned": pruned}
