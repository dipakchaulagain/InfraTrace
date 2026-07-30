"""Add login_allowed to users and os_detail to vm_metadata

Revision ID: 003
Revises: 002
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # login_allowed on users — default True so existing users are unaffected
    op.add_column(
        "users",
        sa.Column("login_allowed", sa.Boolean(), nullable=False, server_default="true"),
    )
    # os_detail on vm_metadata — custom OS version field (Layer B)
    op.add_column(
        "vm_metadata",
        sa.Column("os_detail", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vm_metadata", "os_detail")
    op.drop_column("users", "login_allowed")
