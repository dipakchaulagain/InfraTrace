"""Add datastores_current — datastore inventory (Layer A) synced from vCenter
and Nutanix Prism Element, including connectivity classification
(connectivity_type: ISCSI/FC/LOCAL/SAS/NFS/NFS41/VSAN/VVOL/NUTANIX_CONTAINER/
UNKNOWN) and is_shared (host-local vs multi-host-accessible storage).

Revision ID: 011
Revises: 010
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datastores_current",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_system_id", sa.String(36), sa.ForeignKey("source_systems.id"), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("capacity_gb", sa.Float, nullable=True),
        sa.Column("used_gb", sa.Float, nullable=True),
        sa.Column("free_gb", sa.Float, nullable=True),
        sa.Column("type", sa.String(30), nullable=True),
        sa.Column("connectivity_type", sa.String(30), nullable=False, server_default="UNKNOWN"),
        sa.Column("is_shared", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_system_id", "source_id", name="uq_datastore_source"),
    )
    op.create_index("ix_datastores_current_source_system", "datastores_current", ["source_system_id"])


def downgrade() -> None:
    op.drop_index("ix_datastores_current_source_system", table_name="datastores_current")
    op.drop_table("datastores_current")
