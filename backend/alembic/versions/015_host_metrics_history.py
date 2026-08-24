"""Add host_metrics_history and host_metrics_history_rollup — the same
two-tier design as datastore_metrics_history/_rollup (see migrations 013,
014), applied to host CPU/memory usage: raw full-resolution samples for
the last hour, hourly min/max/avg rollup buckets beyond that, pruned at
sync.host_metrics_retention_days (Settings -> Sync Engine, default 90).

Revision ID: 015
Revises: 014
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "host_metrics_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("host_id", sa.String(36), sa.ForeignKey("hosts_current.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_usage_mhz", sa.Integer, nullable=True),
        sa.Column("cpu_capacity_ghz", sa.Float, nullable=True),
        sa.Column("memory_usage_mb", sa.Integer, nullable=True),
        sa.Column("memory_capacity_gb", sa.Float, nullable=True),
    )
    op.create_index(
        "ix_host_metrics_history_host_captured",
        "host_metrics_history", ["host_id", "captured_at"],
    )

    op.create_table(
        "host_metrics_history_rollup",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("host_id", sa.String(36), sa.ForeignKey("hosts_current.id"), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_usage_mhz_avg", sa.Float, nullable=True),
        sa.Column("cpu_usage_mhz_min", sa.Float, nullable=True),
        sa.Column("cpu_usage_mhz_max", sa.Float, nullable=True),
        sa.Column("cpu_capacity_ghz_avg", sa.Float, nullable=True),
        sa.Column("memory_usage_mb_avg", sa.Float, nullable=True),
        sa.Column("memory_usage_mb_min", sa.Float, nullable=True),
        sa.Column("memory_usage_mb_max", sa.Float, nullable=True),
        sa.Column("memory_capacity_gb_avg", sa.Float, nullable=True),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("host_id", "bucket_start", name="uq_host_metrics_rollup_bucket"),
    )
    op.create_index(
        "ix_host_metrics_rollup_host_bucket",
        "host_metrics_history_rollup", ["host_id", "bucket_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_host_metrics_rollup_host_bucket", table_name="host_metrics_history_rollup")
    op.drop_table("host_metrics_history_rollup")
    op.drop_index("ix_host_metrics_history_host_captured", table_name="host_metrics_history")
    op.drop_table("host_metrics_history")
