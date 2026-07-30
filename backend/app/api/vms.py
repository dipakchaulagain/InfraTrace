"""
vms.py — VM inventory endpoints: list, detail, metadata edit, history, decommissioned.
"""
import ipaddress
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_client_ip, get_current_active_user, require_role
from app.audit import log_event
from app.config import settings as app_settings
from app.database import get_db
from app.models.inventory import VmCurrent, VmHistory, HostCurrent, ClusterCurrent
from app.models.metadata import User, VmMetadata, VmMetadataAudit, Department, Environment

router = APIRouter(prefix="/vms", tags=["vms"])

# Roles that can only see/edit VMs they own
OWNER_SCOPED_ROLES = ("user", "viewer")

# Field-level edit permissions per role
EDITABLE_FIELDS_BY_ROLE = {
    "admin":         {"owner_user_id", "secondary_owner_id", "department_id", "environment_id", "notes", "os_detail", "management_ip"},
    "global_editor": {"owner_user_id", "secondary_owner_id", "department_id", "environment_id", "notes", "os_detail", "management_ip"},
    "user":          {"owner_user_id", "secondary_owner_id", "department_id", "environment_id", "notes"},
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VmMetadataUpdate(BaseModel):
    owner_user_id: Optional[str] = None
    secondary_owner_id: Optional[str] = None
    department_id: Optional[str] = None
    environment_id: Optional[str] = None
    os_detail: Optional[str] = None
    management_ip: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("owner_user_id", "secondary_owner_id", "department_id", "environment_id", mode="before")
    @classmethod
    def blank_fk_to_none(cls, v: Optional[str]) -> Optional[str]:
        # An untouched "— unassigned —" select round-trips as "" (its form state
        # is never funneled through the onChange `|| null` coercion unless the
        # user actively picks something). "" is not a valid FK value and would
        # otherwise crash the update with a ForeignKeyViolation — treat it as
        # "not set" instead. (os_detail/notes are free text — "" there is a
        # legitimate value, e.g. clearing the field, so they're left alone.)
        return None if v == "" else v

    @field_validator("management_ip")
    @classmethod
    def validate_ipv4(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        try:
            ipaddress.IPv4Address(v)
        except ValueError:
            raise ValueError("management_ip must be a valid IPv4 address")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _owner_scope(q, current_user: User):
    """Restrict a VmCurrent query to VMs owned by current_user, for roles
    that may only see VMs they own. Uses a correlated EXISTS (.has(...))
    rather than a JOIN so it composes safely with other filters that also
    join VmMetadata (department_id, environment_id, unassigned_only)."""
    if current_user.role in OWNER_SCOPED_ROLES:
        q = q.filter(VmCurrent.metadata_.has(VmMetadata.owner_user_id == current_user.id))
    return q


def _management_ip_status(vm: VmCurrent, management_ip: Optional[str]) -> Optional[str]:
    if not management_ip:
        return None
    platform_ips: set[str] = set()
    if vm.primary_ip:
        platform_ips.add(vm.primary_ip)
    for nic in (vm.nics or []):
        for entry in (nic.get("ip_addresses") or []):
            ip = entry.get("ip")
            if not ip or not entry.get("valid"):
                continue
            try:
                if isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address):
                    platform_ips.add(ip)
            except ValueError:
                continue
    if not platform_ips:
        return "no_platform_ip"
    return "match" if management_ip in platform_ips else "mismatch"


def _vm_to_dict(vm: VmCurrent) -> dict:
    meta = vm.metadata_
    host = vm.host
    management_ip = meta.management_ip if meta else None
    return {
        "id": vm.id,
        "source_id": vm.source_id,
        "source_platform": vm.source_platform,
        "name": vm.name,
        "power_state": vm.power_state,
        "os_type": vm.os_type,
        "vcpu": vm.vcpu,
        "memory_mb": vm.memory_mb,
        "disk_gb": vm.disk_gb,
        "primary_ip": vm.primary_ip,
        "nics": vm.nics or [],
        "disks": vm.disks or [],
        "tools_status": vm.tools_status,
        "is_decommissioned": vm.is_decommissioned,
        "decommissioned_at": vm.decommissioned_at.isoformat() if vm.decommissioned_at else None,
        "last_synced_at": vm.last_synced_at.isoformat() if vm.last_synced_at else None,
        "cluster": host.cluster.name if host and host.cluster else None,
        "host_node": host.name if host else None,
        # Layer B
        "owner_user_id": meta.owner_user_id if meta else None,
        "owner_username": meta.owner.username if (meta and meta.owner) else None,
        "secondary_owner_id": meta.secondary_owner_id if meta else None,
        "secondary_owner_username": meta.secondary_owner.username if (meta and meta.secondary_owner) else None,
        "department_id": meta.department_id if meta else None,
        "department_name": meta.department.name if (meta and meta.department) else None,
        "environment_id": meta.environment_id if meta else None,
        "environment_name": meta.environment.name if (meta and meta.environment) else None,
        "os_detail": meta.os_detail if meta else None,
        "management_ip": management_ip,
        "management_ip_status": _management_ip_status(vm, management_ip),
        "notes": meta.notes if meta else None,
    }


def _require_vm_visible(db: Session, vm_id: str, current_user: User) -> VmCurrent:
    q = db.query(VmCurrent).options(
        joinedload(VmCurrent.host).joinedload(HostCurrent.cluster),
        joinedload(VmCurrent.metadata_).joinedload(VmMetadata.owner),
        joinedload(VmCurrent.metadata_).joinedload(VmMetadata.secondary_owner),
        joinedload(VmCurrent.metadata_).joinedload(VmMetadata.department),
        joinedload(VmCurrent.metadata_).joinedload(VmMetadata.environment),
    ).filter(VmCurrent.id == vm_id)
    q = _owner_scope(q, current_user)
    vm = q.first()
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    return vm


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# Direct-column sorts — no extra join needed
SORTABLE_COLUMNS = {
    "name": VmCurrent.name,
    "platform": VmCurrent.source_platform,
    "power_state": VmCurrent.power_state,
    "os_type": VmCurrent.os_type,
    "vcpu": VmCurrent.vcpu,
    "memory_mb": VmCurrent.memory_mb,
    "disk_gb": VmCurrent.disk_gb,
    "primary_ip": VmCurrent.primary_ip,
    "last_synced_at": VmCurrent.last_synced_at,
}
# Sorts that need a join onto a related table
JOINED_SORT_FIELDS = {"cluster", "owner", "department", "environment"}


@router.get("")
def list_vms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    platform: Optional[str] = Query(None),
    power_state: Optional[str] = Query(None),
    os_type: Optional[str] = Query(None),
    os_detail: Optional[str] = Query(None),
    tools_status: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    environment_id: Optional[str] = Query(None),
    owner_user_id: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    unassigned_only: bool = Query(False),
    sort_by: str = Query("name"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Filterable/sortable VM list — the main inventory grid. Always excludes
    decommissioned VMs (see /vms/decommissioned) and, for owner-scoped roles,
    excludes any VM the caller doesn't own."""
    q = (
        db.query(VmCurrent)
        .options(
            joinedload(VmCurrent.host).joinedload(HostCurrent.cluster),
            joinedload(VmCurrent.metadata_).joinedload(VmMetadata.owner),
            joinedload(VmCurrent.metadata_).joinedload(VmMetadata.secondary_owner),
            joinedload(VmCurrent.metadata_).joinedload(VmMetadata.department),
            joinedload(VmCurrent.metadata_).joinedload(VmMetadata.environment),
        )
        .filter(VmCurrent.is_decommissioned.is_(False))
    )
    q = _owner_scope(q, current_user)

    metadata_joined = False   # unassigned_only and JOINED_SORT_FIELDS both need this — join at most once

    if platform:
        q = q.filter(VmCurrent.source_platform == platform)
    if power_state:
        q = q.filter(VmCurrent.power_state == power_state)
    if os_type:
        q = q.filter(VmCurrent.os_type.ilike(f"%{os_type}%"))
    if os_detail:
        q = q.filter(VmCurrent.metadata_.has(VmMetadata.os_detail.ilike(f"%{os_detail}%")))
    if tools_status:
        q = q.filter(VmCurrent.tools_status == tools_status)
    if department_id:
        q = q.filter(VmCurrent.metadata_.has(VmMetadata.department_id == department_id))
    if environment_id:
        q = q.filter(VmCurrent.metadata_.has(VmMetadata.environment_id == environment_id))
    if owner_user_id:
        q = q.filter(VmCurrent.metadata_.has(VmMetadata.owner_user_id == owner_user_id))
    if cluster:
        q = q.filter(VmCurrent.host.has(HostCurrent.cluster.has(ClusterCurrent.name.ilike(f"%{cluster}%"))))
    if search:
        q = q.filter(
            or_(
                VmCurrent.name.ilike(f"%{search}%"),
                VmCurrent.primary_ip.ilike(f"%{search}%"),
                VmCurrent.os_type.ilike(f"%{search}%"),
            )
        )
    if unassigned_only:
        q = q.outerjoin(VmCurrent.metadata_).filter(
            or_(VmMetadata.vm_id.is_(None), VmMetadata.department_id.is_(None))
        )
        metadata_joined = True

    # -- Sorting --
    if sort_by in JOINED_SORT_FIELDS:
        if sort_by == "cluster":
            q = q.outerjoin(VmCurrent.host).outerjoin(HostCurrent.cluster)
            sort_col = ClusterCurrent.name
        else:
            if not metadata_joined:
                q = q.outerjoin(VmCurrent.metadata_)
                metadata_joined = True
            if sort_by == "owner":
                q = q.outerjoin(User, VmMetadata.owner_user_id == User.id)
                sort_col = User.username
            elif sort_by == "department":
                q = q.outerjoin(Department, VmMetadata.department_id == Department.id)
                sort_col = Department.name
            else:  # environment
                q = q.outerjoin(Environment, VmMetadata.environment_id == Environment.id)
                sort_col = Environment.name
    else:
        sort_col = SORTABLE_COLUMNS.get(sort_by, VmCurrent.name)

    order_fn = sort_col.desc() if sort_order == "desc" else sort_col.asc()
    q = q.order_by(order_fn.nullslast(), VmCurrent.name.asc())

    total = q.count()
    vms = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_vm_to_dict(vm) for vm in vms],
    }


@router.get("/decommissioned")
def list_decommissioned_vms(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor")),
    decommissioned_from: Optional[datetime] = Query(None),
    decommissioned_to: Optional[datetime] = Query(None),
    owner_user_id: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None),
    environment_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Historical-reference list of decommissioned VMs. Admin / Global Editor only."""
    q = (
        db.query(VmCurrent)
        .options(
            joinedload(VmCurrent.host).joinedload(HostCurrent.cluster),
            joinedload(VmCurrent.metadata_).joinedload(VmMetadata.owner),
            joinedload(VmCurrent.metadata_).joinedload(VmMetadata.department),
            joinedload(VmCurrent.metadata_).joinedload(VmMetadata.environment),
        )
        .filter(VmCurrent.is_decommissioned.is_(True))
    )

    if decommissioned_from:
        q = q.filter(VmCurrent.decommissioned_at >= decommissioned_from)
    if decommissioned_to:
        q = q.filter(VmCurrent.decommissioned_at <= decommissioned_to)
    if owner_user_id or department_id or environment_id:
        q = q.join(VmCurrent.metadata_)
        if owner_user_id:
            q = q.filter(VmMetadata.owner_user_id == owner_user_id)
        if department_id:
            q = q.filter(VmMetadata.department_id == department_id)
        if environment_id:
            q = q.filter(VmMetadata.environment_id == environment_id)

    total = q.count()
    vms = q.order_by(VmCurrent.decommissioned_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_vm_to_dict(vm) for vm in vms],
    }


@router.get("/summary")
def get_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    """Dashboard summary counts."""
    total = db.query(func.count(VmCurrent.id)).filter(VmCurrent.is_decommissioned.is_(False)).scalar()
    on = db.query(func.count(VmCurrent.id)).filter(
        VmCurrent.is_decommissioned.is_(False), VmCurrent.power_state == "on"
    ).scalar()
    off = db.query(func.count(VmCurrent.id)).filter(
        VmCurrent.is_decommissioned.is_(False), VmCurrent.power_state == "off"
    ).scalar()
    decommissioned = db.query(func.count(VmCurrent.id)).filter(
        VmCurrent.is_decommissioned.is_(True)
    ).scalar()
    unassigned = (
        db.query(func.count(VmCurrent.id))
        .outerjoin(VmCurrent.metadata_)
        .filter(
            VmCurrent.is_decommissioned.is_(False),
            or_(VmMetadata.vm_id.is_(None), VmMetadata.department_id.is_(None)),
        )
        .scalar()
    )

    # OS distribution
    os_counts = (
        db.query(VmCurrent.os_type, func.count(VmCurrent.id))
        .filter(VmCurrent.is_decommissioned.is_(False), VmCurrent.os_type.isnot(None))
        .group_by(VmCurrent.os_type)
        .order_by(func.count(VmCurrent.id).desc())
        .limit(10)
        .all()
    )

    # Platform split
    platform_counts = (
        db.query(VmCurrent.source_platform, func.count(VmCurrent.id))
        .filter(VmCurrent.is_decommissioned.is_(False))
        .group_by(VmCurrent.source_platform)
        .all()
    )

    # Department split
    dept_counts = (
        db.query(Department.name, func.count(VmCurrent.id))
        .join(VmMetadata, VmMetadata.department_id == Department.id)
        .join(VmCurrent, VmCurrent.id == VmMetadata.vm_id)
        .filter(VmCurrent.is_decommissioned.is_(False))
        .group_by(Department.name)
        .all()
    )

    # Environment split
    env_counts = (
        db.query(Environment.name, func.count(VmCurrent.id))
        .join(VmMetadata, VmMetadata.environment_id == Environment.id)
        .join(VmCurrent, VmCurrent.id == VmMetadata.vm_id)
        .filter(VmCurrent.is_decommissioned.is_(False))
        .group_by(Environment.name)
        .all()
    )

    return {
        "total": total,
        "power_on": on,
        "power_off": off,
        "decommissioned": decommissioned,
        "unassigned": unassigned,
        "by_os": [{"os": r[0], "count": r[1]} for r in os_counts],
        "by_platform": [{"platform": r[0], "count": r[1]} for r in platform_counts],
        "by_department": [{"department": r[0], "count": r[1]} for r in dept_counts],
        "by_environment": [{"environment": r[0], "count": r[1]} for r in env_counts],
    }


@router.get("/{vm_id}")
def get_vm(
    vm_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    vm = _require_vm_visible(db, vm_id, current_user)
    if app_settings.AUDIT_LOG_VM_VIEWS:
        log_event(db, actor=current_user, action="vm_viewed", entity_type="vm", entity_id=vm_id)
        db.commit()
    return _vm_to_dict(vm)


@router.patch("/{vm_id}/metadata")
def update_vm_metadata(
    request: Request,
    vm_id: str,
    payload: VmMetadataUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update Layer B ownership/metadata for a VM. Writes an audit row for every changed field."""
    ip = get_client_ip(request)
    session_id = getattr(request.state, "session_id", None)

    allowed_fields = EDITABLE_FIELDS_BY_ROLE.get(current_user.role)
    if not allowed_fields:
        log_event(db, actor=current_user, action="permission_denied", result="failure",
                   entity_type="vm", entity_id=vm_id, details={"reason": "role_cannot_edit"},
                   ip_address=ip, session_id=session_id)
        db.commit()
        raise HTTPException(status_code=403, detail="Your role cannot edit VM metadata")

    changed_fields = payload.model_dump(exclude_none=True)
    disallowed = set(changed_fields) - allowed_fields
    if disallowed:
        log_event(db, actor=current_user, action="permission_denied", result="failure",
                   entity_type="vm", entity_id=vm_id, details={"reason": "field_not_allowed", "fields": list(disallowed)},
                   ip_address=ip, session_id=session_id)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Your role cannot edit: {', '.join(sorted(disallowed))}")

    vm = db.query(VmCurrent).filter(VmCurrent.id == vm_id).first()
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")

    meta = db.query(VmMetadata).filter(VmMetadata.vm_id == vm_id).first()

    if current_user.role in OWNER_SCOPED_ROLES:
        if not meta or meta.owner_user_id != current_user.id:
            log_event(db, actor=current_user, action="permission_denied", result="failure",
                       entity_type="vm", entity_id=vm_id, details={"reason": "not_owner"},
                       ip_address=ip, session_id=session_id)
            db.commit()
            raise HTTPException(status_code=403, detail="You can only edit VMs you own")

    if not meta:
        meta = VmMetadata(vm_id=vm_id)
        db.add(meta)

    for field_name, new_value in changed_fields.items():
        old_value = getattr(meta, field_name, None)
        if str(old_value) != str(new_value):
            db.add(VmMetadataAudit(
                vm_id=vm_id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value),
                changed_by=current_user.id,
            ))
            setattr(meta, field_name, new_value)

    meta.updated_at = datetime.now(timezone.utc)
    meta.updated_by = current_user.id

    log_event(db, actor=current_user, action="vm_metadata_updated", entity_type="vm", entity_id=vm_id,
               details={"changed": changed_fields}, ip_address=ip, session_id=session_id)
    db.commit()
    db.refresh(meta)
    return {"status": "ok", "vm_id": vm_id}


@router.get("/{vm_id}/history")
def get_vm_history(
    vm_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    _require_vm_visible(db, vm_id, current_user)
    history = (
        db.query(VmHistory)
        .filter(VmHistory.vm_id == vm_id)
        .order_by(VmHistory.changed_at.desc())
        .all()
    )
    return [
        {
            "id": h.id,
            "sync_run_id": h.sync_run_id,
            "changed_fields": h.changed_fields,
            "changed_at": h.changed_at.isoformat(),
        }
        for h in history
    ]


@router.get("/{vm_id}/metadata-audit")
def get_vm_metadata_audit(
    vm_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    _require_vm_visible(db, vm_id, current_user)
    audit = (
        db.query(VmMetadataAudit)
        .filter(VmMetadataAudit.vm_id == vm_id)
        .order_by(VmMetadataAudit.changed_at.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "field_name": a.field_name,
            "old_value": a.old_value,
            "new_value": a.new_value,
            "changed_by": a.changed_by,
            "changed_at": a.changed_at.isoformat(),
        }
        for a in audit
    ]
