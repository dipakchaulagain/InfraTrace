"""
Unit tests for VMware snapshot mapping (app/sync/vmware_adapter.py).
Pure functions — no vCenter connection, no DB.

Size computation is verified against the real shape confirmed live against
a 4-generation branching snapshot tree: layoutEx.snapshot[].disk[].chain is
ordered [base_disk, delta1, delta2, ...], where chain[0] is always the
VM's original disk (identical across every snapshot's chain) and everything
after it is a redo-log layer specific to that branch.
"""
import types

import pytest

from app.sync.base import ValidationReport
from app.sync.vmware_adapter import (
    _snapshot_size_index,
    _flatten_snapshot_tree,
    _build_snapshots,
)


def _file(key, size):
    return types.SimpleNamespace(key=key, size=size)


def _chain_layer(*file_keys):
    return types.SimpleNamespace(fileKey=list(file_keys))


def _disk(*chain_layers):
    return types.SimpleNamespace(chain=list(chain_layers))


def _snapshot_layout(key, disks, memory_key=-1):
    return types.SimpleNamespace(key=key, disk=list(disks), memoryKey=memory_key)


def _layout_ex(files, snapshots):
    return types.SimpleNamespace(file=list(files), snapshot=list(snapshots))


def _tree_node(name, snapshot_key, description=None, created_time=None, children=None):
    return types.SimpleNamespace(
        name=name, description=description, createTime=created_time,
        id=1, snapshot=snapshot_key, childSnapshotList=children or [],
    )


def _report():
    return ValidationReport()


# ---------------------------------------------------------------------------
# _snapshot_size_index
# ---------------------------------------------------------------------------

def test_size_excludes_shared_base_disk():
    # chain[0] is the 50GB base, shared by every snapshot — must not be
    # counted as this snapshot's own size.
    files = [_file("base", 50 * 1024 ** 3), _file("delta1", 2 * 1024 ** 3)]
    layout = _layout_ex(files, [
        _snapshot_layout("snap-1", [_disk(_chain_layer("base"), _chain_layer("delta1"))]),
    ])
    vm = types.SimpleNamespace(layoutEx=layout, name="vm1")
    index = _snapshot_size_index(vm)
    assert index["snap-1"] == 2.0


def test_size_first_snapshot_with_no_delta_yet_is_zero():
    # Only the base layer exists in the chain (nothing written since) —
    # this snapshot's own footprint is 0, not the base disk's full size.
    files = [_file("base", 50 * 1024 ** 3)]
    layout = _layout_ex(files, [_snapshot_layout("snap-1", [_disk(_chain_layer("base"))])])
    vm = types.SimpleNamespace(layoutEx=layout, name="vm1")
    index = _snapshot_size_index(vm)
    assert index["snap-1"] == 0.0


def test_size_includes_memory_file_when_present():
    files = [_file("base", 50 * 1024 ** 3), _file("delta1", 1 * 1024 ** 3), _file("mem", 4 * 1024 ** 3)]
    layout = _layout_ex(files, [
        _snapshot_layout("snap-1", [_disk(_chain_layer("base"), _chain_layer("delta1"))], memory_key="mem"),
    ])
    vm = types.SimpleNamespace(layoutEx=layout, name="vm1")
    index = _snapshot_size_index(vm)
    assert index["snap-1"] == 5.0


def test_size_missing_layout_entry_not_in_index():
    # Some snapshots (confirmed live) have no layoutEx.snapshot entry at
    # all — .get() on the result must return None, not raise or guess.
    layout = _layout_ex([], [])
    vm = types.SimpleNamespace(layoutEx=layout, name="vm1")
    index = _snapshot_size_index(vm)
    assert index.get("snap-1") is None


def test_size_no_layout_ex_at_all_returns_empty_index():
    vm = types.SimpleNamespace(layoutEx=None, name="vm1")
    assert _snapshot_size_index(vm) == {}


def test_size_branching_tree_matches_live_shape():
    # Real shape confirmed live: two sibling snapshots branching off the
    # same parent, then a grandchild — each branch's size is independent
    # cumulative delta from base, not affected by the sibling branch.
    files = [
        _file("base", 50 * 1024 ** 3),
        _file("branchA", int(1.03 * 1024 ** 3)),
        _file("branchB", int(0.459 * 1024 ** 3)),
    ]
    layout = _layout_ex(files, [
        _snapshot_layout("root", [_disk(_chain_layer("base"))]),
        _snapshot_layout("child-A", [_disk(_chain_layer("base"), _chain_layer("branchA"))]),
        _snapshot_layout("child-B", [_disk(_chain_layer("base"), _chain_layer("branchA"), _chain_layer("branchB"))]),
    ])
    vm = types.SimpleNamespace(layoutEx=layout, name="vm1")
    index = _snapshot_size_index(vm)
    assert index["root"] == 0.0
    assert index["child-A"] == pytest.approx(1.03, abs=0.01)
    assert index["child-B"] == pytest.approx(1.03 + 0.459, abs=0.01)


def test_size_resolution_exception_is_resilient():
    class ExplodingLayout:
        @property
        def snapshot(self):
            raise RuntimeError("permission denied")

    vm = types.SimpleNamespace(layoutEx=ExplodingLayout(), name="vm1")
    assert _snapshot_size_index(vm) == {}


# ---------------------------------------------------------------------------
# _flatten_snapshot_tree
# ---------------------------------------------------------------------------

def test_flatten_single_node():
    import datetime
    created = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    node = _tree_node("snap1", "moref-1", description="desc1", created_time=created)
    flat = _flatten_snapshot_tree([node], {"moref-1": 1.5})
    assert flat == [{
        "id": "moref-1", "name": "snap1", "description": "desc1",
        "created_at": created.isoformat(), "size_gb": 1.5,
    }]


def test_flatten_nested_tree_preserves_all_generations():
    grandchild = _tree_node("gc", "m3")
    child = _tree_node("c", "m2", children=[grandchild])
    root = _tree_node("r", "m1", children=[child])
    flat = _flatten_snapshot_tree([root], {})
    assert [f["id"] for f in flat] == ["m1", "m2", "m3"]


def test_flatten_missing_size_is_none():
    node = _tree_node("snap1", "moref-unresolved")
    flat = _flatten_snapshot_tree([node], {})
    assert flat[0]["size_gb"] is None


def test_flatten_empty_description_becomes_none():
    node = _tree_node("snap1", "moref-1", description="")
    flat = _flatten_snapshot_tree([node], {})
    assert flat[0]["description"] is None


# ---------------------------------------------------------------------------
# _build_snapshots
# ---------------------------------------------------------------------------

def test_build_snapshots_no_snapshot_object_returns_empty():
    vm = types.SimpleNamespace(snapshot=None, name="vm1")
    assert _build_snapshots(vm, _report()) == []


def test_build_snapshots_empty_root_list_returns_empty():
    vm = types.SimpleNamespace(snapshot=types.SimpleNamespace(rootSnapshotList=[]), name="vm1")
    assert _build_snapshots(vm, _report()) == []


def test_build_snapshots_end_to_end():
    node = _tree_node("snap1", "m1")
    files = [_file("base", 10 * 1024 ** 3)]
    layout = _layout_ex(files, [_snapshot_layout("m1", [_disk(_chain_layer("base"))])])
    vm = types.SimpleNamespace(
        snapshot=types.SimpleNamespace(rootSnapshotList=[node]),
        layoutEx=layout, name="vm1",
    )
    result = _build_snapshots(vm, _report())
    assert len(result) == 1
    assert result[0]["name"] == "snap1"
    assert result[0]["size_gb"] == 0.0


def test_build_snapshots_never_raises_on_bad_data():
    class BadSnapshot:
        @property
        def rootSnapshotList(self):
            raise RuntimeError("boom")

    vm = types.SimpleNamespace(snapshot=BadSnapshot(), name="vm1", layoutEx=None)
    report = _report()
    assert _build_snapshots(vm, report) == []
