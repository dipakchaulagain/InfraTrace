"""Add datastore_metrics_history_rollup — hourly min/max/avg aggregates for
datastore capacity/used/free data older than 1 hour. Keeping 90 days of
raw, full-resolution samples (every ~10-15 min, across every datastore)
would grow datastore_metrics_history unbounded and make the detail-page
chart query increasingly expensive; instead only the last hour is kept at
raw resolution there, and the rollup job (datastore_sync.
rollup_and_prune_datastore_metrics) folds everything older into hourly
buckets here, storing min/max alongside avg so a brief spike or dip isn't
smoothed away once raw resolution is gone. Retention of rollup rows is
controlled by sync.datastore_metrics_retention_days (Settings -> Sync
Engine, default 90) — a plain AppSetting key, no schema change needed for
that part.

Revision ID: 014
Revises: 013
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datastore_metrics_history_rollup",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("datastore_id", sa.String(36), sa.ForeignKey("datastores_current.id"), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity_gb_avg", sa.Float, nullable=True),
        sa.Column("capacity_gb_min", sa.Float, nullable=True),
        sa.Column("capacity_gb_max", sa.Float, nullable=True),
        sa.Column("used_gb_avg", sa.Float, nullable=True),
        sa.Column("used_gb_min", sa.Float, nullable=True),
        sa.Column("used_gb_max", sa.Float, nullable=True),
        sa.Column("free_gb_avg", sa.Float, nullable=True),
        sa.Column("free_gb_min", sa.Float, nullable=True),
        sa.Column("free_gb_max", sa.Float, nullable=True),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("datastore_id", "bucket_start", name="uq_datastore_metrics_rollup_bucket"),
    )
    op.create_index(
        "ix_datastore_metrics_rollup_datastore_bucket",
        "datastore_metrics_history_rollup", ["datastore_id", "bucket_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_datastore_metrics_rollup_datastore_bucket", table_name="datastore_metrics_history_rollup")
    op.drop_table("datastore_metrics_history_rollup")
