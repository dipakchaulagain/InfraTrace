"""
auth.py — Login / token / session / password endpoints.
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Suppress passlib/bcrypt version-mismatch warning on Python 3.12
import warnings
warnings.filterwarnings("ignore", ".*error reading bcrypt version.*")

from app.audit import log_event
from app.api.deps import get_client_ip, get_current_user, _session_idle_timeout_minutes
from app.config import settings
from app.database import get_db
from app.models.metadata import User, UserSession, PasswordResetCode

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


class ResetPasswordRequest(BaseModel):
    username: str
    code: str
    new_password: str


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(plain: str) -> str:
    return pwd_context.hash(plain)


def hash_reset_code(code: str) -> str:
    return pwd_context.hash(code)


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
    log_event(db, actor=current_user, action="password_change", result="success",
               ip_address=get_client_ip(request), session_id=getattr(request.state, "session_id", None))
    db.commit()
    return {"status": "ok"}


@router.post("/reset-password")
def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Self-service completion of an admin-issued one-time reset code."""
    ip = get_client_ip(request)
    user = db.query(User).filter(User.username == payload.username).first()

    generic_error = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code")

    if not user:
        log_event(db, actor=None, action="password_reset_completed", result="failure",
                   details={"username": payload.username}, ip_address=ip)
        db.commit()
        raise generic_error

    now = datetime.now(timezone.utc)
    candidates = (
        db.query(PasswordResetCode)
        .filter(PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None))
        .filter(PasswordResetCode.expires_at > now)
        .order_by(PasswordResetCode.created_at.desc())
        .all()
    )
    match = next((c for c in candidates if verify_password(payload.code, c.code_hash)), None)

    if not match:
        log_event(db, actor=user, action="password_reset_completed", result="failure", ip_address=ip)
        db.commit()
        raise generic_error

    validate_password_policy(payload.new_password)
    user.hashed_password = get_password_hash(payload.new_password)
    user.must_reset_password = False
    match.used_at = now

    # Force re-login everywhere — revoke all of this user's active sessions
    for s in db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).all():
        s.revoked_at = now

    log_event(db, actor=user, action="password_reset_completed", result="success", ip_address=ip)
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
