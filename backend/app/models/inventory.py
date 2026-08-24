"""
inventory.py — Layer A (synced facts) ORM models.
The sync engine's DB role has INSERT/UPDATE only on these tables.
No ownership or metadata columns live here — those belong in metadata.py (Layer B).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# APP_SETTINGS — key/value store for runtime-configurable settings.
# Credentials are stored encrypted (see connector_settings.py).
# Admin-writable from the UI; read by the sync engine at runtime.
# ---------------------------------------------------------------------------
class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)   # user id


# ---------------------------------------------------------------------------
# SOURCE_SYSTEMS — one row per connected vCenter / Prism instance
# Credentials stored here (encrypted) take precedence over .env values.
# ---------------------------------------------------------------------------
class SourceSystem(Base):
    __tablename__ = "source_systems"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)          # "vmware" | "nutanix"
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    # Credentials — stored encrypted via connector_settings.py
    # These override the corresponding .env / Settings values at runtime.
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    encrypted_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    insecure: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    clusters: Mapped[list["ClusterCurrent"]] = relationship(back_populates="source_system")
    networks: Mapped[list["NetworkCurrent"]] = relationship(back_populates="source_system")
    datastores: Mapped[list["DatastoreCurrent"]] = relationship(back_populates="source_system")
    sync_runs: Mapped[list["SyncRun"]] = relationship(back_populates="source_system")


# ---------------------------------------------------------------------------
# CLUSTERS_CURRENT
# ---------------------------------------------------------------------------
class ClusterCurrent(Base):
    __tablename__ = "clusters_current"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_system_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_systems.id"), nullable=False
    )
    source_id: Mapped[Optional[str]] = mapped_column(String(255))   # platform-native cluster ID
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_system_id", "name", name="uq_cluster_source_name"),
    )

    source_system: Mapped["SourceSystem"] = relationship(back_populates="clusters")
    hosts: Mapped[list["HostCurrent"]] = relationship(back_populates="cluster")


# ---------------------------------------------------------------------------
# HOSTS_CURRENT
# ---------------------------------------------------------------------------
class HostCurrent(Base):
    __tablename__ = "hosts_current"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    cluster_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("clusters_current.id"), nullable=True
    )
    source_system_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_systems.id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hypervisor_type: Mapped[Optional[str]] = mapped_column(String(60))      # ESXi / AHV
    hypervisor_version: Mapped[Optional[str]] = mapped_column(String(255))
    connection_state: Mapped[Optional[str]] = mapped_column(String(60))
    in_maintenance_mode: Mapped[Optional[bool]] = mapped_column(Boolean)
    num_cpu_sockets: Mapped[Optional[int]] = mapped_column(Integer)
    num_cpu_cores: Mapped[Optional[int]] = mapped_column(Integer)
    num_cpu_threads: Mapped[Optional[int]] = mapped_column(Integer)
    cpu_capacity_ghz: Mapped[Optional[float]] = mapped_column(Float)
    memory_capacity_gb: Mapped[Optional[float]] = mapped_column(Float)
    cpu_usage_mhz: Mapped[Optional[int]] = mapped_column(Integer)       # latest snapshot — see HostMetricsHistory for the trend
    memory_usage_mb: Mapped[Optional[int]] = mapped_column(Integer)     # latest snapshot — see HostMetricsHistory for the trend
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_system_id", "source_id", name="uq_host_source"),
    )

    cluster: Mapped[Optional["ClusterCurrent"]] = relationship(back_populates="hosts")
    source_system: Mapped["SourceSystem"] = relationship()
    vms: Mapped[list["VmCurrent"]] = relationship(back_populates="host")


# ---------------------------------------------------------------------------
# HOST_METRICS_HISTORY — raw, full-resolution CPU/memory usage observations,
# but only ever the *last hour's* worth (both the full inventory sync and
# the lightweight host-metrics pull write here — see host_metrics_sync.py's
# _record_metrics_history). Rows older than 1 hour are rolled up into
# HostMetricsHistoryRollup and deleted from here — mirrors
# DatastoreMetricsHistory's design exactly.
# ---------------------------------------------------------------------------
class HostMetricsHistory(Base):
    __tablename__ = "host_metrics_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    host_id: Mapped[str] = mapped_column(String(36), ForeignKey("hosts_current.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    cpu_usage_mhz: Mapped[Optional[int]] = mapped_column(Integer)
    cpu_capacity_ghz: Mapped[Optional[float]] = mapped_column(Float)
    memory_usage_mb: Mapped[Optional[int]] = mapped_column(Integer)
    memory_capacity_gb: Mapped[Optional[float]] = mapped_column(Float)


# ---------------------------------------------------------------------------
# HOST_METRICS_HISTORY_ROLLUP — one row per host per hour, for data older
# than the last hour. Stores min/max alongside avg for the same reason as
# DatastoreMetricsHistoryRollup: a brief CPU/memory spike shouldn't be
# smoothed away once raw resolution is gone. Pruned at
# sync.host_metrics_retention_days (Settings -> Sync Engine, default 90).
# ---------------------------------------------------------------------------
class HostMetricsHistoryRollup(Base):
    __tablename__ = "host_metrics_history_rollup"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    host_id: Mapped[str] = mapped_column(String(36), ForeignKey("hosts_current.id"), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)   # truncated to the hour, UTC
    cpu_usage_mhz_avg: Mapped[Optional[float]] = mapped_column(Float)
    cpu_usage_mhz_min: Mapped[Optional[float]] = mapped_column(Float)
    cpu_usage_mhz_max: Mapped[Optional[float]] = mapped_column(Float)
    cpu_capacity_ghz_avg: Mapped[Optional[float]] = mapped_column(Float)
    memory_usage_mb_avg: Mapped[Optional[float]] = mapped_column(Float)
    memory_usage_mb_min: Mapped[Optional[float]] = mapped_column(Float)
    memory_usage_mb_max: Mapped[Optional[float]] = mapped_column(Float)
    memory_capacity_gb_avg: Mapped[Optional[float]] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("host_id", "bucket_start", name="uq_host_metrics_rollup_bucket"),
    )


# ---------------------------------------------------------------------------
# NETWORKS_CURRENT
# ---------------------------------------------------------------------------
class NetworkCurrent(Base):
    __tablename__ = "networks_current"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_system_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_systems.id"), nullable=False
    )
    source_id: Mapped[Optional[str]] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vlan_id: Mapped[Optional[str]] = mapped_column(String(60))     # int, "trunk", or "pvlan:N"
    vswitch_or_dvs_name: Mapped[Optional[str]] = mapped_column(String(255))
    subnet_cidr: Mapped[Optional[str]] = mapped_column(String(60))
    default_gateway: Mapped[Optional[str]] = mapped_column(String(60))
    dhcp_enabled: Mapped[Optional[bool]] = mapped_column(Boolean)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    source_system: Mapped["SourceSystem"] = relationship(back_populates="networks")


# ---------------------------------------------------------------------------
# DATASTORES_CURRENT
# connectivity_type is a plain string (not a DB enum), matching the style
# used for power_state/source_platform/connection_state elsewhere in this
# file — validated at the adapter layer, not the DB layer. Valid values:
# ISCSI, FC, LOCAL, SAS, NFS, NFS41, VSAN, VVOL, NUTANIX_CONTAINER, UNKNOWN.
# ---------------------------------------------------------------------------
class DatastoreCurrent(Base):
    __tablename__ = "datastores_current"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_system_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_systems.id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity_gb: Mapped[Optional[float]] = mapped_column(Float)
    used_gb: Mapped[Optional[float]] = mapped_column(Float)
    free_gb: Mapped[Optional[float]] = mapped_column(Float)
    type: Mapped[Optional[str]] = mapped_column(String(30))   # raw platform type: VMFS/NFS/NFS41/vsan/VVOL/NutanixContainer
    connectivity_type: Mapped[str] = mapped_column(String(30), default="UNKNOWN", nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_system_id", "source_id", name="uq_datastore_source"),
    )

    source_system: Mapped["SourceSystem"] = relationship(back_populates="datastores")


# ---------------------------------------------------------------------------
# DATASTORE_METRICS_HISTORY — raw, full-resolution observations, but only
# ever the *last hour's* worth (both the full inventory sync and the
# lightweight datastore-metrics pull write here — see datastore_sync.py's
# _record_metrics_history). Rows older than 1 hour are rolled up into
# DatastoreMetricsHistoryRollup and deleted from here — see
# datastore_sync.rollup_and_prune_datastore_metrics — so this table stays
# small regardless of retention window.
# ---------------------------------------------------------------------------
class DatastoreMetricsHistory(Base):
    __tablename__ = "datastore_metrics_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    datastore_id: Mapped[str] = mapped_column(String(36), ForeignKey("datastores_current.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    capacity_gb: Mapped[Optional[float]] = mapped_column(Float)
    used_gb: Mapped[Optional[float]] = mapped_column(Float)
    free_gb: Mapped[Optional[float]] = mapped_column(Float)


# ---------------------------------------------------------------------------
# DATASTORE_METRICS_HISTORY_ROLLUP — one row per datastore per hour, for
# data older than the last hour. Stores min/max alongside avg specifically
# so a brief spike or dip inside an hour isn't smoothed away once it's no
# longer available at raw resolution — the detail-page chart plots a
# min/max band, not just the average line. Pruned at
# sync.datastore_metrics_retention_days (Settings -> Sync Engine, default
# 90) by the same rollup job that creates these rows.
# ---------------------------------------------------------------------------
class DatastoreMetricsHistoryRollup(Base):
    __tablename__ = "datastore_metrics_history_rollup"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    datastore_id: Mapped[str] = mapped_column(String(36), ForeignKey("datastores_current.id"), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)   # truncated to the hour, UTC
    capacity_gb_avg: Mapped[Optional[float]] = mapped_column(Float)
    capacity_gb_min: Mapped[Optional[float]] = mapped_column(Float)
    capacity_gb_max: Mapped[Optional[float]] = mapped_column(Float)
    used_gb_avg: Mapped[Optional[float]] = mapped_column(Float)
    used_gb_min: Mapped[Optional[float]] = mapped_column(Float)
    used_gb_max: Mapped[Optional[float]] = mapped_column(Float)
    free_gb_avg: Mapped[Optional[float]] = mapped_column(Float)
    free_gb_min: Mapped[Optional[float]] = mapped_column(Float)
    free_gb_max: Mapped[Optional[float]] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("datastore_id", "bucket_start", name="uq_datastore_metrics_rollup_bucket"),
    )


# ---------------------------------------------------------------------------
# VMS_CURRENT
# ---------------------------------------------------------------------------
class VmCurrent(Base):
    __tablename__ = "vms_current"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(20), nullable=False)     # "vmware" | "nutanix"
    source_system_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_systems.id"), nullable=False
    )
    host_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("hosts_current.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    power_state: Mapped[str] = mapped_column(String(20), nullable=False)   # on | off | suspended | unknown
    os_type: Mapped[Optional[str]] = mapped_column(String(255))
    vcpu: Mapped[Optional[int]] = mapped_column(Integer)
    memory_mb: Mapped[Optional[int]] = mapped_column(Integer)
    disk_gb: Mapped[Optional[float]] = mapped_column(Float)
    primary_ip: Mapped[Optional[str]] = mapped_column(String(60))
    nics: Mapped[Optional[dict]] = mapped_column(JSONB)         # array per VMRecord.nics shape
    disks: Mapped[Optional[dict]] = mapped_column(JSONB)        # array per VMRecord.disks shape
    tools_status: Mapped[Optional[str]] = mapped_column(String(60))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_decommissioned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decommissioned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_sync_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("sync_runs.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("source_platform", "source_id", name="uq_vm_platform_source"),
    )

    host: Mapped[Optional["HostCurrent"]] = relationship(back_populates="vms")
    source_system: Mapped["SourceSystem"] = relationship()
    history: Mapped[list["VmHistory"]] = relationship(back_populates="vm")
    metadata_: Mapped[Optional["VmMetadata"]] = relationship(back_populates="vm", uselist=False)


# ---------------------------------------------------------------------------
# SYNC_RUNS — first-class run record: one row per execution of either adapter
# ---------------------------------------------------------------------------
class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_system_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("source_systems.id"), nullable=True
    )
    source_platform: Mapped[str] = mapped_column(String(20), nullable=False)
    run_type: Mapped[str] = mapped_column(String(30), default="full", nullable=False)   # "full" | "datastore_metrics"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    records_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_ok: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_dead_lettered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    validation_report: Mapped[Optional[dict]] = mapped_column(JSONB)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    source_system: Mapped[Optional["SourceSystem"]] = relationship(back_populates="sync_runs")
    vm_history: Mapped[list["VmHistory"]] = relationship(back_populates="sync_run")
    dead_letters: Mapped[list["DeadLetterRecord"]] = relationship(back_populates="sync_run")


# ---------------------------------------------------------------------------
# VM_HISTORY — one row per VM per run where a meaningful field changed
# ---------------------------------------------------------------------------
class VmHistory(Base):
    __tablename__ = "vm_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    vm_id: Mapped[str] = mapped_column(String(36), ForeignKey("vms_current.id"), nullable=False)
    sync_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("sync_runs.id"), nullable=False)
    changed_fields: Mapped[dict] = mapped_column(JSONB, nullable=False)   # {"field": {"old":..., "new":...}}
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    vm: Mapped["VmCurrent"] = relationship(back_populates="history")
    sync_run: Mapped["SyncRun"] = relationship(back_populates="vm_history")


# ---------------------------------------------------------------------------
# DEAD_LETTER_RECORDS — records that failed processing, held for review/retry
# ---------------------------------------------------------------------------
class DeadLetterRecord(Base):
    __tablename__ = "dead_letter_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sync_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("sync_runs.id"), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    sync_run: Mapped["SyncRun"] = relationship(back_populates="dead_letters")
