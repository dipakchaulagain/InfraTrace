"""
Unit tests for Nutanix host CPU/memory usage extraction
(app/sync/nutanix_adapter.py._host_usage_from_ppm / _fetch_hosts_map).

The real Prism Element v2 /hosts API returns usage as parts-per-million
strings under `stats` (confirmed live: '827533' ppm == 82.75% CPU), not
absolute values — this was previously unhandled and cpu_usage_mhz/
memory_usage_mb were hardcoded to None for every Nutanix host.
"""
from app.sync.nutanix_adapter import _host_usage_from_ppm, _fetch_hosts_map


def test_ppm_converts_to_absolute_usage():
    # 10 GHz capacity, 50% (500000 ppm) usage -> 5000 MHz.
    host = {"stats": {"hypervisor_cpu_usage_ppm": "500000", "hypervisor_memory_usage_ppm": "250000"}}
    cpu_mhz, mem_mb = _host_usage_from_ppm(host, cpu_hz=10_000_000_000, memory_bytes=100 * 1024 ** 3)
    assert cpu_mhz == 5000
    assert mem_mb == round(100 * 1024 * 0.25)


def test_ppm_missing_stats_returns_none():
    cpu_mhz, mem_mb = _host_usage_from_ppm({}, cpu_hz=10_000_000_000, memory_bytes=100 * 1024 ** 3)
    assert cpu_mhz is None
    assert mem_mb is None


def test_ppm_unparseable_string_returns_none():
    host = {"stats": {"hypervisor_cpu_usage_ppm": "not-a-number", "hypervisor_memory_usage_ppm": None}}
    cpu_mhz, mem_mb = _host_usage_from_ppm(host, cpu_hz=10_000_000_000, memory_bytes=100 * 1024 ** 3)
    assert cpu_mhz is None
    assert mem_mb is None


def test_ppm_zero_capacity_returns_none_not_zero_division():
    host = {"stats": {"hypervisor_cpu_usage_ppm": "500000", "hypervisor_memory_usage_ppm": "500000"}}
    cpu_mhz, mem_mb = _host_usage_from_ppm(host, cpu_hz=None, memory_bytes=None)
    assert cpu_mhz is None
    assert mem_mb is None


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


def test_fetch_hosts_map_populates_usage_from_real_shaped_payload():
    # Shape confirmed against a live Prism Element cluster.
    payload = {
        "entities": [
            {
                "uuid": "host-uuid-1",
                "name": "NX01-NDC-RA5-U17",
                "hypervisor_type": "kKvm",
                "hypervisor_full_name": "Nutanix 20220304.480",
                "state": "NORMAL",
                "num_cpu_sockets": 2,
                "num_cpu_cores": 36,
                "num_cpu_threads": 72,
                "cpu_capacity_in_hz": 100_000_000_000,
                "memory_capacity_in_bytes": 400 * 1024 ** 3,
                "stats": {
                    "hypervisor_cpu_usage_ppm": "827533",
                    "hypervisor_memory_usage_ppm": "795782",
                },
            },
        ],
    }
    session = _FakeSession(payload)
    result = _fetch_hosts_map(session, "https://prism.example.local:9440/PrismGateway/services/rest/v2.0")
    host = result["host-uuid-1"]
    assert host["cpu_usage_mhz"] is not None
    assert host["memory_usage_mb"] is not None
    assert host["cpu_capacity_ghz"] == 100.0
    assert host["memory_capacity_gb"] == 400.0
