"""Add vms_current.snapshots — array of {id, name, description, created_at,
size_gb} per VM, synced from vCenter (vim.vm.Snapshot tree, size computed
from layoutEx disk-chain deltas) and Nutanix (v2 /snapshots, no size field
exposed by that API — size_gb always null there). Same JSONB-array-on-
VmCurrent pattern already used for nics/disks, not a separate table, since
snapshots don't need independent history/querying.

Revision ID: 016
Revises: 015
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vms_current", sa.Column("snapshots", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("vms_current", "snapshots")
