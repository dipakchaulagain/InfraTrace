"""
networks.py — Network/VLAN inventory endpoints.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import NetworkCurrent
from app.models.metadata import User

router = APIRouter(prefix="/networks", tags=["networks"])


def _vm_counts_by_vlan(db: Session) -> dict[str, int]:
    """VM count per VLAN, across all active VMs' NICs, in a single query.

    Unnests each VM's nics JSONB array and groups by vlan_id (compared as
    text, matching how NetworkCurrent.vlan_id is stored) — one aggregate
    query instead of one COUNT per network row, and an *exact* match instead
    of the previous substring ILIKE (which incorrectly counted VLAN 21 as a
    match for VLAN 210, 219, etc.).
    """
    rows = db.execute(text("""
        SELECT nic->>'vlan_id' AS vlan_id, COUNT(DISTINCT vm.id) AS vm_count
        FROM vms_current vm,
             LATERAL jsonb_array_elements(COALESCE(vm.nics, '[]'::jsonb)) AS nic
        WHERE vm.is_decommissioned = false
          AND nic->>'vlan_id' IS NOT NULL
        GROUP BY nic->>'vlan_id'
    """)).all()
    return {row.vlan_id: row.vm_count for row in rows}


@router.get("")
def list_networks(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
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

    vm_counts = _vm_counts_by_vlan(db)

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
                "vm_count": vm_counts.get(n.vlan_id, 0) if n.vlan_id is not None else 0,
            }
            for n in networks
        ],
    }
