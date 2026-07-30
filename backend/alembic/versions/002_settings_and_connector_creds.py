"""Add app_settings table and credential columns to source_systems

Revision ID: 002
Revises: 001
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # app_settings — key/value store for runtime-configurable settings
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
    )

    # Credential columns on source_systems
    op.add_column("source_systems", sa.Column("username", sa.String(255), nullable=True))
    op.add_column("source_systems", sa.Column("encrypted_password", sa.Text(), nullable=True))
    op.add_column("source_systems", sa.Column("port", sa.Integer(), nullable=True))
    op.add_column("source_systems", sa.Column("insecure", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_systems", "insecure")
    op.drop_column("source_systems", "port")
    op.drop_column("source_systems", "encrypted_password")
    op.drop_column("source_systems", "username")
    op.drop_table("app_settings")
