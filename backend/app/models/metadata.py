"""
metadata.py — Layer B (managed metadata) ORM models.
The sync engine's DB role has ZERO grants on these tables — enforced at the DB level.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# DEPARTMENTS — normalized lookup
# ---------------------------------------------------------------------------
class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="department")
    vm_metadata: Mapped[list["VmMetadata"]] = relationship(back_populates="department")


# ---------------------------------------------------------------------------
# ENVIRONMENTS — normalized lookup
# ---------------------------------------------------------------------------
class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)

    vm_metadata: Mapped[list["VmMetadata"]] = relationship(back_populates="environment")


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("departments.id"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False)
    # admin | global_editor | user | viewer
    # "user" = can view/edit only VMs they own; "viewer" = read-only, owned VMs only
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    login_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # login_allowed = False prevents login even if active=True. Defaults off —
    # an admin must deliberately grant access to a newly created account.
    must_reset_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Forces a password change at next login — set on admin-created accounts
    # and whenever an admin triggers a reset for an existing account.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    department: Mapped[Optional["Department"]] = relationship(back_populates="users")
    vm_metadata_authored: Mapped[list["VmMetadata"]] = relationship(
        back_populates="updated_by_user", foreign_keys="VmMetadata.updated_by"
    )
    access_logs: Mapped[list["AccessLog"]] = relationship(back_populates="actor")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")
    reset_codes: Mapped[list["PasswordResetCode"]] = relationship(
        back_populates="user", foreign_keys="PasswordResetCode.user_id"
    )


# ---------------------------------------------------------------------------
# VM_METADATA — the only place ownership data lives; one-to-one with VmCurrent
# ---------------------------------------------------------------------------
class VmMetadata(Base):
    __tablename__ = "vm_metadata"

    vm_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vms_current.id"), primary_key=True
    )
    owner_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    secondary_owner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    # Optional co-owner/backup contact — same edit permissions as owner_user_id
    # confer no extra privilege by itself; it's informational (who else to contact).
    department_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("departments.id"), nullable=True
    )
    environment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("environments.id"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    os_detail: Mapped[Optional[str]] = mapped_column(String(255))
    # Custom OS detail — more specific than the platform-reported os_type
    # e.g. "Ubuntu 22.04 LTS", "Windows Server 2019 Datacenter"
    management_ip: Mapped[Optional[str]] = mapped_column(String(45))
    # Known-good, validated IPv4 — supplements/corrects the platform-reported IP
    # when guest tools are absent, wrong, IPv6-only, or the VM has multiple NICs.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    vm: Mapped["VmCurrent"] = relationship(back_populates="metadata_")
    owner: Mapped[Optional["User"]] = relationship(foreign_keys=[owner_user_id])
    secondary_owner: Mapped[Optional["User"]] = relationship(foreign_keys=[secondary_owner_id])
    department: Mapped[Optional["Department"]] = relationship(back_populates="vm_metadata")
    environment: Mapped[Optional["Environment"]] = relationship(back_populates="vm_metadata")
    updated_by_user: Mapped[Optional["User"]] = relationship(
        back_populates="vm_metadata_authored", foreign_keys=[updated_by]
    )
    audit: Mapped[list["VmMetadataAudit"]] = relationship(
        back_populates="vm_meta",
        primaryjoin="VmMetadata.vm_id == foreign(VmMetadataAudit.vm_id)",
        viewonly=True,
    )
    taggings: Mapped[list["Tagging"]] = relationship(
        primaryjoin="and_(Tagging.entity_type == 'vm', foreign(Tagging.entity_id) == VmMetadata.vm_id)",
        viewonly=True,
    )


# ---------------------------------------------------------------------------
# TAGS — reusable, normalized
# ---------------------------------------------------------------------------
class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(80))

    __table_args__ = (
        UniqueConstraint("name", "category", name="uq_tag_name_category"),
    )

    taggings: Mapped[list["Tagging"]] = relationship(back_populates="tag")


# ---------------------------------------------------------------------------
# TAGGINGS — polymorphic join: entity_type in ('vm', 'host', 'network')
# ---------------------------------------------------------------------------
class Tagging(Base):
    __tablename__ = "taggings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)   # vm | host | network
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)     # not a strict FK (polymorphic)
    tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "tag_id", name="uq_tagging"),
    )

    tag: Mapped["Tag"] = relationship(back_populates="taggings")


# ---------------------------------------------------------------------------
# VM_METADATA_AUDIT — who changed ownership/environment/tags, and when
# ---------------------------------------------------------------------------
class VmMetadataAudit(Base):
    __tablename__ = "vm_metadata_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    vm_id: Mapped[str] = mapped_column(String(36), ForeignKey("vms_current.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(String(500))
    new_value: Mapped[Optional[str]] = mapped_column(String(500))
    changed_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    vm_meta: Mapped[Optional["VmMetadata"]] = relationship(
        back_populates="audit",
        primaryjoin="foreign(VmMetadataAudit.vm_id) == VmMetadata.vm_id",
        viewonly=True,
    )


# ---------------------------------------------------------------------------
# PASSWORD_RESET_CODES — admin-generated one-time codes (hashed at rest)
# ---------------------------------------------------------------------------
class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    user: Mapped["User"] = relationship(back_populates="reset_codes", foreign_keys=[user_id])


# ---------------------------------------------------------------------------
# USER_SESSIONS — server-side session tracking so a JWT can be revoked
# before its natural expiry (logout, idle timeout).
# ---------------------------------------------------------------------------
class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))

    user: Mapped["User"] = relationship(back_populates="sessions")


# ---------------------------------------------------------------------------
# ACCESS_LOGS — application-level audit log (logins, admin actions, VM
# metadata edits, permission denials, etc). Intentionally append-only.
# Routine reads (VM views) are not logged by default — see AUDIT_LOG_VM_VIEWS.
# ---------------------------------------------------------------------------
class AccessLog(Base):
    __tablename__ = "access_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="human", nullable=False)  # human | service
    user_email: Mapped[Optional[str]] = mapped_column(String(255))   # denormalized snapshot at event time
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(60))   # doubles as "entity type"
    entity_id: Mapped[Optional[str]] = mapped_column(String(36))
    result: Mapped[str] = mapped_column(String(20), nullable=False)   # success | failure
    details: Mapped[Optional[dict]] = mapped_column(JSONB)             # e.g. {"field":..., "old":..., "new":...}
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    session_id: Mapped[Optional[str]] = mapped_column(String(36))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    actor: Mapped[Optional["User"]] = relationship(back_populates="access_logs")
