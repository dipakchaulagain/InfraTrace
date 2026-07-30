"""
sync/vmware_adapter.py — Production VMware adapter.

Wraps the validated Phase 1 logic from vmware_sync.py with:
  - Retry/exponential backoff via tenacity
  - Structured logging via structlog
  - Writes to DB (VmCurrent, HostCurrent, ClusterCurrent, NetworkCurrent,
    SyncRun, VmHistory, DeadLetterRecord) rather than to JSON files

Circuit-breaker principle: if vCenter is unreachable, a SyncRun row is
written with status="failed" and the function returns — it does not crash
the process or block the Nutanix sync.
"""
import ssl
import sys
from datetime import datetime, timezone
from typing import Optional, Any

import structlog
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log, RetryError,
)

from app.config import settings
from app.sync.base import VMRecord, ValidationReport, classify_nic_ips, compute_vm_diff

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Optional pyVmomi import — adapter still loads if not installed (fails at run time)
# ---------------------------------------------------------------------------
try:
    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim
    _PYVMOMI_AVAILABLE = True
except ImportError:
    _PYVMOMI_AVAILABLE = False
    log.warning("pyvmomi_not_installed", msg="Install pyvmomi to use the VMware adapter")


POWER_STATE_MAP = {
    "poweredOn": "on",
    "poweredOff": "off",
    "suspended": "suspended",
}


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _build_ssl_context(insecure: bool):
    if insecure:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(settings.SYNC_RETRY_MAX_ATTEMPTS),
    wait=wait_exponential(
        min=settings.SYNC_RETRY_WAIT_MIN,
        max=settings.SYNC_RETRY_WAIT_MAX,
    ),
    reraise=True,
)
def _connect_vcenter(host: str, user: str, password: str, port: int, insecure: bool):
    ctx = _build_ssl_context(insecure)
    return SmartConnect(host=host, user=user, pwd=password, port=port, sslContext=ctx)


# ---------------------------------------------------------------------------
# VLAN lookup — built once per sync run, shared across all VMs
# ---------------------------------------------------------------------------

def _parse_dvs_vlan_config(pg) -> Optional[Any]:
    try:
        cfg = pg.config.defaultPortConfig.vlan if pg.config and pg.config.defaultPortConfig else None
        if cfg is not None:
            if hasattr(cfg, "vlanId") and isinstance(getattr(cfg, "vlanId"), int):
                return "trunk" if cfg.vlanId == 4095 else cfg.vlanId
            elif hasattr(cfg, "pvlanId"):
                return f"pvlan:{cfg.pvlanId}"
            elif hasattr(cfg, "vlanId"):
                return "trunk"
    except Exception:
        pass
    return None


def _build_dvs_vlan_map(si) -> dict[str, Any]:
    vlan_map: dict[str, Any] = {}
    try:
        content = si.RetrieveContent()
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.dvs.DistributedVirtualPortgroup], True
        )
        for pg in container.view:
            vlan_map[pg.key] = _parse_dvs_vlan_config(pg)
        container.Destroy()
    except Exception as exc:
        log.warning("dvs_vlan_map_error", error=str(exc))
    return vlan_map


def _build_standard_pg_vlan_map(si) -> dict[tuple, Any]:
    pg_map: dict[tuple, Any] = {}
    try:
        content = si.RetrieveContent()
        container = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
        for host in container.view:
            try:
                net_cfg = host.config.network if host.config else None
                for pg in (net_cfg.portgroup if net_cfg else []):
                    vlan_id = pg.spec.vlanId
                    pg_map[(host.name, pg.spec.name)] = "trunk" if vlan_id == 4095 else vlan_id
            except Exception:
                pass
        container.Destroy()
    except Exception as exc:
        log.warning("standard_pg_vlan_map_error", error=str(exc))
    return pg_map


def _build_vlan_lookup(si) -> dict[str, dict]:
    return {
        "standard": _build_standard_pg_vlan_map(si),
        "distributed": _build_dvs_vlan_map(si),
    }


def _get_vlan_id(device, host_name: Optional[str], vlan_lookup: dict) -> Optional[Any]:
    try:
        backing = device.backing
        if backing is None:
            return None
        port = getattr(backing, "port", None)
        if port is not None:
            return vlan_lookup["distributed"].get(port.portgroupKey)
        network_name = getattr(backing, "deviceName", None)
        if network_name and host_name:
            return vlan_lookup["standard"].get((host_name, network_name))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# NIC / disk builders
# ---------------------------------------------------------------------------

def _build_nics(vm, devices: list, host_name: Optional[str],
                vlan_lookup: dict, report: ValidationReport) -> list[dict]:
    device_by_key = {
        d.key: d for d in devices
        if isinstance(d, vim.vm.device.VirtualEthernetCard)
    }

    guest = vm.guest
    guest_net = guest.net if guest and guest.net else []

    if not guest_net:
        report.note_missing("nics (no guest.net — VMware Tools likely not running)")
        return [
            {
                "label": d.deviceInfo.label if d.deviceInfo else None,
                "mac_address": getattr(d, "macAddress", None),
                "vlan_id": _get_vlan_id(d, host_name, vlan_lookup),
                "connected": bool(d.connectable.connected) if getattr(d, "connectable", None) else None,
                "ip_addresses": [],
            }
            for d in device_by_key.values()
        ]

    nics = []
    for nic in guest_net:
        device = device_by_key.get(nic.deviceConfigId)
        label = device.deviceInfo.label if device and device.deviceInfo else f"NIC (device {nic.deviceConfigId})"
        mac = nic.macAddress or None
        if not mac:
            report.note_missing("nic_mac_address")

        vlan_id = _get_vlan_id(device, host_name, vlan_lookup) if device else None
        if vlan_id is None:
            report.note_missing("nic_vlan_id")

        raw_ips: list[str] = []
        if nic.ipConfig and nic.ipConfig.ipAddress:
            raw_ips = [e.ipAddress for e in nic.ipConfig.ipAddress]
        elif nic.ipAddress:
            raw_ips = list(nic.ipAddress)

        ip_entries = classify_nic_ips(raw_ips)
        for e in ip_entries:
            if not e["valid"]:
                report.total_invalid_ips += 1

        nics.append({
            "label": label,
            "mac_address": mac,
            "vlan_id": vlan_id,
            "connected": bool(nic.connected) if nic.connected is not None else None,
            "ip_addresses": ip_entries,
        })

    return nics


def _build_disks(devices: list, report: ValidationReport) -> list[dict]:
    disks = []
    for d in devices:
        if not isinstance(d, vim.vm.device.VirtualDisk):
            continue
        capacity_gb = round(d.capacityInKB / (1024 ** 2), 2) if d.capacityInKB else None
        thin_provisioned = None
        datastore_name = None
        try:
            backing = d.backing
            thin_provisioned = getattr(backing, "thinProvisioned", None)
            ds = getattr(backing, "datastore", None)
            datastore_name = ds.name if ds else None
        except Exception:
            pass
        disks.append({
            "label": d.deviceInfo.label if d.deviceInfo else None,
            "capacity_gb": capacity_gb,
            "thin_provisioned": thin_provisioned,
            "datastore": datastore_name,
        })
    if not disks:
        report.note_missing("disks")
    return disks


# ---------------------------------------------------------------------------
# VM mapping: vim.VirtualMachine -> VMRecord
# ---------------------------------------------------------------------------

def _map_vm(vm, report: ValidationReport, vlan_lookup: dict,
             include_templates: bool = False) -> Optional[VMRecord]:
    summary = vm.summary
    config = summary.config
    runtime = summary.runtime
    guest_summary = summary.guest
    identifier = config.name if config and config.name else "unknown"

    if config and getattr(config, "template", False) and not include_templates:
        report.total_skipped += 1
        return None

    try:
        source_id = config.instanceUuid or vm._moId
        if not config.instanceUuid:
            report.note_missing("source_id (instanceUuid, fell back to MoRef)")

        raw_power = runtime.powerState if runtime else None
        power_state = POWER_STATE_MAP.get(raw_power, "unknown")
        if power_state == "unknown":
            report.note_missing("power_state")

        os_type = config.guestFullName if config else None
        if not os_type:
            report.note_missing("os_type")

        vcpu = config.numCpu if config else None
        if vcpu is None:
            report.note_missing("vcpu")

        memory_mb = config.memorySizeMB if config else None
        if memory_mb is None:
            report.note_missing("memory_mb")

        devices = []
        try:
            devices = vm.config.hardware.device if vm.config and vm.config.hardware else []
        except Exception:
            pass

        disks = _build_disks(devices, report)
        disk_gb = round(sum(d["capacity_gb"] for d in disks if d["capacity_gb"]), 2) if disks else None

        cluster = None
        host_node = None
        host = None
        try:
            host = runtime.host if runtime else None
            if host:
                host_node = host.name
                if host.parent and isinstance(host.parent, vim.ClusterComputeResource):
                    cluster = host.parent.name
        except Exception:
            pass
        if not cluster:
            report.note_missing("cluster")
        if not host_node:
            report.note_missing("host_node")

        nics = _build_nics(vm, devices, host.name if host else None, vlan_lookup, report)
        primary_ip = next(
            (e["ip"] for nic in nics for e in nic["ip_addresses"] if e["valid"]), None
        )
        if primary_ip is None:
            report.note_missing("primary_ip (no valid IP across any NIC)")

        tools_status = guest_summary.toolsStatus if guest_summary else None

        created_at = None
        try:
            if config and getattr(config, "createDate", None):
                created_at = config.createDate.isoformat()
        except Exception:
            pass

        record = VMRecord(
            source_id=str(source_id),
            source_platform="vmware",
            name=identifier,
            power_state=power_state,
            os_type=os_type,
            vcpu=vcpu,
            memory_mb=memory_mb,
            disk_gb=disk_gb,
            cluster=cluster,
            host_node=host_node,
            nics=nics,
            disks=disks,
            primary_ip=primary_ip,
            last_synced_at=datetime.now(timezone.utc).isoformat(),
            tools_status=tools_status,
            created_at=created_at,
            raw={
                "annotation": getattr(config, "annotation", None) if config else None,
                "hw_version": getattr(config, "version", None) if config else None,
            },
        )
        report.total_ok += 1
        return record

    except Exception as exc:
        report.note_failure(identifier, str(exc))
        return None


# ---------------------------------------------------------------------------
# Host mapping: vim.HostSystem -> dict (for HostCurrent upsert)
# ---------------------------------------------------------------------------

def _map_host(h) -> dict:
    summary = h.summary
    hw = summary.hardware if summary else None
    runtime = summary.runtime if summary else None
    quickstats = summary.quickStats if summary else None
    config = summary.config if summary else None

    cluster = None
    try:
        if h.parent and isinstance(h.parent, vim.ClusterComputeResource):
            cluster = h.parent.name
    except Exception:
        pass

    cpu_mhz = hw.cpuMhz if hw else None
    num_cores = hw.numCpuCores if hw else None
    cpu_capacity_ghz = round((cpu_mhz * num_cores) / 1000, 2) if cpu_mhz and num_cores else None
    memory_gb = round(hw.memorySize / (1024 ** 3), 2) if hw and hw.memorySize else None
    esxi_version = config.product.fullName if config and config.product else None

    return {
        "source_id": h._moId,
        "name": config.name if config and config.name else h.name,
        "cluster_name": cluster,
        "hypervisor_type": "ESXi",
        "hypervisor_version": esxi_version,
        "connection_state": str(runtime.connectionState) if runtime else None,
        "in_maintenance_mode": runtime.inMaintenanceMode if runtime else None,
        "num_cpu_sockets": hw.numCpuPkgs if hw else None,
        "num_cpu_cores": num_cores,
        "num_cpu_threads": hw.numCpuThreads if hw else None,
        "cpu_capacity_ghz": cpu_capacity_ghz,
        "memory_capacity_gb": memory_gb,
        "cpu_usage_mhz": quickstats.overallCpuUsage if quickstats else None,
        "memory_usage_mb": quickstats.overallMemoryUsage if quickstats else None,
    }


# ---------------------------------------------------------------------------
# Main entry point — called by the sync runner / scheduler
# ---------------------------------------------------------------------------

def run_vmware_sync(db_session, source_system_id: str) -> dict:
    """
    Full VMware sync pass. SyncRun is always created first so the UI
    always sees a result, even if credentials are missing or pyvmomi
    is not installed.
    """
    from app.models.inventory import (
        SyncRun, VmCurrent, HostCurrent, ClusterCurrent, VmHistory, DeadLetterRecord
    )
    from datetime import datetime, timezone

    # Create the run row immediately so the UI always sees feedback
    run = SyncRun(
        source_system_id=source_system_id,
        source_platform="vmware",
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db_session.add(run)
    db_session.commit()

    log.info("vmware_sync_start", run_id=run.id, source_system_id=source_system_id)

    def _fail(msg: str) -> dict:
        run.status = "failed"
        run.error_message = msg
        run.completed_at = datetime.now(timezone.utc)
        try:
            db_session.commit()
        except Exception:
            db_session.rollback()
        return {"status": "failed", "error": msg}

    if not _PYVMOMI_AVAILABLE:
        return _fail("pyvmomi not installed — run: pip install pyvmomi")

    # Resolve credentials: DB values override .env
    from app.sync.connector_settings import get_vmware_creds, get_sync_engine_settings
    creds = get_vmware_creds(db_session, source_system_id)
    if creds is None:
        return _fail("VMware credentials not configured — go to Settings and save host, username, and password.")

    sync_cfg = get_sync_engine_settings(db_session)
    log.info("vmware_sync_connecting", run_id=run.id, host=creds.host)

    log.info("vmware_sync_start", run_id=run.id, vcenter=creds.host)

    si = None
    try:
        # -- Connect --
        try:
            si = _connect_vcenter(
                creds.host, creds.user, creds.password,
                creds.port, creds.insecure,
            )
        except (RetryError, Exception) as exc:
            log.error("vcenter_connect_failed", error=str(exc))
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            db_session.commit()
            return {"status": "failed", "error": str(exc)}

        content = si.RetrieveContent()

        # -- Hosts --
        host_container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True
        )
        raw_hosts = list(host_container.view)
        host_container.Destroy()
        log.info("vcenter_hosts_fetched", count=len(raw_hosts))

        # Upsert clusters and hosts
        cluster_name_to_id: dict[str, str] = {}
        host_name_to_db_id: dict[str, str] = {}

        for h in raw_hosts:
            hdata = _map_host(h)
            cluster_name = hdata.pop("cluster_name", None)

            # Ensure cluster row exists
            cluster_db_id = None
            if cluster_name:
                if cluster_name not in cluster_name_to_id:
                    existing_cluster = db_session.query(ClusterCurrent).filter_by(
                        source_system_id=source_system_id, name=cluster_name
                    ).first()
                    if not existing_cluster:
                        existing_cluster = ClusterCurrent(
                            source_system_id=source_system_id,
                            name=cluster_name,
                        )
                        db_session.add(existing_cluster)
                        db_session.flush()
                    cluster_name_to_id[cluster_name] = existing_cluster.id
                cluster_db_id = cluster_name_to_id[cluster_name]

            # Upsert host
            existing_host = db_session.query(HostCurrent).filter_by(
                source_system_id=source_system_id, source_id=hdata["source_id"]
            ).first()
            if existing_host:
                for k, v in hdata.items():
                    setattr(existing_host, k, v)
                existing_host.cluster_id = cluster_db_id
                existing_host.last_synced_at = datetime.now(timezone.utc)
                host_name_to_db_id[existing_host.name] = existing_host.id
            else:
                new_host = HostCurrent(
                    source_system_id=source_system_id,
                    cluster_id=cluster_db_id,
                    **hdata,
                )
                db_session.add(new_host)
                db_session.flush()
                host_name_to_db_id[new_host.name] = new_host.id

        db_session.commit()

        # -- Networks (portgroups/VLANs) --
        log.info("vcenter_fetching_networks")
        network_records: list[dict] = []
        try:
            # Standard vSwitch portgroups (per host)
            seen_pg_names: set[str] = set()
            for h in raw_hosts:
                try:
                    net_cfg = h.config.network if h.config else None
                    for pg in (net_cfg.portgroup if net_cfg else []):
                        key = pg.spec.name
                        if key in seen_pg_names:
                            continue
                        seen_pg_names.add(key)
                        vlan_id = pg.spec.vlanId
                        network_records.append({
                            "source_id": f"std:{pg.spec.name}",
                            "name": pg.spec.name,
                            "vlan_id": "trunk" if vlan_id == 4095 else vlan_id,
                            "vswitch_or_dvs_name": pg.spec.vswitchName,
                        })
                except Exception:
                    pass

            # Distributed vSwitch portgroups
            dvs_container = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.dvs.DistributedVirtualPortgroup], True
            )
            for pg in dvs_container.view:
                vlan_id = _parse_dvs_vlan_config(pg)
                network_records.append({
                    "source_id": f"dvs:{pg.key}",
                    "name": pg.name,
                    "vlan_id": vlan_id,
                    "vswitch_or_dvs_name": pg.config.distributedVirtualSwitch.name
                    if (pg.config and pg.config.distributedVirtualSwitch) else None,
                })
            dvs_container.Destroy()
        except Exception as exc:
            log.warning("vcenter_networks_fetch_error", error=str(exc))

        if network_records:
            from app.sync.network_sync import upsert_networks
            upsert_networks(db_session, source_system_id, network_records)
            db_session.commit()

        # -- VMs --
        vm_container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        raw_vms = list(vm_container.view)
        vm_container.Destroy()
        log.info("vcenter_vms_fetched", count=len(raw_vms))

        vlan_lookup = _build_vlan_lookup(si)

        # host_id -> (host_name, cluster_name), for resolving each VM's *previous*
        # location when diffing — VmCurrent only stores host_id, not cluster/host_node
        # directly, so this can't be read via getattr() on the existing row.
        from sqlalchemy.orm import joinedload
        host_id_to_location: dict[str, tuple[Optional[str], Optional[str]]] = {
            h.id: (h.name, h.cluster.name if h.cluster else None)
            for h in db_session.query(HostCurrent)
                .options(joinedload(HostCurrent.cluster))
                .filter_by(source_system_id=source_system_id)
                .all()
        }

        report = ValidationReport()
        report.total_seen = len(raw_vms)
        synced_source_ids: set[str] = set()

        for raw_vm in raw_vms:
            record = _map_vm(raw_vm, report, vlan_lookup)
            if record is None:
                continue  # template or skipped

            synced_source_ids.add(record.source_id)

            try:
                existing = db_session.query(VmCurrent).filter_by(
                    source_platform="vmware", source_id=record.source_id
                ).first()

                host_db_id = host_name_to_db_id.get(record.host_node) if record.host_node else None

                if existing:
                    old_host_node, old_cluster = host_id_to_location.get(existing.host_id, (None, None))
                    diff = compute_vm_diff(existing, record, old_cluster=old_cluster, old_host_node=old_host_node)
                    if diff:
                        history = VmHistory(
                            vm_id=existing.id,
                            sync_run_id=run.id,
                            changed_fields=diff,
                        )
                        db_session.add(history)
                    # Update in place
                    existing.name = record.name
                    existing.power_state = record.power_state
                    existing.os_type = record.os_type
                    existing.vcpu = record.vcpu
                    existing.memory_mb = record.memory_mb
                    existing.disk_gb = record.disk_gb
                    existing.primary_ip = record.primary_ip
                    existing.nics = record.nics
                    existing.disks = record.disks
                    existing.tools_status = record.tools_status
                    existing.host_id = host_db_id
                    existing.last_synced_at = datetime.now(timezone.utc)
                    existing.last_sync_run_id = run.id
                    existing.is_decommissioned = False
                    existing.decommissioned_at = None
                else:
                    new_vm = VmCurrent(
                        source_id=record.source_id,
                        source_platform="vmware",
                        source_system_id=source_system_id,
                        host_id=host_db_id,
                        name=record.name,
                        power_state=record.power_state,
                        os_type=record.os_type,
                        vcpu=record.vcpu,
                        memory_mb=record.memory_mb,
                        disk_gb=record.disk_gb,
                        primary_ip=record.primary_ip,
                        nics=record.nics,
                        disks=record.disks,
                        tools_status=record.tools_status,
                        last_sync_run_id=run.id,
                    )
                    db_session.add(new_vm)

            except Exception as exc:
                log.error("vm_upsert_error", vm=record.name, error=str(exc))
                dead = DeadLetterRecord(
                    sync_run_id=run.id,
                    source_platform="vmware",
                    raw_payload=record.to_dict(),
                    error_message=str(exc),
                )
                db_session.add(dead)
                run.records_dead_lettered = (run.records_dead_lettered or 0) + 1

        db_session.flush()

        # -- Decommission VMs not seen this run --
        decommissioned = (
            db_session.query(VmCurrent)
            .filter(
                VmCurrent.source_platform == "vmware",
                VmCurrent.source_system_id == source_system_id,
                VmCurrent.is_decommissioned.is_(False),
                VmCurrent.source_id.notin_(synced_source_ids),
            )
            .all()
        )
        for vm_row in decommissioned:
            vm_row.is_decommissioned = True
            vm_row.decommissioned_at = datetime.now(timezone.utc)
            log.info("vm_decommissioned", vm=vm_row.name, source_id=vm_row.source_id)
            from app.audit import log_event
            log_event(db_session, actor=None, actor_type="service", action="vm_decommissioned",
                       entity_type="vm", entity_id=vm_row.id, details={"name": vm_row.name})

        # -- Finalize run --
        run.status = "partial" if (report.total_failed > 0 or run.records_dead_lettered > 0) else "success"
        run.records_seen = report.total_seen
        run.records_ok = report.total_ok
        run.records_failed = report.total_failed
        run.records_dead_lettered = run.records_dead_lettered or 0
        run.validation_report = report.summary()
        run.completed_at = datetime.now(timezone.utc)
        db_session.commit()

        log.info(
            "vmware_sync_complete",
            run_id=run.id,
            status=run.status,
            seen=run.records_seen,
            ok=run.records_ok,
            failed=run.records_failed,
        )
        return {"status": run.status, "run_id": run.id, "summary": report.summary()}

    except Exception as exc:
        log.error("vmware_sync_unhandled_error", error=str(exc))
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        try:
            db_session.commit()
        except Exception:
            db_session.rollback()
        return {"status": "failed", "error": str(exc)}

    finally:
        if si:
            try:
                Disconnect(si)
            except Exception:
                pass
