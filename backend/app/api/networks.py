"""
networks.py — Network/VLAN inventory endpoints.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import NetworkCurrent, VmCurrent
from app.models.metadata import User

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("")
def list_networks(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor")),
    platform: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List all known networks/VLANs with VM count per network."""
    q = db.query(NetworkCurrent)

    if search:
        q = q.filter(
            NetworkCurrent.name.ilike(f"%{search}%") |
            NetworkCurrent.vlan_id.ilike(f"%{search}%")
        )

    total = q.count()
    networks = (
        q.order_by(NetworkCurrent.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    def vm_count_for_vlan(vlan_id: Optional[str]) -> int:
        """Count active VMs whose nics JSONB array contains this vlan_id.
        Uses PostgreSQL JSONB containment — fast with a GIN index."""
        if vlan_id is None:
            return 0
        try:
            # Try as integer first (most common case)
            vid: object = int(vlan_id)
        except (ValueError, TypeError):
            vid = vlan_id

        try:
            result = db.execute(
                db.query(func.count(VmCurrent.id))
                .filter(
                    VmCurrent.is_decommissioned.is_(False),
                    VmCurrent.nics.cast('text').ilike(f'%"vlan_id": {vid}%')
                )
                .statement
            ).scalar()
            return result or 0
        except Exception:
            return 0

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": n.id,
                "source_id": n.source_id,
                "name": n.name,
                "vlan_id": n.vlan_id,
                "vswitch_or_dvs_name": n.vswitch_or_dvs_name,
                "subnet_cidr": n.subnet_cidr,
                "default_gateway": n.default_gateway,
                "dhcp_enabled": n.dhcp_enabled,
                "last_synced_at": n.last_synced_at.isoformat() if n.last_synced_at else None,
            }
            for n in networks
        ],
    }
