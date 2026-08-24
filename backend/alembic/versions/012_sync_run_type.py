"""Add sync_runs.run_type so the new lightweight datastore-metrics pull
(separate, typically much more frequent than the full VM inventory sync —
see run_*_datastore_metrics_sync) can be tracked and displayed without
flooding Sync Health / Dashboard "Recent Syncs" with entries the existing
"full" sync history views weren't designed to show. Existing rows backfill
to 'full', which is also the API's default filter, so nothing already
displaying sync_runs changes behavior.

Revision ID: 012
Revises: 011
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_runs",
        sa.Column("run_type", sa.String(30), nullable=False, server_default="full"),
    )


def downgrade() -> None:
    op.drop_column("sync_runs", "run_type")
