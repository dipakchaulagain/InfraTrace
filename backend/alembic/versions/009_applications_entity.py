"""Normalize Applications into a managed lookup entity, like Department/Environment.

Adds `applications` (id, name) and a `vm_applications` join table, then
backfills existing free-text values from vm_metadata.applications (a JSONB
array added in a prior migration) into normalized Application rows + links,
before dropping the now-superseded JSONB column. Matching-by-name is
case-insensitive so "Payroll" and "payroll" collapse into one entity.

Revision ID: 009
Revises: 008
Create Date: 2026-07-31
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
    )
    op.create_table(
        "vm_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vm_id", sa.String(36), sa.ForeignKey("vms_current.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.UniqueConstraint("vm_id", "application_id", name="uq_vm_application"),
    )
    op.create_index("ix_vm_applications_vm", "vm_applications", ["vm_id"])
    op.create_index("ix_vm_applications_application", "vm_applications", ["application_id"])

    conn = op.get_bind()

    rows = conn.execute(sa.text("""
        SELECT vm_id, applications FROM vm_metadata
        WHERE applications IS NOT NULL AND jsonb_array_length(applications) > 0
    """)).fetchall()

    name_to_id: dict[str, str] = {}
    for vm_id, app_names in rows:
        for raw_name in app_names:
            name = (raw_name or "").strip()
            if not name:
                continue
            key = name.lower()
            app_id = name_to_id.get(key)
            if app_id is None:
                app_id = str(uuid.uuid4())
                conn.execute(
                    sa.text("INSERT INTO applications (id, name) VALUES (:id, :name)"),
                    {"id": app_id, "name": name},
                )
                name_to_id[key] = app_id
            conn.execute(
                sa.text("""
                    INSERT INTO vm_applications (id, vm_id, application_id)
                    VALUES (:id, :vm_id, :app_id)
                    ON CONFLICT (vm_id, application_id) DO NOTHING
                """),
                {"id": str(uuid.uuid4()), "vm_id": vm_id, "app_id": app_id},
            )

    op.drop_column("vm_metadata", "applications")


def downgrade() -> None:
    from sqlalchemy.dialects.postgresql import JSONB
    op.add_column("vm_metadata", sa.Column("applications", JSONB, nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE vm_metadata vm
        SET applications = sub.names
        FROM (
            SELECT va.vm_id, jsonb_agg(a.name) AS names
            FROM vm_applications va
            JOIN applications a ON a.id = va.application_id
            GROUP BY va.vm_id
        ) sub
        WHERE vm.vm_id = sub.vm_id
    """))

    op.drop_table("vm_applications")
    op.drop_table("applications")
