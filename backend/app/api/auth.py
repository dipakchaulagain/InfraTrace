"""
auth.py — Login / token / session / password endpoints.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

# Suppress passlib/bcrypt version-mismatch warning on Python 3.12
import warnings
warnings.filterwarnings("ignore", ".*error reading bcrypt version.*")

from app.audit import log_event
from app.api.deps import get_client_ip, get_current_user, _session_idle_timeout_minutes
from app.config import settings
from app.database import get_db
from app.models.metadata import User, UserSession, AccessLog

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_SPECIAL_CHARS = r"""!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?"""


class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(plain: str) -> str:
    return pwd_context.hash(plain)


def validate_password_policy(password: str) -> None:
    """Minimum length + upper/lower/digit/special-char complexity.
    Enforced on account creation, self-service change, and reset."""
    problems = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"at least {settings.PASSWORD_MIN_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if not re.search(r"[0-9]", password):
        problems.append("a number")
    if not re.search(f"[{_SPECIAL_CHARS}]", password):
        problems.append("a special character")
    if problems:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must contain {', '.join(problems)}.",
        )


def create_access_token(subject: str, session_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": subject, "sid": session_id, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def _recent_failures(
    db: Session, *, action: str, window_minutes: int, user_id: Optional[str] = None, ip: Optional[str] = None,
) -> int:
    """Count failed attempts logged in access_logs within the window, keyed
    by user (when the account is known) or by IP (when it isn't — e.g. an
    unknown username, which still shouldn't be brute-forceable)."""
    window_start = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    q = db.query(func.count(AccessLog.id)).filter(
        AccessLog.action == action,
        AccessLog.result == "failure",
        AccessLog.occurred_at >= window_start,
    )
    q = q.filter(AccessLog.actor_id == user_id) if user_id else q.filter(AccessLog.ip_address == ip)
    return q.scalar() or 0


def _create_session(db: Session, user: User, request: Request) -> UserSession:
    now = datetime.now(timezone.utc)
    session = UserSession(
        user_id=user.id,
        created_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    db.flush()
    return session


@router.post("/token", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)

    # Step 1 — find user (must be active)
    user = db.query(User).filter(
        User.username == form_data.username,
        User.active.is_(True),
    ).first()

    # Step 1b — brute-force lockout, keyed by account when known, else by IP
    # (so guessing at unknown usernames is throttled too)
    failures = _recent_failures(
        db, action="login", window_minutes=settings.LOGIN_LOCKOUT_WINDOW_MINUTES,
        user_id=user.id if user else None, ip=ip,
    )
    if failures >= settings.LOGIN_LOCKOUT_THRESHOLD:
        log_event(db, actor=user, action="login", result="failure",
                   details={"reason": "rate_limited"}, ip_address=ip)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {settings.LOGIN_LOCKOUT_WINDOW_MINUTES} minutes.",
        )

    if not user or not verify_password(form_data.password, user.hashed_password):
        log_event(db, actor=user, action="login", result="failure",
                   details={"username": form_data.username}, ip_address=ip)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Step 2 — check login_allowed flag (correct password but access blocked)
    if not user.login_allowed:
        log_event(db, actor=user, action="login", result="failure",
                   details={"reason": "login_not_allowed"}, ip_address=ip)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Login access has been disabled for this account. Contact your administrator.",
        )

    # Step 3 — success: create a server-side session, mint a JWT bound to it
    user.last_login_at = datetime.now(timezone.utc)
    session = _create_session(db, user, request)
    log_event(db, actor=user, action="login", result="success",
               ip_address=ip, session_id=session.id)
    db.commit()

    token = create_access_token(user.username, session.id)
    return Token(
        access_token=token,
        token_type="bearer",
        user={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "department_id": user.department_id,
            "must_reset_password": user.must_reset_password,
            "session_idle_timeout_minutes": _session_idle_timeout_minutes(db),
        },
    )


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        session = db.get(UserSession, session_id)
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
    log_event(db, actor=current_user, action="logout", result="success",
               ip_address=get_client_ip(request), session_id=session_id)
    db.commit()
    return {"status": "ok"}


@router.post("/change-password")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        log_event(db, actor=current_user, action="password_change", result="failure",
                   ip_address=get_client_ip(request))
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    validate_password_policy(payload.new_password)
    current_user.hashed_password = get_password_hash(payload.new_password)
    current_user.must_reset_password = False

    # Revoke every other active session — if the old password was
    # compromised, this is what actually kicks an attacker out. The
    # session making this request stays alive so the user isn't logged out
    # by their own deliberate password change.
    current_session_id = getattr(request.state, "session_id", None)
    other_sessions = db.query(UserSession).filter(
        UserSession.user_id == current_user.id,
        UserSession.revoked_at.is_(None),
        UserSession.id != current_session_id,
    ).all()
    now = datetime.now(timezone.utc)
    for s in other_sessions:
        s.revoked_at = now

    log_event(db, actor=current_user, action="password_change", result="success",
               details={"other_sessions_revoked": len(other_sessions)},
               ip_address=get_client_ip(request), session_id=current_session_id)
    db.commit()
    return {"status": "ok"}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "department_id": current_user.department_id,
        "must_reset_password": current_user.must_reset_password,
        "last_login_at": current_user.last_login_at,
    }
