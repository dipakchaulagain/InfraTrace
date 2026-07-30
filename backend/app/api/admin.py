"""
admin.py — Admin endpoints: users, departments, environments, tags, source systems.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_password_hash, hash_reset_code, validate_password_policy
from app.api.deps import get_client_ip, get_current_active_user, require_role
from app.audit import log_event
from app.config import settings
from app.database import get_db
from app.models.inventory import SourceSystem
from app.models.metadata import Department, Environment, Tag, User, PasswordResetCode, UserSession, AccessLog

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

class DepartmentCreate(BaseModel):
    name: str


@router.get("/departments")
def list_departments(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    return [{"id": d.id, "name": d.name} for d in db.query(Department).order_by(Department.name).all()]


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


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------

class EnvironmentCreate(BaseModel):
    name: str


@router.get("/environments")
def list_environments(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    return [{"id": e.id, "name": e.name} for e in db.query(Environment).order_by(Environment.name).all()]


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


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TagCreate(BaseModel):
    name: str
    category: Optional[str] = None


@router.get("/tags")
def list_tags(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    return [{"id": t.id, "name": t.name, "category": t.category} for t in db.query(Tag).order_by(Tag.name).all()]


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


def _user_out(u: User) -> dict:
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
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    users = db.query(User).order_by(User.username).all()
    return [_user_out(u) for u in users]


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
