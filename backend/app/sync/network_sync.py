"""
network_sync.py — Shared helper to upsert NetworkCurrent rows.

Called by both platform adapters after fetching their network data.
Keeps the diff/load for networks in one place, consistent with the
principle from the project plan: one shared module, not duplicated per platform.
"""
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger()


def upsert_networks(db_session, source_system_id: str, networks: list[dict]) -> int:
    """
    Upsert a list of network dicts into NetworkCurrent.

    Each dict should have:
        source_id (str)       — platform-native network UUID/key
        name (str)            — display name
        vlan_id (str|None)    — int, "trunk", "pvlan:N", or None
        vswitch_or_dvs_name   — optional
        subnet_cidr           — optional (Nutanix IPAM)
        default_gateway       — optional
        dhcp_enabled          — optional bool

    Returns the count of rows upserted.
    """
    from app.models.inventory import NetworkCurrent

    upserted = 0
    now = datetime.now(timezone.utc)

    for net in networks:
        source_id = net.get("source_id")
        if not source_id:
            continue

        existing = db_session.query(NetworkCurrent).filter_by(
            source_system_id=source_system_id,
            source_id=source_id,
        ).first()

        if existing:
            existing.name = net.get("name", existing.name)
            existing.vlan_id = str(net["vlan_id"]) if net.get("vlan_id") is not None else None
            existing.vswitch_or_dvs_name = net.get("vswitch_or_dvs_name")
            existing.subnet_cidr = net.get("subnet_cidr")
            existing.default_gateway = net.get("default_gateway")
            existing.dhcp_enabled = net.get("dhcp_enabled")
            existing.last_synced_at = now
        else:
            db_session.add(NetworkCurrent(
                source_system_id=source_system_id,
                source_id=source_id,
                name=net.get("name", ""),
                vlan_id=str(net["vlan_id"]) if net.get("vlan_id") is not None else None,
                vswitch_or_dvs_name=net.get("vswitch_or_dvs_name"),
                subnet_cidr=net.get("subnet_cidr"),
                default_gateway=net.get("default_gateway"),
                dhcp_enabled=net.get("dhcp_enabled"),
                last_synced_at=now,
            ))
        upserted += 1

    db_session.flush()
    log.info("networks_upserted", source_system_id=source_system_id, count=upserted)
    return upserted
