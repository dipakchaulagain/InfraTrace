"""Add ON DELETE behavior to every FK referencing users.id, so a user
account can actually be deleted without a FK violation.

Live "current state" references (ownership, session, in-progress reset code)
are set to CASCADE/SET NULL so deleting the account can't leave a dangling
pointer to a row that no longer exists. Historical/audit references
(who changed a field, who resolved a dead-letter record, who performed a
logged action) are set to SET NULL — the row and its data survive, only the
FK to the now-gone account is cleared. AccessLog.user_email is a denormalized
snapshot taken at write time, so nulling AccessLog.actor_id does not lose
"who did this" for historical entries.

Application code (admin.py's delete_user) still explicitly clears
vm_metadata.owner_user_id and writes a VmMetadataAudit row per affected VM
*before* the user row is deleted, so that ownership change is itself
audited — SET NULL here is only a defense-in-depth safety net for any
future deletion path that doesn't go through that endpoint.

Revision ID: 008
Revises: 007
Create Date: 2026-07-31
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

# (constraint_name, table, column, ondelete)
_FKS = [
    ("vm_metadata_owner_user_id_fkey", "vm_metadata", "owner_user_id", "SET NULL"),
    ("vm_metadata_secondary_owner_id_fkey", "vm_metadata", "secondary_owner_id", "SET NULL"),
    ("vm_metadata_updated_by_fkey", "vm_metadata", "updated_by", "SET NULL"),
    ("vm_metadata_audit_changed_by_fkey", "vm_metadata_audit", "changed_by", "SET NULL"),
    ("access_logs_actor_id_fkey", "access_logs", "actor_id", "SET NULL"),
    ("dead_letter_records_resolved_by_fkey", "dead_letter_records", "resolved_by", "SET NULL"),
    ("password_reset_codes_created_by_fkey", "password_reset_codes", "created_by", "SET NULL"),
    ("password_reset_codes_user_id_fkey", "password_reset_codes", "user_id", "CASCADE"),
    ("user_sessions_user_id_fkey", "user_sessions", "user_id", "CASCADE"),
]


def upgrade() -> None:
    for name, table, column, ondelete in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, "users", [column], ["id"], ondelete=ondelete)


def downgrade() -> None:
    for name, table, column, _ in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, "users", [column], ["id"])
