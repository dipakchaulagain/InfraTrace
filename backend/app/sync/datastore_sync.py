"""
datastore_sync.py — Shared helper to upsert DatastoreCurrent rows.

Called by both platform adapters after fetching their datastore/storage
container data. Keeps the diff/load for datastores in one place, consistent
with network_sync.py's precedent (one shared module, not duplicated per
platform).
"""
from datetime import datetime, timezone

import structlog

log = structlog.get_logger()


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

        if existing:
            existing.name = ds.get("name", existing.name)
            existing.capacity_gb = ds.get("capacity_gb")
            existing.used_gb = ds.get("used_gb")
            existing.free_gb = ds.get("free_gb")
            existing.type = ds.get("type")
            existing.connectivity_type = ds.get("connectivity_type") or "UNKNOWN"
            existing.is_shared = bool(ds.get("is_shared", False))
            existing.last_synced_at = now
        else:
            db_session.add(DatastoreCurrent(
                source_system_id=source_system_id,
                source_id=source_id,
                name=ds.get("name", ""),
                capacity_gb=ds.get("capacity_gb"),
                used_gb=ds.get("used_gb"),
                free_gb=ds.get("free_gb"),
                type=ds.get("type"),
                connectivity_type=ds.get("connectivity_type") or "UNKNOWN",
                is_shared=bool(ds.get("is_shared", False)),
                last_synced_at=now,
            ))
            db_session.flush()   # so a later duplicate source_id in this same call finds it via the query above, not autoflush (SessionLocal has autoflush=False)

    if seen_source_ids:
        db_session.query(DatastoreCurrent).filter(
            DatastoreCurrent.source_system_id == source_system_id,
            DatastoreCurrent.source_id.notin_(seen_source_ids),
        ).delete(synchronize_session=False)

    db_session.flush()
    log.info("datastores_upserted", source_system_id=source_system_id, count=len(seen_source_ids))
    return len(seen_source_ids)
