"""Add datastore_metrics_history — one row per datastore per capacity/used/
free observation, written by both the full inventory sync and the
lightweight datastore-metrics pull (see datastore_sync.py's
_record_metrics_history). Powers the trend chart on the Datastore detail
page. No retention pruning yet (known follow-up).

Revision ID: 013
Revises: 012
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datastore_metrics_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("datastore_id", sa.String(36), sa.ForeignKey("datastores_current.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity_gb", sa.Float, nullable=True),
        sa.Column("used_gb", sa.Float, nullable=True),
        sa.Column("free_gb", sa.Float, nullable=True),
    )
    op.create_index(
        "ix_datastore_metrics_history_datastore_captured",
        "datastore_metrics_history", ["datastore_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_datastore_metrics_history_datastore_captured", table_name="datastore_metrics_history")
    op.drop_table("datastore_metrics_history")
