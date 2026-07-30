"""Add full_name/phone to users, secondary_owner_id to vm_metadata

Revision ID: 005
Revises: 004
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(40), nullable=True))

    op.add_column("vm_metadata", sa.Column("secondary_owner_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "vm_metadata_secondary_owner_id_fkey",
        "vm_metadata", "users",
        ["secondary_owner_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("vm_metadata_secondary_owner_id_fkey", "vm_metadata", type_="foreignkey")
    op.drop_column("vm_metadata", "secondary_owner_id")

    op.drop_column("users", "phone")
    op.drop_column("users", "full_name")
