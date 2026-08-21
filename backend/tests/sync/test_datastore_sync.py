"""
Unit tests for the shared upsert_datastores helper (app/sync/datastore_sync.py)
against a real (in-memory SQLite) session — this exercises the actual
query/insert/delete logic, not just the in-memory dict shape.
"""
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
import pytest

from app.database import Base
from app.models.inventory import SourceSystem, DatastoreCurrent
from app.sync.datastore_sync import upsert_datastores


@pytest.fixture
def session():
    engine = sa.create_engine("sqlite:///:memory:")
    SourceSystem.__table__.create(engine)
    DatastoreCurrent.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False)   # matches app/database.py's SessionLocal
    s = Session()
    s.add(SourceSystem(id="src-1", platform="vmware", display_name="test", base_url="https://x"))
    s.commit()
    yield s
    s.close()


def _rec(source_id, name="ds", connectivity_type="ISCSI", is_shared=True):
    return {
        "source_id": source_id, "name": name,
        "capacity_gb": 100.0, "used_gb": 40.0, "free_gb": 60.0,
        "type": "VMFS", "connectivity_type": connectivity_type, "is_shared": is_shared,
    }


def test_creates_new_rows(session):
    upsert_datastores(session, "src-1", [_rec("url-1", name="ds1")])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1
    assert rows[0].name == "ds1"
    assert rows[0].source_id == "url-1"


def test_updates_existing_row_on_resync(session):
    upsert_datastores(session, "src-1", [_rec("url-1", connectivity_type="UNKNOWN")])
    session.commit()
    upsert_datastores(session, "src-1", [_rec("url-1", connectivity_type="ISCSI")])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1
    assert rows[0].connectivity_type == "ISCSI"


def test_duplicate_source_id_within_one_call_collapses_to_one_row(session):
    # Same physical datastore seen twice in one sync pass (e.g. mounted into
    # two Datacenters, each producing a separate vim.Datastore object with
    # its own moId but the same storage-identity source_id) — must not
    # duplicate. SessionLocal uses autoflush=False, so this only works
    # because upsert_datastores flushes after each insert.
    upsert_datastores(session, "src-1", [
        _rec("shared-url", name="DELL-EMC-R5-12.23", connectivity_type="ISCSI"),
        _rec("shared-url", name="DELL-EMC-R5-12.23", connectivity_type="UNKNOWN"),
    ])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1


def test_prunes_rows_not_seen_in_latest_run(session):
    upsert_datastores(session, "src-1", [_rec("url-old", name="gone")])
    session.commit()
    upsert_datastores(session, "src-1", [_rec("url-new", name="current")])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1
    assert rows[0].source_id == "url-new"


def test_empty_call_does_not_wipe_existing_rows(session):
    upsert_datastores(session, "src-1", [_rec("url-1")])
    session.commit()
    upsert_datastores(session, "src-1", [])
    session.commit()
    rows = session.query(DatastoreCurrent).all()
    assert len(rows) == 1


def test_prune_is_scoped_to_source_system(session):
    session.add(SourceSystem(id="src-2", platform="vmware", display_name="other", base_url="https://y"))
    session.commit()
    upsert_datastores(session, "src-1", [_rec("url-1")])
    upsert_datastores(session, "src-2", [_rec("url-2")])
    session.commit()
    # Re-sync src-1 without url-1 present — must not touch src-2's row.
    upsert_datastores(session, "src-1", [_rec("url-1-renamed")])
    session.commit()
    rows = {r.source_system_id: r.source_id for r in session.query(DatastoreCurrent).all()}
    assert rows == {"src-1": "url-1-renamed", "src-2": "url-2"}
