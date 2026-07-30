"""
audit.py — single write path into the application audit log (AccessLog).
Used for every significant, state-changing or security-relevant event:
logins/logouts, session timeouts, password changes/resets, user admin
actions, VM metadata edits, decommissioning, and permission denials.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.metadata import AccessLog, User


def log_event(
    db: Session,
    *,
    actor: Optional[User],
    action: str,
    result: str = "success",
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    session_id: Optional[str] = None,
    actor_type: str = "human",
) -> None:
    """Insert one audit-log row. Does not commit — caller controls the transaction."""
    db.add(AccessLog(
        actor_id=actor.id if actor else None,
        actor_type=actor_type,
        user_email=actor.email if actor else None,
        action=action,
        resource_type=entity_type,
        entity_id=entity_id,
        result=result,
        details=details,
        ip_address=ip_address,
        session_id=session_id,
    ))
