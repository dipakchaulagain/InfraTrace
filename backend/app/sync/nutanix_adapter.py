"""
sync/nutanix_adapter.py — Production Nutanix Prism Element adapter (v2.0 API).

Wraps the validated Phase 1 logic from nutanix_sync.py with:
  - Retry/exponential backoff via tenacity
  - Structured logging via structlog
  - Writes to DB (VmCurrent, HostCurrent, ClusterCurrent, NetworkCurrent,
    SyncRun, VmHistory, DeadLetterRecord) rather than to JSON files

Known gaps carried forward from Phase 1:
  - os_type: NOT available via v2 /vms — requires NGT integration (Phase 5).
    Flagged in the validation report, not silently null.
  - power_state: lowercase "on"/"off" from Nutanix, normalised via POWER_STATE_MAP.
  - Total vCPU = num_vcpus × num_cores_per_vcpu (NOT num_vcpus alone).
  - CD-ROM disk entries excluded (is_cdrom=true).
  - Agent VMs excluded by default (vm_features.AGENT_VM).
  - /vms is paginated; we loop until grand_total_entities is reached.
"""
from datetime import datetime, timezone
from typing import Optional, Any

import requests
import structlog
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, RetryError,
)

from app.config import settings
from app.sync.base import VMRecord, ValidationReport, classify_nic_ips, compute_vm_diff

log = structlog.get_logger()

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    pass


POWER_STATE_MAP = {"on": "on", "off": "off"}


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def _build_session(user: str, password: str, insecure: bool) -> requests.Session:
    session = requests.Session()
    session.auth = (user, password)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    session.verify = not insecure
    return session


# ---------------------------------------------------------------------------
# API helpers with retry
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    stop=stop_after_attempt(settings.SYNC_RETRY_MAX_ATTEMPTS),
    wait=wait_exponential(
        min=settings.SYNC_RETRY_WAIT_MIN,
        max=settings.SYNC_RETRY_WAIT_MAX,
    ),
    reraise=True,
)
def _api_get(session: requests.Session, base_url: str, path: str, params: Optional[dict] = None) -> dict:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    resp = session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fetch_all_vms(session: requests.Session, base_url: str, page_size: int) -> list[dict]:
    all_vms: list[dict] = []
    offset = 0
    while True:
        data = _api_get(session, base_url, "vms", params={
            "offset": offset,
            "length": page_size,
            "include_vm_disk_config": "true",
            "include_vm_nic_config": "true",
        })
        entities = data.get("entities", [])
        all_vms.extend(entities)
        meta = data.get("metadata", {})
        grand_total = meta.get("grand_total_entities", len(all_vms))
        offset += len(entities)
        if not entities or offset >= grand_total:
            break
    return all_vms


def _fetch_networks_map(session: requests.Session, base_url: str) -> dict[str, dict]:
    data = _api_get(session, base_url, "networks")
    return {
        net["uuid"]: {"name": net.get("name"), "vlan_id": net.get("vlan_id")}
        for net in data.get("entities", [])
        if net.get("uuid")
    }


def _fetch_hosts_map(session: requests.Session, base_url: str) -> dict[str, dict]:
    data = _api_get(session, base_url, "hosts")
    result: dict[str, dict] = {}
    for h in data.get("entities", []):
        uuid = h.get("uuid")
        if not uuid:
            continue
        memory_bytes = h.get("memory_capacity_in_bytes")
        cpu_hz = h.get("cpu_capacity_in_hz")
        result[uuid] = {
            "source_id": uuid,
            "name": h.get("name"),
            "hypervisor_type": h.get("hypervisor_type"),
            "hypervisor_version": h.get("hypervisor_full_name"),
            "connection_state": h.get("state"),
            "num_cpu_sockets": h.get("num_cpu_sockets"),
            "num_cpu_cores": h.get("num_cpu_cores"),
            "num_cpu_threads": h.get("num_cpu_threads"),
            "cpu_capacity_ghz": round(cpu_hz / 1e9, 2) if cpu_hz else None,
            "memory_capacity_gb": round(memory_bytes / (1024 ** 3), 2) if memory_bytes else None,
            "in_maintenance_mode": None,   # not exposed directly in v2 /hosts
            "cpu_usage_mhz": None,
            "memory_usage_mb": None,
        }
    return result


def _fetch_cluster_name(session: requests.Session, base_url: str) -> Optional[str]:
    try:
        data = _api_get(session, base_url, "cluster")
        return data.get("name")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# VM mapping: raw v2 entity -> VMRecord
# ---------------------------------------------------------------------------

def _map_vm(
    vm: dict,
    hosts_map: dict[str, dict],
    networks_map: dict[str, dict],
    cluster_name: Optional[str],
    report: ValidationReport,
    include_agent_vms: bool = False,
) -> Optional[VMRecord]:
    identifier = vm.get("name") or vm.get("uuid") or "unknown"

    features = vm.get("vm_features") or {}
    if features.get("AGENT_VM") and not include_agent_vms:
        report.total_skipped += 1
        return None

    try:
        source_id = vm.get("uuid")
        if not source_id:
            report.note_missing("source_id")

        raw_power = vm.get("power_state")
        power_state = POWER_STATE_MAP.get(raw_power, "unknown")
        if power_state == "unknown":
            report.note_missing("power_state")

        # os_type: not available via v2 /vms — NGT required (Phase 5)
        os_type = None
        report.note_missing("os_type (not exposed via v2 /vms — requires NGT)")

        num_vcpus = vm.get("num_vcpus")
        num_cores = vm.get("num_cores_per_vcpu")
        vcpu = (num_vcpus * num_cores) if (num_vcpus is not None and num_cores is not None) else None
        if vcpu is None:
            report.note_missing("vcpu")

        memory_mb = vm.get("memory_mb")
        if memory_mb is None:
            report.note_missing("memory_mb")

        disks = []
        for d in (vm.get("vm_disk_info") or []):
            if d.get("is_cdrom"):
                continue
            size_bytes = d.get("size")
            capacity_gb = round(size_bytes / (1024 ** 3), 2) if size_bytes else None
            addr = d.get("disk_address") or {}
            disks.append({
                "label": addr.get("disk_label"),
                "capacity_gb": capacity_gb,
                "thin_provisioned": d.get("is_thin_provisioned"),
                "storage_container_uuid": d.get("storage_container_uuid"),
            })
        if not disks:
            report.note_missing("disks")
        disk_gb = round(sum(d["capacity_gb"] for d in disks if d["capacity_gb"]), 2) if disks else None

        nics = []
        for nic in (vm.get("vm_nics") or []):
            network_uuid = nic.get("network_uuid")
            net_info = networks_map.get(network_uuid, {})
            vlan_id = net_info.get("vlan_id")
            if vlan_id is None:
                report.note_missing("nic_vlan_id")

            mac = nic.get("mac_address")
            if not mac:
                report.note_missing("nic_mac_address")

            raw_ips: list[str] = nic.get("ip_addresses") or (
                [nic["ip_address"]] if nic.get("ip_address") else []
            )
            ip_entries = classify_nic_ips(raw_ips)
            for e in ip_entries:
                if not e["valid"]:
                    report.total_invalid_ips += 1
            if not ip_entries:
                report.note_missing("nic_ip")

            nics.append({
                "label": net_info.get("name") or nic.get("nic_uuid"),
                "mac_address": mac,
                "vlan_id": vlan_id,
                "connected": nic.get("is_connected"),
                "ip_addresses": ip_entries,
            })

        primary_ip = next(
            (e["ip"] for nic in nics for e in nic["ip_addresses"] if e["valid"]), None
        )
        if primary_ip is None:
            report.note_missing("primary_ip (no valid IP across any NIC)")

        host_uuid = vm.get("host_uuid")
        host_info = hosts_map.get(host_uuid, {})
        host_node = host_info.get("name") if host_info else None
        if not host_node:
            report.note_missing("host_node")
        if not cluster_name:
            report.note_missing("cluster")

        record = VMRecord(
            source_id=str(source_id),
            source_platform="nutanix",
            name=identifier,
            power_state=power_state,
            os_type=os_type,
            vcpu=vcpu,
            memory_mb=memory_mb,
            disk_gb=disk_gb,
            cluster=cluster_name,
            host_node=host_node,
            nics=nics,
            disks=disks,
            primary_ip=primary_ip,
            last_synced_at=datetime.now(timezone.utc).isoformat(),
            tools_status=None,
            created_at=None,
            raw={
                "hypervisor_type": vm.get("hypervisor_type"),
                "machine_type": vm.get("machine_type"),
                "timezone": vm.get("timezone"),
            },
        )
        report.total_ok += 1
        return record

    except Exception as exc:
        report.note_failure(identifier, str(exc))
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_nutanix_sync(db_session, source_system_id: str) -> dict:
    """
    Full Nutanix sync pass — SyncRun is always created first so the UI
    always sees a result, even if credentials are missing.
    """
    from app.models.inventory import (
        SyncRun, VmCurrent, HostCurrent, ClusterCurrent, VmHistory, DeadLetterRecord
    )
    from datetime import datetime, timezone

    # Create the run row immediately so the UI always sees feedback
    run = SyncRun(
        source_system_id=source_system_id,
        source_platform="nutanix",
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db_session.add(run)
    db_session.commit()

    log.info("nutanix_sync_start", run_id=run.id, source_system_id=source_system_id)

    # Resolve credentials: DB values override .env
    from app.sync.connector_settings import get_nutanix_creds, get_sync_engine_settings
    creds = get_nutanix_creds(db_session, source_system_id)
    if creds is None:
        msg = "Nutanix credentials not configured — go to Settings and save host, username, and password."
        log.error("nutanix_creds_missing", run_id=run.id)
        run.status = "failed"
        run.error_message = msg
        run.completed_at = datetime.now(timezone.utc)
        db_session.commit()
        return {"status": "failed", "error": msg}

    sync_cfg = get_sync_engine_settings(db_session)

    log.info("nutanix_sync_connecting", run_id=run.id, base_url=creds.base_url)

    try:
        session = _build_session(
            creds.user, creds.password, creds.insecure
        )

        try:
            cluster_name = _fetch_cluster_name(session, creds.base_url)
            hosts_map = _fetch_hosts_map(session, creds.base_url)
            networks_map = _fetch_networks_map(session, creds.base_url)
        except (RetryError, requests.exceptions.RequestException) as exc:
            log.error("nutanix_connect_failed", error=str(exc))
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            db_session.commit()
            return {"status": "failed", "error": str(exc)}

        log.info("nutanix_metadata_fetched",
                 cluster=cluster_name, hosts=len(hosts_map), networks=len(networks_map))

        # Upsert cluster
        cluster_db_id = None
        if cluster_name:
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
            cluster_db_id = existing_cluster.id

        # Upsert hosts
        host_uuid_to_db_id: dict[str, str] = {}
        for host_uuid, hdata in hosts_map.items():
            host_data_copy = {k: v for k, v in hdata.items() if k != "source_id"}
            existing_host = db_session.query(HostCurrent).filter_by(
                source_system_id=source_system_id, source_id=host_uuid
            ).first()
            if existing_host:
                for k, v in host_data_copy.items():
                    setattr(existing_host, k, v)
                existing_host.cluster_id = cluster_db_id
                existing_host.last_synced_at = datetime.now(timezone.utc)
                host_uuid_to_db_id[host_uuid] = existing_host.id
            else:
                new_host = HostCurrent(
                    source_system_id=source_system_id,
                    cluster_id=cluster_db_id,
                    source_id=host_uuid,
                    **host_data_copy,
                )
                db_session.add(new_host)
                db_session.flush()
                host_uuid_to_db_id[host_uuid] = new_host.id

        db_session.commit()

        # -- Networks (subnets/VLANs) --
        network_records = []
        for net_uuid, net_info in networks_map.items():
            network_records.append({
                "source_id": net_uuid,
                "name": net_info.get("name", ""),
                "vlan_id": net_info.get("vlan_id"),
            })
        if network_records:
            from app.sync.network_sync import upsert_networks
            upsert_networks(db_session, source_system_id, network_records)
            db_session.commit()

        # Fetch VMs
        raw_vms = _fetch_all_vms(session, creds.base_url, sync_cfg.page_size)
        log.info("nutanix_vms_fetched", count=len(raw_vms))

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
            record = _map_vm(raw_vm, hosts_map, networks_map, cluster_name, report)
            if record is None:
                continue

            synced_source_ids.add(record.source_id)

            try:
                host_uuid = raw_vm.get("host_uuid")
                host_db_id = host_uuid_to_db_id.get(host_uuid) if host_uuid else None

                existing = db_session.query(VmCurrent).filter_by(
                    source_platform="nutanix", source_id=record.source_id
                ).first()

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
                    existing.name = record.name
                    existing.power_state = record.power_state
                    existing.os_type = record.os_type
                    existing.vcpu = record.vcpu
                    existing.memory_mb = record.memory_mb
                    existing.disk_gb = record.disk_gb
                    existing.primary_ip = record.primary_ip
                    existing.nics = record.nics
                    existing.disks = record.disks
                    existing.host_id = host_db_id
                    existing.last_synced_at = datetime.now(timezone.utc)
                    existing.last_sync_run_id = run.id
                    existing.is_decommissioned = False
                    existing.decommissioned_at = None
                else:
                    new_vm = VmCurrent(
                        source_id=record.source_id,
                        source_platform="nutanix",
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
                        last_sync_run_id=run.id,
                    )
                    db_session.add(new_vm)

            except Exception as exc:
                log.error("vm_upsert_error", vm=record.name, error=str(exc))
                dead = DeadLetterRecord(
                    sync_run_id=run.id,
                    source_platform="nutanix",
                    raw_payload=record.to_dict(),
                    error_message=str(exc),
                )
                db_session.add(dead)
                run.records_dead_lettered = (run.records_dead_lettered or 0) + 1

        db_session.flush()

        # Decommission VMs not seen this run
        decommissioned = (
            db_session.query(VmCurrent)
            .filter(
                VmCurrent.source_platform == "nutanix",
                VmCurrent.source_system_id == source_system_id,
                VmCurrent.is_decommissioned.is_(False),
                VmCurrent.source_id.notin_(synced_source_ids),
            )
            .all()
        )
        for vm_row in decommissioned:
            vm_row.is_decommissioned = True
            vm_row.decommissioned_at = datetime.now(timezone.utc)
            log.info("vm_decommissioned", vm=vm_row.name)
            from app.audit import log_event
            log_event(db_session, actor=None, actor_type="service", action="vm_decommissioned",
                       entity_type="vm", entity_id=vm_row.id, details={"name": vm_row.name})

        run.status = "partial" if (report.total_failed > 0 or run.records_dead_lettered > 0) else "success"
        run.records_seen = report.total_seen
        run.records_ok = report.total_ok
        run.records_failed = report.total_failed
        run.records_dead_lettered = run.records_dead_lettered or 0
        run.validation_report = report.summary()
        run.completed_at = datetime.now(timezone.utc)
        db_session.commit()

        log.info(
            "nutanix_sync_complete",
            run_id=run.id,
            status=run.status,
            seen=run.records_seen,
            ok=run.records_ok,
            failed=run.records_failed,
        )
        return {"status": run.status, "run_id": run.id, "summary": report.summary()}

    except Exception as exc:
        log.error("nutanix_sync_unhandled_error", error=str(exc))
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        try:
            db_session.commit()
        except Exception:
            db_session.rollback()
        return {"status": "failed", "error": str(exc)}
