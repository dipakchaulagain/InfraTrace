"""Drop password_reset_codes — the out-of-band code reset flow is replaced by
a standard forced-reset flow: an admin sets `users.must_reset_password`
(already existed since migration 004), and the user's next login redirects
them to the reset-required page where they confirm their current password
and set a new one. No separate one-time code is generated or stored anymore.

Revision ID: 010
Revises: 009
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_password_reset_codes_user_id", table_name="password_reset_codes")
    op.drop_table("password_reset_codes")


def downgrade() -> None:
    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_reset_codes_user_id", "password_reset_codes", ["user_id"])
