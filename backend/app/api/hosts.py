"""
hosts.py — Host/hypervisor node endpoints.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import HostCurrent, VmCurrent, HostMetricsHistory, HostMetricsHistoryRollup
from app.models.metadata import User

router = APIRouter(prefix="/hosts", tags=["hosts"])

_RANGE_TO_TIMEDELTA = {
    "1h": timedelta(hours=1),
    "3h": timedelta(hours=3),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _host_to_dict(h: HostCurrent, db: Session) -> dict:
    return {
        "id": h.id,
        "source_id": h.source_id,
        "name": h.name,
        "cluster": h.cluster.name if h.cluster else None,
        "hypervisor_type": h.hypervisor_type,
        "hypervisor_version": h.hypervisor_version,
        "connection_state": h.connection_state,
        "in_maintenance_mode": h.in_maintenance_mode,
        "num_cpu_sockets": h.num_cpu_sockets,
        "num_cpu_cores": h.num_cpu_cores,
        "num_cpu_threads": h.num_cpu_threads,
        "cpu_capacity_ghz": h.cpu_capacity_ghz,
        "memory_capacity_gb": h.memory_capacity_gb,
        "cpu_usage_mhz": h.cpu_usage_mhz,
        "memory_usage_mb": h.memory_usage_mb,
        "last_synced_at": h.last_synced_at.isoformat() if h.last_synced_at else None,
        "vm_count": db.query(func.count(VmCurrent.id)).filter(
            VmCurrent.host_id == h.id,
            VmCurrent.is_decommissioned.is_(False),
        ).scalar(),
    }


@router.get("")
def list_hosts(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
    platform: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q = db.query(HostCurrent).options(joinedload(HostCurrent.cluster))

    if platform:
        q = q.filter(HostCurrent.hypervisor_type == platform)

    total = q.count()
    hosts = q.order_by(HostCurrent.name).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_host_to_dict(h, db) for h in hosts],
    }


@router.get("/{host_id}")
def get_host(
    host_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
):
    h = db.query(HostCurrent).options(joinedload(HostCurrent.cluster)).filter(HostCurrent.id == host_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Host not found")
    return _host_to_dict(h, db)


@router.get("/{host_id}/history")
def get_host_history(
    host_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
    range: str = Query("7d", pattern="^(1h|3h|6h|12h|1d|7d|30d)$"),
):
    """
    CPU/memory usage trend for the Host detail page's chart. Same two-tier
    combine as the datastore history endpoint — raw for the last hour,
    hourly min/max/avg rollup buckets for anything older (see
    host_metrics_sync.rollup_and_prune_host_metrics). Every point uses the
    same {avg, min, max} shape per metric — for raw points min == avg == max.
    """
    if not db.query(HostCurrent).filter(HostCurrent.id == host_id).first():
        raise HTTPException(status_code=404, detail="Host not found")

    now = datetime.now(timezone.utc)
    since = now - _RANGE_TO_TIMEDELTA[range]
    raw_boundary = now - timedelta(hours=1)

    points = []

    if since < raw_boundary:
        rollup_rows = (
            db.query(HostMetricsHistoryRollup)
            .filter(
                HostMetricsHistoryRollup.host_id == host_id,
                HostMetricsHistoryRollup.bucket_start >= since,
                HostMetricsHistoryRollup.bucket_start < raw_boundary,
            )
            .order_by(HostMetricsHistoryRollup.bucket_start.asc())
            .all()
        )
        points.extend({
            "captured_at": r.bucket_start.isoformat(),
            "cpu_capacity_ghz": r.cpu_capacity_ghz_avg,
            "cpu_usage_mhz_avg": r.cpu_usage_mhz_avg, "cpu_usage_mhz_min": r.cpu_usage_mhz_min, "cpu_usage_mhz_max": r.cpu_usage_mhz_max,
            "memory_capacity_gb": r.memory_capacity_gb_avg,
            "memory_usage_mb_avg": r.memory_usage_mb_avg, "memory_usage_mb_min": r.memory_usage_mb_min, "memory_usage_mb_max": r.memory_usage_mb_max,
        } for r in rollup_rows)

    raw_since = max(since, raw_boundary)
    raw_rows = (
        db.query(HostMetricsHistory)
        .filter(
            HostMetricsHistory.host_id == host_id,
            HostMetricsHistory.captured_at >= raw_since,
        )
        .order_by(HostMetricsHistory.captured_at.asc())
        .all()
    )
    points.extend({
        "captured_at": r.captured_at.isoformat(),
        "cpu_capacity_ghz": r.cpu_capacity_ghz,
        "cpu_usage_mhz_avg": r.cpu_usage_mhz, "cpu_usage_mhz_min": r.cpu_usage_mhz, "cpu_usage_mhz_max": r.cpu_usage_mhz,
        "memory_capacity_gb": r.memory_capacity_gb,
        "memory_usage_mb_avg": r.memory_usage_mb, "memory_usage_mb_min": r.memory_usage_mb, "memory_usage_mb_max": r.memory_usage_mb,
    } for r in raw_rows)

    return points
