"""
sync/base.py — Shared sync infrastructure: canonical VMRecord schema,
ValidationReport, IP classification, and the diff/load engine.

The diff/load engine lives here once, shared by both platform adapters —
neither adapter contains platform-agnostic diff/load logic.
"""
import ipaddress
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

log = structlog.get_logger()

# Fields that constitute a "meaningful change" for VM_HISTORY.
# Live-usage stats (cpu_usage_mhz etc.) are intentionally excluded to avoid noise.
MEANINGFUL_VM_FIELDS = [
    "name", "power_state", "os_type", "vcpu", "memory_mb",
    "disk_gb", "primary_ip", "cluster", "host_node",
]

APIPA_NETWORK = ipaddress.ip_network("169.254.0.0/16")


# ---------------------------------------------------------------------------
# Canonical VMRecord — identical shape to the prototype scripts
# ---------------------------------------------------------------------------

@dataclass
class VMRecord:
    source_id: str
    source_platform: str
    name: str
    power_state: str            # normalized: "on" | "off" | "suspended" | "unknown"
    os_type: Optional[str]
    vcpu: Optional[int]
    memory_mb: Optional[int]
    disk_gb: Optional[float]
    cluster: Optional[str]
    host_node: Optional[str]
    nics: list[dict[str, Any]] = field(default_factory=list)
    disks: list[dict[str, Any]] = field(default_factory=list)
    primary_ip: Optional[str] = None
    last_synced_at: str = ""

    tools_status: Optional[str] = None
    created_at: Optional[str] = None

    # Layer B placeholders — always null from sync, never written here
    owner: Optional[str] = None
    department: Optional[str] = None
    environment: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Validation / quality report — same as prototype scripts, now persisted to DB
# ---------------------------------------------------------------------------

class ValidationReport:
    def __init__(self):
        self.total_seen: int = 0
        self.total_ok: int = 0
        self.total_failed: int = 0
        self.total_skipped: int = 0       # templates (VMware) or agent VMs (Nutanix)
        self.total_invalid_ips: int = 0
        self.missing_field_counts: dict[str, int] = {}
        self.failures: list[dict[str, str]] = []

    def note_missing(self, field_name: str) -> None:
        self.missing_field_counts[field_name] = self.missing_field_counts.get(field_name, 0) + 1

    def note_failure(self, identifier: str, error: str) -> None:
        self.total_failed += 1
        self.failures.append({"vm": identifier, "error": error})
        log.warning("vm_mapping_failed", vm=identifier, error=error)

    def summary(self) -> dict:
        return {
            "total_seen": self.total_seen,
            "total_ok": self.total_ok,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "total_invalid_ips": self.total_invalid_ips,
            "missing_field_counts": self.missing_field_counts,
            "failures": self.failures,
        }


# ---------------------------------------------------------------------------
# IP validity classification — identical rule in both adapters
# ---------------------------------------------------------------------------

def classify_nic_ips(raw_ips: list[str]) -> list[dict[str, Any]]:
    """
    Classifies IPs per-NIC, not per-address:
    - IPv4 APIPA (169.254.x.x)      → always invalid
    - Any other IPv4                → valid
    - IPv6                          → valid only if same NIC has a valid IPv4
    - Empty / unparseable           → invalid
    """
    parsed: list[tuple[str, Any]] = []
    for ip_str in raw_ips:
        if not ip_str:
            parsed.append((ip_str, None))
            continue
        try:
            parsed.append((ip_str, ipaddress.ip_address(ip_str)))
        except ValueError:
            parsed.append((ip_str, "unparseable"))

    has_valid_ipv4 = any(
        addr is not None
        and addr != "unparseable"
        and addr.version == 4
        and addr not in APIPA_NETWORK
        for _, addr in parsed
    )

    entries: list[dict[str, Any]] = []
    for ip_str, addr in parsed:
        if addr is None:
            entries.append({"ip": ip_str, "valid": False, "reason": "empty"})
        elif addr == "unparseable":
            entries.append({"ip": ip_str, "valid": False, "reason": "unparseable"})
        elif addr.version == 4:
            if addr in APIPA_NETWORK:
                entries.append({"ip": ip_str, "valid": False, "reason": "apipa_link_local"})
            else:
                entries.append({"ip": ip_str, "valid": True, "reason": None})
        else:  # IPv6
            valid = has_valid_ipv4
            entries.append({"ip": ip_str, "valid": valid, "reason": None if valid else "ipv6_only"})

    return entries


# ---------------------------------------------------------------------------
# Diff/load engine — shared module, not duplicated per platform
# ---------------------------------------------------------------------------

def compute_vm_diff(
    existing_row,
    new_record: VMRecord,
    *,
    old_cluster: Optional[str] = None,
    old_host_node: Optional[str] = None,
) -> dict[str, dict]:
    """
    Compare MEANINGFUL_VM_FIELDS between the DB row and the fresh VMRecord.
    Returns a dict of {"field": {"old": ..., "new": ...}} for changed fields only.

    "cluster" and "host_node" are not real columns on VmCurrent (only host_id
    is) — callers must resolve the VM's *previous* cluster/host names (e.g.
    via its current host_id, before that gets overwritten) and pass them in
    here. Falling back to getattr() on existing_row for these two would
    silently read None every time and report a false "changed" diff on
    every sync run, even when nothing actually moved.
    """
    changes: dict[str, dict] = {}
    for field_name in MEANINGFUL_VM_FIELDS:
        if field_name == "cluster":
            old_val = old_cluster
        elif field_name == "host_node":
            old_val = old_host_node
        else:
            old_val = getattr(existing_row, field_name, None)
        new_val = getattr(new_record, field_name, None)
        if old_val != new_val:
            changes[field_name] = {"old": old_val, "new": new_val}
    return changes
