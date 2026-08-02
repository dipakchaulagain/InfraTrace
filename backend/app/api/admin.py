"""
admin.py — Admin endpoints: users, departments, environments, tags, source systems.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.auth import get_password_hash, hash_reset_code, validate_password_policy
from app.api.deps import get_client_ip, get_current_active_user, require_role
from app.audit import log_event
from app.config import settings
from app.database import get_db
from app.models.inventory import SourceSystem, VmCurrent
from app.models.metadata import (
    Department, Environment, Application, VmApplication, Tag, Tagging,
    User, PasswordResetCode, UserSession, AccessLog,
    VmMetadata, VmMetadataAudit,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# VM-count helpers — one aggregate query per lookup type, active VMs only
# (matches the rest of the app's convention of excluding decommissioned VMs
# from "current" counts, e.g. get_summary/_vm_counts_by_vlan).
# ---------------------------------------------------------------------------

def _department_vm_counts(db: Session) -> dict[str, int]:
    rows = db.execute(text("""
        SELECT vm_metadata.department_id, COUNT(*) AS vm_count
        FROM vm_metadata JOIN vms_current ON vms_current.id = vm_metadata.vm_id
        WHERE vm_metadata.department_id IS NOT NULL AND vms_current.is_decommissioned = false
        GROUP BY vm_metadata.department_id
    """)).all()
    return {row.department_id: row.vm_count for row in rows}


def _environment_vm_counts(db: Session) -> dict[str, int]:
    rows = db.execute(text("""
        SELECT vm_metadata.environment_id, COUNT(*) AS vm_count
        FROM vm_metadata JOIN vms_current ON vms_current.id = vm_metadata.vm_id
        WHERE vm_metadata.environment_id IS NOT NULL AND vms_current.is_decommissioned = false
        GROUP BY vm_metadata.environment_id
    """)).all()
    return {row.environment_id: row.vm_count for row in rows}


def _application_vm_counts(db: Session) -> dict[str, int]:
    rows = db.execute(text("""
        SELECT va.application_id, COUNT(DISTINCT va.vm_id) AS vm_count
        FROM vm_applications va JOIN vms_current ON vms_current.id = va.vm_id
        WHERE vms_current.is_decommissioned = false
        GROUP BY va.application_id
    """)).all()
    return {row.application_id: row.vm_count for row in rows}


def _tag_vm_counts(db: Session) -> dict[str, int]:
    rows = db.execute(text("""
        SELECT t.tag_id, COUNT(DISTINCT t.entity_id) AS vm_count
        FROM taggings t JOIN vms_current ON vms_current.id = t.entity_id
        WHERE t.entity_type = 'vm' AND vms_current.is_decommissioned = false
        GROUP BY t.tag_id
    """)).all()
    return {row.tag_id: row.vm_count for row in rows}


def _user_vm_counts(db: Session) -> dict[str, int]:
    rows = db.execute(text("""
        SELECT vm_metadata.owner_user_id, COUNT(*) AS vm_count
        FROM vm_metadata JOIN vms_current ON vms_current.id = vm_metadata.vm_id
        WHERE vm_metadata.owner_user_id IS NOT NULL AND vms_current.is_decommissioned = false
        GROUP BY vm_metadata.owner_user_id
    """)).all()
    return {row.owner_user_id: row.vm_count for row in rows}


def _vms_using(db: Session, *, join_model, join_condition, extra_filter=None, limit: int = 50) -> list[dict]:
    """Active VMs currently referencing a lookup entity — used both to block
    a delete-while-in-use and to show the admin exactly which VMs to reassign."""
    q = db.query(VmCurrent.id, VmCurrent.name).join(join_model, join_condition).filter(
        VmCurrent.is_decommissioned.is_(False)
    )
    if extra_filter is not None:
        q = q.filter(extra_filter)
    rows = q.order_by(VmCurrent.name).limit(limit).all()
    return [{"id": r.id, "name": r.name} for r in rows]


def _blocked_delete(kind: str, affected: list[dict]) -> HTTPException:
    return HTTPException(status_code=400, detail={
        "message": f"{len(affected)} VM{'s' if len(affected) != 1 else ''} still "
                   f"{'use' if len(affected) != 1 else 'uses'} this {kind}. "
                   f"Reassign {'them' if len(affected) != 1 else 'it'} before deleting.",
        "affected_vms": affected,
    })


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

class DepartmentCreate(BaseModel):
    name: str


@router.get("/departments")
def list_departments(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    counts = _department_vm_counts(db)
    return [
        {"id": d.id, "name": d.name, "vm_count": counts.get(d.id, 0)}
        for d in db.query(Department).order_by(Department.name).all()
    ]


@router.post("/departments")
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    dept = Department(name=payload.name)
    db.add(dept)
    db.commit()
    return {"id": dept.id, "name": dept.name}


@router.delete("/departments/{department_id}")
def delete_department(
    department_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    affected = _vms_using(
        db, join_model=VmMetadata, join_condition=VmMetadata.vm_id == VmCurrent.id,
        extra_filter=VmMetadata.department_id == department_id,
    )
    if affected:
        raise _blocked_delete("department", affected)
    db.delete(dept)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------

class EnvironmentCreate(BaseModel):
    name: str


@router.get("/environments")
def list_environments(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    counts = _environment_vm_counts(db)
    return [
        {"id": e.id, "name": e.name, "vm_count": counts.get(e.id, 0)}
        for e in db.query(Environment).order_by(Environment.name).all()
    ]


@router.post("/environments")
def create_environment(
    payload: EnvironmentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    env = Environment(name=payload.name)
    db.add(env)
    db.commit()
    return {"id": env.id, "name": env.name}


@router.delete("/environments/{environment_id}")
def delete_environment(
    environment_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    env = db.query(Environment).filter(Environment.id == environment_id).first()
    if not env:
        raise HTTPException(status_code=404, detail="Environment not found")
    affected = _vms_using(
        db, join_model=VmMetadata, join_condition=VmMetadata.vm_id == VmCurrent.id,
        extra_filter=VmMetadata.environment_id == environment_id,
    )
    if affected:
        raise _blocked_delete("environment", affected)
    db.delete(env)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Applications — normalized lookup; a VM can link to several (vm_applications)
# ---------------------------------------------------------------------------

class ApplicationCreate(BaseModel):
    name: str


@router.get("/applications")
def list_applications(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    counts = _application_vm_counts(db)
    return [
        {"id": a.id, "name": a.name, "vm_count": counts.get(a.id, 0)}
        for a in db.query(Application).order_by(Application.name).all()
    ]


@router.post("/applications")
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Application name is required")
    if db.query(Application).filter(func.lower(Application.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail="An application with this name already exists")
    app_ = Application(name=name)
    db.add(app_)
    db.commit()
    return {"id": app_.id, "name": app_.name}


@router.delete("/applications/{application_id}")
def delete_application(
    application_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    app_ = db.query(Application).filter(Application.id == application_id).first()
    if not app_:
        raise HTTPException(status_code=404, detail="Application not found")
    affected = _vms_using(
        db, join_model=VmApplication, join_condition=VmApplication.vm_id == VmCurrent.id,
        extra_filter=VmApplication.application_id == application_id,
    )
    if affected:
        raise _blocked_delete("application", affected)
    db.delete(app_)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TagCreate(BaseModel):
    name: str
    category: Optional[str] = None


@router.get("/tags")
def list_tags(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    counts = _tag_vm_counts(db)
    return [
        {"id": t.id, "name": t.name, "category": t.category, "vm_count": counts.get(t.id, 0)}
        for t in db.query(Tag).order_by(Tag.name).all()
    ]


@router.post("/tags")
def create_tag(
    payload: TagCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    tag = Tag(name=payload.name, category=payload.category)
    db.add(tag)
    db.commit()
    return {"id": tag.id, "name": tag.name, "category": tag.category}


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    affected = _vms_using(
        db, join_model=Tagging, join_condition=Tagging.entity_id == VmCurrent.id,
        extra_filter=(Tagging.tag_id == tag_id) & (Tagging.entity_type == "vm"),
    )
    if affected:
        raise _blocked_delete("tag", affected)
    db.delete(tag)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

VALID_ROLES = ("admin", "global_editor", "user", "viewer")


class UserCreate(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    password: str
    role: str = "viewer"   # admin | global_editor | user | viewer
    department_id: Optional[str] = None
    login_allowed: bool = False   # defaults off — admin must deliberately grant access


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[str] = None
    active: Optional[bool] = None
    login_allowed: Optional[bool] = None
    must_reset_password: Optional[bool] = None


def _user_out(u: User, vm_count: int = 0) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "phone": u.phone,
        "role": u.role,
        "active": u.active,
        "login_allowed": u.login_allowed,
        "must_reset_password": u.must_reset_password,
        "department_id": u.department_id,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "owned_vm_count": vm_count,
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    counts = _user_vm_counts(db)
    users = db.query(User).order_by(User.username).all()
    return [_user_out(u, counts.get(u.id, 0)) for u in users]


@router.get("/users/lookup")
def list_users_lookup(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor")),
):
    """Minimal id+username list for populating the VM-owner dropdown,
    without exposing full user records to Global Editors."""
    users = db.query(User).filter(User.active.is_(True)).order_by(User.username).all()
    return [{"id": u.id, "username": u.username, "full_name": u.full_name} for u in users]


@router.post("/users")
def create_user(
    request: Request,
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    validate_password_policy(payload.password)

    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        phone=payload.phone,
        hashed_password=get_password_hash(payload.password),
        role=payload.role,
        department_id=payload.department_id,
        login_allowed=payload.login_allowed,
        must_reset_password=True,   # admin-created accounts require a first-login reset
    )
    db.add(user)
    db.flush()
    log_event(db, actor=current_user, action="user_created", entity_type="user", entity_id=user.id,
               details={"username": user.username, "role": user.role}, ip_address=get_client_ip(request))
    db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}


@router.patch("/users/{user_id}")
def update_user(
    request: Request,
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changes = payload.model_dump(exclude_none=True)
    if "role" in changes and changes["role"] not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")

    before = {k: getattr(user, k) for k in changes}
    for k, v in changes.items():
        setattr(user, k, v)

    # Revoking access should take effect immediately, not just at next idle timeout
    if changes.get("active") is False or changes.get("login_allowed") is False:
        now = datetime.now(timezone.utc)
        for s in db.query(UserSession).filter(
            UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
        ).all():
            s.revoked_at = now

    log_event(db, actor=current_user, action="user_updated", entity_type="user", entity_id=user.id,
               details={"before": before, "after": changes}, ip_address=get_client_ip(request))
    db.commit()
    return {"status": "ok", "user_id": user_id}


@router.post("/users/{user_id}/trigger-reset")
def trigger_password_reset(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Generate a one-time reset code (no email service configured — the
    admin relays this code to the user out-of-band). Returned in plaintext
    exactly once; only its hash is stored."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(timezone.utc)
    # Invalidate any prior unused codes for this user
    for c in db.query(PasswordResetCode).filter(
        PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None)
    ).all():
        c.used_at = now

    code = secrets.token_hex(4).upper()   # 8 hex chars, e.g. "A1B2C3D4"
    db.add(PasswordResetCode(
        user_id=user.id,
        code_hash=hash_reset_code(code),
        expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_CODE_TTL_MINUTES),
        created_by=current_user.id,
        created_at=now,
    ))
    user.must_reset_password = True

    log_event(db, actor=current_user, action="password_reset_requested", entity_type="user", entity_id=user.id,
               ip_address=get_client_ip(request))
    db.commit()
    return {
        "code": code,
        "expires_at": (now + timedelta(minutes=settings.PASSWORD_RESET_CODE_TTL_MINUTES)).isoformat(),
        "message": "Relay this code to the user out-of-band. It will not be shown again.",
    }


@router.get("/users/{user_id}/owned-vms")
def get_user_owned_vms(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """VMs currently owned by this user — lets the Admin UI preview the impact
    of deleting the account before the admin confirms."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = (
        db.query(VmCurrent.id, VmCurrent.name)
        .join(VmMetadata, VmMetadata.vm_id == VmCurrent.id)
        .filter(VmMetadata.owner_user_id == user_id)
        .order_by(VmCurrent.name)
        .all()
    )
    return {"count": len(rows), "vms": [{"id": r.id, "name": r.name} for r in rows]}


@router.delete("/users/{user_id}")
def delete_user(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Permanently delete a user account. Any VM they owned has its owner
    cleared (with a per-VM audit entry) in the same transaction, so the app
    never ends up with a deleted user still referenced as an owner."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role == "admin":
        other_admins = db.query(func.count(User.id)).filter(
            User.role == "admin", User.id != user_id
        ).scalar()
        if not other_admins:
            raise HTTPException(status_code=400, detail="Cannot delete the last remaining Admin account")

    ip = get_client_ip(request)
    session_id = getattr(request.state, "session_id", None)

    # Captured before the delete: once `user` is gone, a raw user_id in the
    # audit trail is meaningless to a human reading it later — record the
    # display name instead.
    owner_display_name = user.full_name or user.username

    owned = db.query(VmMetadata).filter(VmMetadata.owner_user_id == user_id).all()
    for meta in owned:
        db.add(VmMetadataAudit(
            vm_id=meta.vm_id,
            field_name="owner_user_id",
            old_value=owner_display_name,
            new_value=None,
            changed_by=current_user.id,
        ))
        meta.owner_user_id = None
        meta.updated_at = datetime.now(timezone.utc)
        meta.updated_by = current_user.id

    affected_vm_ids = [meta.vm_id for meta in owned]

    log_event(db, actor=current_user, action="user_deleted", result="success",
               entity_type="user", entity_id=user_id,
               details={"username": user.username, "email": user.email, "role": user.role,
                        "vms_ownership_cleared": affected_vm_ids},
               ip_address=ip, session_id=session_id)

    # Every other FK to this user (sessions, reset codes, secondary-owner slot,
    # who-last-touched-this-row bookkeeping, historical audit attribution) is
    # resolved by ON DELETE SET NULL/CASCADE at the DB level — see migration 008.
    db.delete(user)
    db.commit()
    return {"status": "ok", "deleted_user_id": user_id, "vms_updated": len(affected_vm_ids)}


# ---------------------------------------------------------------------------
# Audit log — admin-only view over AccessLog
# ---------------------------------------------------------------------------

@router.get("/audit-logs")
def list_audit_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    q = db.query(AccessLog)
    if date_from:
        q = q.filter(AccessLog.occurred_at >= date_from)
    if date_to:
        q = q.filter(AccessLog.occurred_at <= date_to)
    if user_id:
        q = q.filter(AccessLog.actor_id == user_id)
    if action:
        q = q.filter(AccessLog.action == action)
    if entity_type:
        q = q.filter(AccessLog.resource_type == entity_type)

    total = q.count()
    rows = q.order_by(AccessLog.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "actor_id": r.actor_id,
                "user_email": r.user_email,
                "action": r.action,
                "entity_type": r.resource_type,
                "entity_id": r.entity_id,
                "result": r.result,
                "ip_address": r.ip_address,
                "session_id": r.session_id,
                "details": r.details,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Source systems (connectors)
# Connectors in Admin are read-only views + active/inactive toggle.
# Credentials are managed exclusively via the Settings page.
# ---------------------------------------------------------------------------

@router.get("/sources")
def list_source_systems(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    sources = db.query(SourceSystem).order_by(SourceSystem.platform, SourceSystem.created_at).all()
    return [
        {
            "id": s.id,
            "platform": s.platform,
            "display_name": s.display_name,
            "base_url": s.base_url,
            "is_active": s.is_active,
            # Show whether credentials are stored (never expose them)
            "has_credentials": bool(s.username and s.encrypted_password),
        }
        for s in sources
    ]


@router.patch("/sources/{source_id}/toggle")
def toggle_source(
    source_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    source = db.query(SourceSystem).filter(SourceSystem.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source system not found")
    source.is_active = not source.is_active
    db.commit()
    return {"id": source.id, "is_active": source.is_active}
