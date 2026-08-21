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
    _map_datastore,
)


def _ds(summary_type, multiple_host_access=True, host_mounts=None, vmfs_extent=None,
        capacity=None, free_space=None, name="ds1", moid="datastore-1"):
    summary = types.SimpleNamespace(
        type=summary_type,
        multipleHostAccess=multiple_host_access,
        name=name,
        capacity=capacity,
        freeSpace=free_space,
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


def _host(scsi_lun=None, adapters=None):
    storage_device = types.SimpleNamespace(
        scsiLun=scsi_lun or [],
        scsiTopology=types.SimpleNamespace(adapter=adapters or []),
    )
    config = types.SimpleNamespace(storageDevice=storage_device)
    return types.SimpleNamespace(config=config)


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
