"""Initial schema — Layer A (inventory) + Layer B (metadata)

Revision ID: 001
Revises:
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Layer A — synced facts
    # -------------------------------------------------------------------------
    op.create_table(
        "source_systems",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "clusters_current",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_system_id", sa.String(36), sa.ForeignKey("source_systems.id"), nullable=False),
        sa.Column("source_id", sa.String(255)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_system_id", "name", name="uq_cluster_source_name"),
    )

    op.create_table(
        "departments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
    )

    op.create_table(
        "environments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "hosts_current",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters_current.id"), nullable=True),
        sa.Column("source_system_id", sa.String(36), sa.ForeignKey("source_systems.id"), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hypervisor_type", sa.String(60)),
        sa.Column("hypervisor_version", sa.String(255)),
        sa.Column("connection_state", sa.String(60)),
        sa.Column("in_maintenance_mode", sa.Boolean()),
        sa.Column("num_cpu_sockets", sa.Integer()),
        sa.Column("num_cpu_cores", sa.Integer()),
        sa.Column("num_cpu_threads", sa.Integer()),
        sa.Column("cpu_capacity_ghz", sa.Float()),
        sa.Column("memory_capacity_gb", sa.Float()),
        sa.Column("cpu_usage_mhz", sa.Integer()),
        sa.Column("memory_usage_mb", sa.Integer()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_system_id", "source_id", name="uq_host_source"),
    )

    op.create_table(
        "networks_current",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_system_id", sa.String(36), sa.ForeignKey("source_systems.id"), nullable=False),
        sa.Column("source_id", sa.String(255)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("vlan_id", sa.String(60)),
        sa.Column("vswitch_or_dvs_name", sa.String(255)),
        sa.Column("subnet_cidr", sa.String(60)),
        sa.Column("default_gateway", sa.String(60)),
        sa.Column("dhcp_enabled", sa.Boolean()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_system_id", sa.String(36), sa.ForeignKey("source_systems.id"), nullable=True),
        sa.Column("source_platform", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_dead_lettered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_report", postgresql.JSONB()),
        sa.Column("error_message", sa.Text()),
    )

    op.create_table(
        "vms_current",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("source_platform", sa.String(20), nullable=False),
        sa.Column("source_system_id", sa.String(36), sa.ForeignKey("source_systems.id"), nullable=False),
        sa.Column("host_id", sa.String(36), sa.ForeignKey("hosts_current.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("power_state", sa.String(20), nullable=False),
        sa.Column("os_type", sa.String(255)),
        sa.Column("vcpu", sa.Integer()),
        sa.Column("memory_mb", sa.Integer()),
        sa.Column("disk_gb", sa.Float()),
        sa.Column("primary_ip", sa.String(60)),
        sa.Column("nics", postgresql.JSONB()),
        sa.Column("disks", postgresql.JSONB()),
        sa.Column("tools_status", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("is_decommissioned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("decommissioned_at", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_run_id", sa.String(36), sa.ForeignKey("sync_runs.id"), nullable=True),
        sa.UniqueConstraint("source_platform", "source_id", name="uq_vm_platform_source"),
    )

    op.create_table(
        "vm_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vm_id", sa.String(36), sa.ForeignKey("vms_current.id"), nullable=False),
        sa.Column("sync_run_id", sa.String(36), sa.ForeignKey("sync_runs.id"), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "dead_letter_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sync_run_id", sa.String(36), sa.ForeignKey("sync_runs.id"), nullable=False),
        sa.Column("source_platform", sa.String(20), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # -------------------------------------------------------------------------
    # Layer B — managed metadata
    # -------------------------------------------------------------------------
    op.create_table(
        "vm_metadata",
        sa.Column("vm_id", sa.String(36), sa.ForeignKey("vms_current.id"), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("environment_id", sa.String(36), sa.ForeignKey("environments.id"), nullable=True),
        sa.Column("notes", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("category", sa.String(80)),
        sa.UniqueConstraint("name", "category", name="uq_tag_name_category"),
    )

    op.create_table(
        "taggings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("tag_id", sa.String(36), sa.ForeignKey("tags.id"), nullable=False),
        sa.UniqueConstraint("entity_type", "entity_id", "tag_id", name="uq_tagging"),
    )

    op.create_table(
        "vm_metadata_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vm_id", sa.String(36), sa.ForeignKey("vms_current.id"), nullable=False),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("old_value", sa.String(500)),
        sa.Column("new_value", sa.String(500)),
        sa.Column("changed_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "access_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="human"),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(60)),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("details", postgresql.JSONB()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Performance indexes (per §8 Non-Functional Requirements)
    op.create_index("ix_vms_platform_source", "vms_current", ["source_platform", "source_id"])
    op.create_index("ix_vms_power_state", "vms_current", ["power_state"])
    op.create_index("ix_vms_decommissioned", "vms_current", ["is_decommissioned"])
    op.create_index("ix_vms_host_id", "vms_current", ["host_id"])
    op.create_index("ix_vm_history_vm_id", "vm_history", ["vm_id"])
    op.create_index("ix_sync_runs_started", "sync_runs", ["started_at"])
    op.create_index("ix_vm_metadata_department", "vm_metadata", ["department_id"])
    op.create_index("ix_vm_metadata_environment", "vm_metadata", ["environment_id"])


def downgrade() -> None:
    op.drop_table("access_logs")
    op.drop_table("vm_metadata_audit")
    op.drop_table("taggings")
    op.drop_table("tags")
    op.drop_table("vm_metadata")
    op.drop_table("dead_letter_records")
    op.drop_table("vm_history")
    op.drop_table("vms_current")
    op.drop_table("sync_runs")
    op.drop_table("networks_current")
    op.drop_table("hosts_current")
    op.drop_table("users")
    op.drop_table("environments")
    op.drop_table("departments")
    op.drop_table("clusters_current")
    op.drop_table("source_systems")
