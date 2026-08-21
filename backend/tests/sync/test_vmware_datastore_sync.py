"""
Unit tests for VMware datastore connectivity classification
(app/sync/vmware_adapter.py). Pure functions — no vCenter connection, no DB.

vim.host.*TargetTransport are real pyVmomi data-object classes (client-side
stubs, not managed-object proxies), so they can be instantiated directly and
checked with isinstance() exactly as the adapter code does — no need for
string-based class-name stand-ins.
"""
import types

import pytest
from pyVmomi import vim

from app.sync.base import ValidationReport
from app.sync.vmware_adapter import (
    _classify_datastore_connectivity,
    _resolve_vmfs_transport,
    _datastore_identity,
    _mounting_host_ids,
    _map_datastore,
    _merge_duplicate_datastore_records,
)


def _ds(summary_type, multiple_host_access=True, host_mounts=None, vmfs_extent=None,
        capacity=None, free_space=None, name="ds1", moid="datastore-1", url=None):
    summary = types.SimpleNamespace(
        type=summary_type,
        multipleHostAccess=multiple_host_access,
        name=name,
        capacity=capacity,
        freeSpace=free_space,
        url=url,
    )
    vmfs_info = types.SimpleNamespace(extent=vmfs_extent or []) if vmfs_extent is not None else None
    info = types.SimpleNamespace(vmfs=vmfs_info)
    return types.SimpleNamespace(
        summary=summary,
        info=info,
        host=host_mounts or [],
        name=name,
        _moId=moid,
    )


def _host(scsi_lun=None, adapters=None, moid="host-1"):
    storage_device = types.SimpleNamespace(
        scsiLun=scsi_lun or [],
        scsiTopology=types.SimpleNamespace(adapter=adapters or []),
    )
    config = types.SimpleNamespace(storageDevice=storage_device)
    return types.SimpleNamespace(config=config, _moId=moid)


def _host_mount(host):
    return types.SimpleNamespace(key=host)


def _scsi_lun(key, canonical_name):
    return types.SimpleNamespace(key=key, canonicalName=canonical_name)


def _extent(disk_name):
    return types.SimpleNamespace(diskName=disk_name)


def _adapter(targets):
    return types.SimpleNamespace(target=targets)


def _target(transport, lun_keys):
    return types.SimpleNamespace(
        transport=transport,
        lun=[types.SimpleNamespace(scsiLun=k) for k in lun_keys],
    )


def _report():
    return ValidationReport()


# ---------------------------------------------------------------------------
# summary.type branching
# ---------------------------------------------------------------------------

def test_nfs_datastore():
    ds = _ds("NFS")
    assert _classify_datastore_connectivity(ds, _report()) == "NFS"


def test_nfs41_datastore():
    ds = _ds("NFS41")
    assert _classify_datastore_connectivity(ds, _report()) == "NFS41"


def test_vsan_datastore():
    ds = _ds("vsan")
    assert _classify_datastore_connectivity(ds, _report()) == "VSAN"


def test_vvol_datastore():
    ds = _ds("VVOL")
    assert _classify_datastore_connectivity(ds, _report()) == "VVOL"


def test_unrecognized_type_is_unknown():
    ds = _ds("CIFS")
    assert _classify_datastore_connectivity(ds, _report()) == "UNKNOWN"


# ---------------------------------------------------------------------------
# VMFS -> LUN transport resolution
# ---------------------------------------------------------------------------

def test_vmfs_on_iscsi():
    host = _host(
        scsi_lun=[_scsi_lun("lun-key-1", "naa.111")],
        adapters=[_adapter([_target(vim.host.InternetScsiTargetTransport(), ["lun-key-1"])])],
    )
    ds = _ds("VMFS", host_mounts=[_host_mount(host)], vmfs_extent=[_extent("naa.111")])
    assert _resolve_vmfs_transport(ds, _report()) == "ISCSI"
    assert _classify_datastore_connectivity(ds, _report()) == "ISCSI"


def test_vmfs_on_fc():
    host = _host(
        scsi_lun=[_scsi_lun("lun-key-1", "naa.222")],
        adapters=[_adapter([_target(vim.host.FibreChannelTargetTransport(), ["lun-key-1"])])],
    )
    ds = _ds("VMFS", host_mounts=[_host_mount(host)], vmfs_extent=[_extent("naa.222")])
    assert _resolve_vmfs_transport(ds, _report()) == "FC"


def test_vmfs_on_local():
    host = _host(
        scsi_lun=[_scsi_lun("lun-key-1", "naa.333")],
        adapters=[_adapter([_target(vim.host.BlockAdapterTargetTransport(), ["lun-key-1"])])],
    )
    ds = _ds("VMFS", host_mounts=[_host_mount(host)], vmfs_extent=[_extent("naa.333")])
    assert _resolve_vmfs_transport(ds, _report()) == "LOCAL"


def test_vmfs_on_sas():
    host = _host(
        scsi_lun=[_scsi_lun("lun-key-1", "naa.444")],
        adapters=[_adapter([_target(vim.host.ParallelScsiTargetTransport(), ["lun-key-1"])])],
    )
    ds = _ds("VMFS", host_mounts=[_host_mount(host)], vmfs_extent=[_extent("naa.444")])
    assert _resolve_vmfs_transport(ds, _report()) == "SAS"


def test_vmfs_unresolvable_lun_is_unknown():
    # Host has SCSI topology, but nothing matches this datastore's extent.
    host = _host(
        scsi_lun=[_scsi_lun("lun-key-1", "naa.other")],
        adapters=[_adapter([_target(vim.host.InternetScsiTargetTransport(), ["lun-key-1"])])],
    )
    ds = _ds("VMFS", host_mounts=[_host_mount(host)], vmfs_extent=[_extent("naa.555")])
    assert _resolve_vmfs_transport(ds, _report()) == "UNKNOWN"


def test_vmfs_no_host_mount_is_unknown():
    ds = _ds("VMFS", host_mounts=[], vmfs_extent=[_extent("naa.666")])
    report = _report()
    assert _resolve_vmfs_transport(ds, report) == "UNKNOWN"
    assert "datastore_transport_host (ds1)" in report.missing_field_counts


def test_vmfs_mixed_transport_extents_is_unknown():
    host = _host(
        scsi_lun=[
            _scsi_lun("lun-key-1", "naa.777"),
            _scsi_lun("lun-key-2", "naa.888"),
        ],
        adapters=[_adapter([
            _target(vim.host.InternetScsiTargetTransport(), ["lun-key-1"]),
            _target(vim.host.FibreChannelTargetTransport(), ["lun-key-2"]),
        ])],
    )
    ds = _ds(
        "VMFS", host_mounts=[_host_mount(host)],
        vmfs_extent=[_extent("naa.777"), _extent("naa.888")],
    )
    assert _resolve_vmfs_transport(ds, _report()) == "UNKNOWN"


def test_vmfs_resolution_exception_is_unknown():
    class Explodes:
        @property
        def host(self):
            raise RuntimeError("permission denied")

    ds = Explodes()
    ds.name = "broken-ds"
    assert _resolve_vmfs_transport(ds, _report()) == "UNKNOWN"


# ---------------------------------------------------------------------------
# _map_datastore — capacity/used/free still populate even when
# classification fails, and one bad datastore doesn't raise.
# ---------------------------------------------------------------------------

def test_map_datastore_populates_capacity_even_when_unknown():
    ds = _ds(
        "VMFS", host_mounts=[], vmfs_extent=[_extent("naa.999")],
        capacity=100 * 1024 ** 3, free_space=40 * 1024 ** 3,
        name="ds-cap", moid="datastore-42",
    )
    record = _map_datastore(ds, _report())
    assert record is not None
    assert record["connectivity_type"] == "UNKNOWN"
    assert record["capacity_gb"] == 100.0
    assert record["free_gb"] == 40.0
    assert record["used_gb"] == 60.0
    assert record["is_shared"] is True
    assert record["source_id"] == "datastore-42"


def test_map_datastore_returns_none_on_unexpected_error():
    class BrokenSummary:
        @property
        def capacity(self):
            raise RuntimeError("boom")

    ds = types.SimpleNamespace(summary=BrokenSummary(), info=None, host=[], name="broken", _moId="x")
    assert _map_datastore(ds, _report()) is None


# ---------------------------------------------------------------------------
# _datastore_identity — a shared LUN/volume mounted into multiple Datacenters
# shows up as one vim.Datastore MO per Datacenter (confirmed live: a single
# storage volume appeared as 9 distinct moIds, one per datacenter folder).
# source_id must be storage-identity-based (summary.url), not moId, so those
# duplicates collapse into one DatastoreCurrent row instead of many.
# ---------------------------------------------------------------------------

def test_datastore_identity_uses_url_when_present():
    ds = _ds("VMFS", moid="datastore-15059", url="ds:///vmfs/volumes/66457e85-1fd78348-794c-d0431e541e15/")
    assert _datastore_identity(ds) == "ds:///vmfs/volumes/66457e85-1fd78348-794c-d0431e541e15/"


def test_datastore_identity_falls_back_to_moid_when_url_missing():
    ds = _ds("VMFS", moid="datastore-99", url=None)
    assert _datastore_identity(ds) == "datastore-99"


def test_duplicate_datacenter_scoped_datastores_share_source_id():
    # Same physical LUN, two separate Datacenter-scoped vim.Datastore objects
    # (different moId, same summary.url) — as actually observed live.
    shared_url = "ds:///vmfs/volumes/66457e85-1fd78348-794c-d0431e541e15/"
    ds_a = _ds("VMFS", moid="datastore-15059", url=shared_url, name="DELL-EMC-R5-12.23")
    ds_b = _ds("VMFS", moid="datastore-15060", url=shared_url, name="DELL-EMC-R5-12.23")
    record_a = _map_datastore(ds_a, _report())
    record_b = _map_datastore(ds_b, _report())
    assert record_a["source_id"] == record_b["source_id"] == shared_url


# ---------------------------------------------------------------------------
# _merge_duplicate_datastore_records — per-Datacenter duplicates must be
# reconciled, not "last one wins": a datastore mounted by hosts split
# across Datacenters can have multipleHostAccess=False on one duplicate
# object while genuinely being shared overall (confirmed live: iSCSI/FC
# datastores mounted on shared hypervisors were showing as host-local).
# ---------------------------------------------------------------------------

def _rec(source_id="url-1", name="ds", connectivity_type="ISCSI", is_shared=True, host_ids=None):
    return {
        "source_id": source_id, "name": name,
        "capacity_gb": 100.0, "used_gb": 40.0, "free_gb": 60.0,
        "type": "VMFS", "connectivity_type": connectivity_type, "is_shared": is_shared,
        "_host_ids": host_ids or [],
    }


def test_merge_is_shared_true_if_any_duplicate_says_true():
    records = [
        _rec(is_shared=False),   # this Datacenter only has one host mounting it
        _rec(is_shared=True),    # another Datacenter has several
    ]
    merged = _merge_duplicate_datastore_records(records)
    assert len(merged) == 1
    assert merged[0]["is_shared"] is True


def test_merge_is_shared_false_only_if_all_duplicates_say_false():
    records = [_rec(is_shared=False), _rec(is_shared=False)]
    merged = _merge_duplicate_datastore_records(records)
    assert merged[0]["is_shared"] is False


def test_merge_agreeing_connectivity_type_kept():
    records = [_rec(connectivity_type="ISCSI"), _rec(connectivity_type="ISCSI")]
    merged = _merge_duplicate_datastore_records(records)
    assert merged[0]["connectivity_type"] == "ISCSI"


def test_merge_prefers_resolved_type_over_unknown_duplicate():
    # One Datacenter's host-topology lookup failed for this object (UNKNOWN),
    # another Datacenter's resolved cleanly — don't let the failure win.
    records = [_rec(connectivity_type="UNKNOWN"), _rec(connectivity_type="ISCSI")]
    merged = _merge_duplicate_datastore_records(records)
    assert merged[0]["connectivity_type"] == "ISCSI"


def test_merge_conflicting_resolved_types_becomes_unknown():
    # Genuine multipath ambiguity: one Datacenter's vantage point sees this
    # LUN over iSCSI, another sees it over FC — same reasoning as
    # mixed-transport extents within a single object.
    records = [_rec(connectivity_type="ISCSI"), _rec(connectivity_type="FC")]
    merged = _merge_duplicate_datastore_records(records)
    assert merged[0]["connectivity_type"] == "UNKNOWN"


def test_merge_leaves_distinct_source_ids_untouched():
    records = [_rec(source_id="url-1", name="a"), _rec(source_id="url-2", name="b")]
    merged = _merge_duplicate_datastore_records(records)
    assert {r["source_id"] for r in merged} == {"url-1", "url-2"}
    assert len(merged) == 2


def test_merge_strips_internal_host_ids_key():
    merged = _merge_duplicate_datastore_records([_rec(host_ids=["h1"])])
    assert "_host_ids" not in merged[0]


def test_merge_detects_sharing_split_across_datacenters():
    # The exact live shape of DMN-Datastore-IBM: 5 Datacenter-scoped objects,
    # each with exactly ONE distinct mounting host (so each object's own
    # multipleHostAccess is False), but 5 distinct hosts overall — genuinely
    # shared, and the union check is the only thing that can see that since
    # no single object's own flag ever says True.
    records = [
        _rec(is_shared=False, host_ids=["host-a"]),
        _rec(is_shared=False, host_ids=["host-b"]),
        _rec(is_shared=False, host_ids=["host-c"]),
        _rec(is_shared=False, host_ids=["host-d"]),
        _rec(is_shared=False, host_ids=["host-e"]),
    ]
    merged = _merge_duplicate_datastore_records(records)
    assert merged[0]["is_shared"] is True


def test_merge_single_host_across_all_duplicates_stays_local():
    # Same host id repeated (e.g. redundant duplicate records seen for the
    # same object) — still only one real mounting host, must stay local.
    records = [_rec(is_shared=False, host_ids=["host-a"]), _rec(is_shared=False, host_ids=["host-a"])]
    merged = _merge_duplicate_datastore_records(records)
    assert merged[0]["is_shared"] is False


# ---------------------------------------------------------------------------
# _mounting_host_ids / _map_datastore host-id capture
# ---------------------------------------------------------------------------

def test_mounting_host_ids_dedupes_and_reads_moid():
    host_a = _host(moid="host-aaa")
    host_b = _host(moid="host-bbb")
    ds = _ds("VMFS", host_mounts=[_host_mount(host_a), _host_mount(host_b), _host_mount(host_a)])
    assert _mounting_host_ids(ds) == ["host-aaa", "host-bbb"]


def test_map_datastore_carries_host_ids_for_merge():
    host_a = _host(moid="host-aaa")
    ds = _ds("NFS", host_mounts=[_host_mount(host_a)], capacity=10 * 1024 ** 3, free_space=5 * 1024 ** 3)
    record = _map_datastore(ds, _report())
    assert record["_host_ids"] == ["host-aaa"]
