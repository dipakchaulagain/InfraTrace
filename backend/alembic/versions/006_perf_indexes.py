"""Add indexes for frequently-filtered columns (pure performance, no schema/behavior change)

Revision ID: 006
Revises: 005
Create Date: 2026-07-30
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # vm_metadata.owner_user_id — every list_vms call for owner-scoped roles
    # (user/viewer) filters on this, plus the new Owner filter for admin/GE.
    op.create_index("ix_vm_metadata_owner", "vm_metadata", ["owner_user_id"])

    # vms_current.tools_status — new VMs-page filter.
    op.create_index("ix_vms_tools_status", "vms_current", ["tools_status"])

    # access_logs — queried on every login/reset attempt (brute-force lockout
    # lookups) and by the admin Audit Log page's filters.
    op.create_index("ix_access_logs_occurred_at", "access_logs", ["occurred_at"])
    op.create_index("ix_access_logs_actor_id", "access_logs", ["actor_id"])
    op.create_index("ix_access_logs_ip_address", "access_logs", ["ip_address"])
    op.create_index("ix_access_logs_action", "access_logs", ["action"])

    # dead_letter_records.resolved — filtered on every Sync Health page load.
    op.create_index("ix_dead_letter_resolved", "dead_letter_records", ["resolved"])


def downgrade() -> None:
    op.drop_index("ix_dead_letter_resolved", table_name="dead_letter_records")
    op.drop_index("ix_access_logs_action", table_name="access_logs")
    op.drop_index("ix_access_logs_ip_address", table_name="access_logs")
    op.drop_index("ix_access_logs_actor_id", table_name="access_logs")
    op.drop_index("ix_access_logs_occurred_at", table_name="access_logs")
    op.drop_index("ix_vms_tools_status", table_name="vms_current")
    op.drop_index("ix_vm_metadata_owner", table_name="vm_metadata")
