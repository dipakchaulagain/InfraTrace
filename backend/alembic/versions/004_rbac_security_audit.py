"""RBAC roles, management_ip, password reset, sessions, richer audit log

Revision ID: 004
Revises: 003
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # management_ip on vm_metadata — validated, known-good IPv4 (Layer B)
    op.add_column(
        "vm_metadata",
        sa.Column("management_ip", sa.String(45), nullable=True),
    )

    # must_reset_password on users — forces a password change at next login
    op.add_column(
        "users",
        sa.Column("must_reset_password", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Role rename: editor -> global_editor, normal -> user (viewer unchanged)
    op.execute("UPDATE users SET role = 'global_editor' WHERE role = 'editor'")
    op.execute("UPDATE users SET role = 'user' WHERE role = 'normal'")

    # password_reset_codes — admin-generated one-time codes (hashed at rest)
    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_reset_codes_user_id", "password_reset_codes", ["user_id"])

    # user_sessions — server-side session tracking so JWTs can be revoked
    # (logout, idle timeout) instead of only relying on natural token expiry.
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    # Richer access_logs — enough to serve as the single audit-log table
    op.add_column("access_logs", sa.Column("user_email", sa.String(255), nullable=True))
    op.add_column("access_logs", sa.Column("entity_id", sa.String(36), nullable=True))
    op.add_column("access_logs", sa.Column("ip_address", sa.String(64), nullable=True))
    op.add_column("access_logs", sa.Column("session_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("access_logs", "session_id")
    op.drop_column("access_logs", "ip_address")
    op.drop_column("access_logs", "entity_id")
    op.drop_column("access_logs", "user_email")

    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_password_reset_codes_user_id", table_name="password_reset_codes")
    op.drop_table("password_reset_codes")

    op.execute("UPDATE users SET role = 'editor' WHERE role = 'global_editor'")
    op.execute("UPDATE users SET role = 'normal' WHERE role = 'user'")

    op.drop_column("users", "must_reset_password")
    op.drop_column("vm_metadata", "management_ip")
