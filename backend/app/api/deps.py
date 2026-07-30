"""
deps.py — FastAPI dependency injection: DB session, current user, session
validation, and role enforcement.
"""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.audit import log_event
from app.config import settings
from app.database import get_db
from app.models.metadata import User, UserSession

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def get_client_ip(request: Request) -> str:
    """The app sits behind the frontend's Nginx container — prefer the
    forwarded header, fall back to the direct peer address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _session_idle_timeout_minutes(db: Session) -> int:
    from app.models.inventory import AppSetting
    row = db.get(AppSetting, "auth.session_idle_timeout_minutes")
    if row and row.value:
        try:
            return int(row.value)
        except ValueError:
            pass
    return settings.SESSION_IDLE_TIMEOUT_MINUTES


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        session_id: str = payload.get("sid")
        if username is None or session_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = db.query(User).filter(User.username == username, User.active.is_(True)).first()
    if user is None:
        raise credentials_exc

    user_session = db.get(UserSession, session_id)
    now = datetime.now(timezone.utc)
    if user_session is None or user_session.user_id != user.id or user_session.revoked_at is not None:
        raise credentials_exc

    idle_minutes = _session_idle_timeout_minutes(db)
    idle_seconds = (now - user_session.last_activity_at).total_seconds()
    if idle_seconds > idle_minutes * 60:
        log_event(
            db, actor=user, action="session_timeout", result="failure",
            entity_type="session", entity_id=user_session.id,
            ip_address=get_client_ip(request), session_id=user_session.id,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired due to inactivity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_session.last_activity_at = now
    db.commit()

    request.state.session_id = user_session.id
    request.state.client_ip = get_client_ip(request)
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Same as get_current_user, but blocks access until a pending forced
    password reset is completed. auth.py's /me, /change-password, and
    /logout intentionally use get_current_user directly so a user stuck in
    forced-reset can still reach them."""
    if current_user.must_reset_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PASSWORD_RESET_REQUIRED", "message": "Password reset required before continuing"},
        )
    return current_user


def require_role(*roles: str):
    """Returns a FastAPI dependency that enforces one of the given roles."""
    def _dep(
        request: Request,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in roles:
            log_event(
                db, actor=current_user, action="permission_denied", result="failure",
                entity_type="route", details={"path": request.url.path, "required_roles": list(roles)},
                ip_address=get_client_ip(request), session_id=getattr(request.state, "session_id", None),
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not authorized for this action",
            )
        return current_user
    return _dep
