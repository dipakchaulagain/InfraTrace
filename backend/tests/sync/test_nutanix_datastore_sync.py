"""
Unit tests for Nutanix storage-container mapping (app/sync/nutanix_adapter.py).
Prism Element containers are always distributed/shared — no branching, no DB.
"""
from app.sync.nutanix_adapter import _map_container


def test_container_always_maps_to_nutanix_container_and_shared():
    container = {
        "storage_container_uuid": "uuid-1",
        "name": "default-container",
        "max_capacity": 500 * 1024 ** 3,
        "usage_stats": {
            "storage.usage_bytes": 100 * 1024 ** 3,
            "storage.free_bytes": 400 * 1024 ** 3,
        },
    }
    record = _map_container(container)
    assert record["connectivity_type"] == "NUTANIX_CONTAINER"
    assert record["is_shared"] is True
    assert record["type"] == "NutanixContainer"
    assert record["source_id"] == "uuid-1"
    assert record["capacity_gb"] == 500.0
    assert record["used_gb"] == 100.0
    assert record["free_gb"] == 400.0


def test_container_missing_usage_stats_still_shared():
    container = {"storage_container_uuid": "uuid-2", "name": "no-stats"}
    record = _map_container(container)
    assert record["connectivity_type"] == "NUTANIX_CONTAINER"
    assert record["is_shared"] is True
    assert record["capacity_gb"] is None
    assert record["used_gb"] is None
    assert record["free_gb"] is None


def test_container_falls_back_to_id_field():
    container = {"id": "uuid-3", "name": "legacy-id-shape"}
    record = _map_container(container)
    assert record["source_id"] == "uuid-3"
    assert record["is_shared"] is True


def test_container_usage_stats_as_strings_does_not_raise():
    # The real Prism Element v2 API returns every usage_stats value as a
    # JSON string (confirmed against a live cluster: {'storage.free_bytes':
    # '20161369956352', ...}) even though max_capacity is a real int. This
    # used to blow up run_nutanix_sync with "unsupported operand type(s) for
    # /: 'str' and 'int'" and abort the whole sync run.
    container = {
        "storage_container_uuid": "uuid-4",
        "name": "string-stats",
        "max_capacity": 36507222016000,
        "usage_stats": {
            "storage.usage_bytes": "16345852059648",
            "storage.free_bytes": "20161369956352",
        },
    }
    record = _map_container(container)
    assert record["capacity_gb"] == round(36507222016000 / (1024 ** 3), 2)
    assert record["used_gb"] == round(16345852059648 / (1024 ** 3), 2)
    assert record["free_gb"] == round(20161369956352 / (1024 ** 3), 2)


def test_container_unparseable_usage_stats_falls_back_to_none():
    container = {
        "storage_container_uuid": "uuid-5",
        "name": "garbage-stats",
        "max_capacity": "not-a-number",
        "usage_stats": {"storage.usage_bytes": None, "storage.free_bytes": "also-not-a-number"},
    }
    record = _map_container(container)
    assert record["capacity_gb"] is None
    assert record["used_gb"] is None
    assert record["free_gb"] is None
