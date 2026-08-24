"""
datastores.py — Datastore/storage-container inventory endpoints.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import DatastoreCurrent, DatastoreMetricsHistory, DatastoreMetricsHistoryRollup
from app.models.metadata import User

router = APIRouter(prefix="/datastores", tags=["datastores"])

_RANGE_TO_TIMEDELTA = {
    "1h": timedelta(hours=1),
    "3h": timedelta(hours=3),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _datastore_to_dict(d: DatastoreCurrent) -> dict:
    return {
        "id": d.id,
        "source_id": d.source_id,
        "name": d.name,
        "capacity_gb": d.capacity_gb,
        "used_gb": d.used_gb,
        "free_gb": d.free_gb,
        "type": d.type,
        "connectivity_type": d.connectivity_type,
        "is_shared": d.is_shared,
        "last_synced_at": d.last_synced_at.isoformat() if d.last_synced_at else None,
    }


@router.get("")
def list_datastores(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
    connectivity_type: Optional[str] = Query(None),
    is_shared: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List all known datastores/storage containers."""
    q = db.query(DatastoreCurrent)

    if connectivity_type:
        q = q.filter(DatastoreCurrent.connectivity_type == connectivity_type)
    if is_shared is not None:
        q = q.filter(DatastoreCurrent.is_shared.is_(is_shared))
    if search:
        q = q.filter(DatastoreCurrent.name.ilike(f"%{search}%"))

    total = q.count()
    datastores = (
        q.order_by(DatastoreCurrent.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_datastore_to_dict(d) for d in datastores],
    }


@router.get("/summary")
def get_datastore_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
):
    """Dashboard summary — count of host-local (non-shared) datastores."""
    local_count = db.query(DatastoreCurrent).filter(DatastoreCurrent.is_shared.is_(False)).count()
    return {"local_count": local_count}


@router.get("/{datastore_id}")
def get_datastore(
    datastore_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
):
    d = db.query(DatastoreCurrent).filter(DatastoreCurrent.id == datastore_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Datastore not found")
    return _datastore_to_dict(d)


@router.get("/{datastore_id}/history")
def get_datastore_history(
    datastore_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
    range: str = Query("7d", pattern="^(1h|3h|6h|12h|1d|7d|30d)$"),
):
    """
    Capacity/used/free trend for the Datastore detail page's chart.

    Combines two tiers so the chart stays cheap regardless of window: raw,
    full-resolution DatastoreMetricsHistory for the last hour, and hourly
    min/max/avg DatastoreMetricsHistoryRollup buckets for anything older
    (see datastore_sync.rollup_and_prune_datastore_metrics). Every point in
    the response uses the same {avg, min, max} shape per metric — for raw
    points min == avg == max, since there's only one observation — so the
    frontend doesn't need to branch on which tier a point came from.
    """
    if not db.query(DatastoreCurrent).filter(DatastoreCurrent.id == datastore_id).first():
        raise HTTPException(status_code=404, detail="Datastore not found")

    now = datetime.now(timezone.utc)
    since = now - _RANGE_TO_TIMEDELTA[range]
    raw_boundary = now - timedelta(hours=1)

    points = []

    if since < raw_boundary:
        rollup_rows = (
            db.query(DatastoreMetricsHistoryRollup)
            .filter(
                DatastoreMetricsHistoryRollup.datastore_id == datastore_id,
                DatastoreMetricsHistoryRollup.bucket_start >= since,
                DatastoreMetricsHistoryRollup.bucket_start < raw_boundary,
            )
            .order_by(DatastoreMetricsHistoryRollup.bucket_start.asc())
            .all()
        )
        points.extend({
            "captured_at": r.bucket_start.isoformat(),
            "capacity_gb": r.capacity_gb_avg,
            "used_gb_avg": r.used_gb_avg, "used_gb_min": r.used_gb_min, "used_gb_max": r.used_gb_max,
            "free_gb_avg": r.free_gb_avg, "free_gb_min": r.free_gb_min, "free_gb_max": r.free_gb_max,
        } for r in rollup_rows)

    raw_since = max(since, raw_boundary)
    raw_rows = (
        db.query(DatastoreMetricsHistory)
        .filter(
            DatastoreMetricsHistory.datastore_id == datastore_id,
            DatastoreMetricsHistory.captured_at >= raw_since,
        )
        .order_by(DatastoreMetricsHistory.captured_at.asc())
        .all()
    )
    points.extend({
        "captured_at": r.captured_at.isoformat(),
        "capacity_gb": r.capacity_gb,
        "used_gb_avg": r.used_gb, "used_gb_min": r.used_gb, "used_gb_max": r.used_gb,
        "free_gb_avg": r.free_gb, "free_gb_min": r.free_gb, "free_gb_max": r.free_gb,
    } for r in raw_rows)

    return points
