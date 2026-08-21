"""
datastores.py — Datastore/storage-container inventory endpoints.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import DatastoreCurrent
from app.models.metadata import User

router = APIRouter(prefix="/datastores", tags=["datastores"])


def _datastore_to_dict(d: DatastoreCurrent) -> dict:
    return {
        "id": d.id,
        "source_id": d.source_id,
        "name": d.name,
        "capacity_gb": d.capacity_gb,
        "used_gb": d.used_gb,
        "free_gb": d.free_gb,
        "type": d.type,
        "connectivity_type": d.connectivity_type,
        "is_shared": d.is_shared,
        "last_synced_at": d.last_synced_at.isoformat() if d.last_synced_at else None,
    }


@router.get("")
def list_datastores(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
    connectivity_type: Optional[str] = Query(None),
    is_shared: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List all known datastores/storage containers."""
    q = db.query(DatastoreCurrent)

    if connectivity_type:
        q = q.filter(DatastoreCurrent.connectivity_type == connectivity_type)
    if is_shared is not None:
        q = q.filter(DatastoreCurrent.is_shared.is_(is_shared))
    if search:
        q = q.filter(DatastoreCurrent.name.ilike(f"%{search}%"))

    total = q.count()
    datastores = (
        q.order_by(DatastoreCurrent.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_datastore_to_dict(d) for d in datastores],
    }


@router.get("/summary")
def get_datastore_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
):
    """Dashboard summary — count of host-local (non-shared) datastores."""
    local_count = db.query(DatastoreCurrent).filter(DatastoreCurrent.is_shared.is_(False)).count()
    return {"local_count": local_count}


@router.get("/{datastore_id}")
def get_datastore(
    datastore_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor", "global_viewer")),
):
    d = db.query(DatastoreCurrent).filter(DatastoreCurrent.id == datastore_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Datastore not found")
    return _datastore_to_dict(d)
