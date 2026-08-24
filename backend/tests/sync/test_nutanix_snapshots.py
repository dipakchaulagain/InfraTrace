"""
Unit tests for Nutanix snapshot grouping (app/sync/nutanix_adapter.py).
The real v2 /snapshots entity shape (confirmed live) has no size field at
all — size_gb is always None for Nutanix snapshots, unlike VMware.
"""
from app.sync.nutanix_adapter import _fetch_snapshots_map


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, params=None, timeout=None):
        return _FakeResponse(self._payload)


def test_groups_snapshots_by_vm_uuid():
    payload = {"entities": [
        {"uuid": "snap-1", "vm_uuid": "vm-a", "snapshot_name": "before-upgrade",
         "created_time": 1717000000000000, "deleted": False},
        {"uuid": "snap-2", "vm_uuid": "vm-a", "snapshot_name": "after-upgrade",
         "created_time": 1718000000000000, "deleted": False},
        {"uuid": "snap-3", "vm_uuid": "vm-b", "snapshot_name": "backup",
         "created_time": 1719000000000000, "deleted": False},
    ]}
    result = _fetch_snapshots_map(_FakeSession(payload), "https://prism.example.local:9440/PrismGateway/services/rest/v2.0")
    assert len(result["vm-a"]) == 2
    assert len(result["vm-b"]) == 1
    assert result["vm-a"][0]["name"] == "before-upgrade"
    assert result["vm-a"][0]["size_gb"] is None


def test_deleted_snapshots_excluded():
    payload = {"entities": [
        {"uuid": "snap-1", "vm_uuid": "vm-a", "snapshot_name": "gone",
         "created_time": 1717000000000000, "deleted": True},
    ]}
    result = _fetch_snapshots_map(_FakeSession(payload), "https://prism.example.local:9440/PrismGateway/services/rest/v2.0")
    assert result == {}


def test_missing_vm_uuid_skipped():
    payload = {"entities": [
        {"uuid": "snap-1", "snapshot_name": "orphan", "created_time": 1717000000000000, "deleted": False},
    ]}
    result = _fetch_snapshots_map(_FakeSession(payload), "https://prism.example.local:9440/PrismGateway/services/rest/v2.0")
    assert result == {}


def test_unnamed_snapshot_gets_placeholder_name():
    payload = {"entities": [
        {"uuid": "snap-1", "vm_uuid": "vm-a", "created_time": 1717000000000000, "deleted": False},
    ]}
    result = _fetch_snapshots_map(_FakeSession(payload), "https://prism.example.local:9440/PrismGateway/services/rest/v2.0")
    assert result["vm-a"][0]["name"] == "(unnamed)"


def test_created_time_converted_from_microseconds():
    payload = {"entities": [
        {"uuid": "snap-1", "vm_uuid": "vm-a", "snapshot_name": "x",
         "created_time": 1717000000000000, "deleted": False},
    ]}
    result = _fetch_snapshots_map(_FakeSession(payload), "https://prism.example.local:9440/PrismGateway/services/rest/v2.0")
    assert result["vm-a"][0]["created_at"].startswith("2024-05-29")
