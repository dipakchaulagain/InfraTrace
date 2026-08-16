"""
hosts.py — Host/hypervisor node endpoints.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import HostCurrent, VmCurrent
from app.models.metadata import User

router = APIRouter(prefix="/hosts", tags=["hosts"])


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
        "items": [
            {
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
            for h in hosts
        ],
    }
