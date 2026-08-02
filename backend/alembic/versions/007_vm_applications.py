"""Add applications (multi-value) to vm_metadata

Revision ID: 007
Revises: 006
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vm_metadata", sa.Column("applications", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("vm_metadata", "applications")
