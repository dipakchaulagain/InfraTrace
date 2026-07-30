"""
sync_runs.py — Sync health dashboard endpoints: run history, dead-letter queue,
and manual trigger for immediate sync.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import SyncRun, DeadLetterRecord, SourceSystem
from app.models.metadata import User

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/runs")
def list_sync_runs(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor")),
    limit: int = 20,
):
    runs = (
        db.query(SyncRun)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "source_platform": r.source_platform,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "records_seen": r.records_seen,
            "records_ok": r.records_ok,
            "records_failed": r.records_failed,
            "records_dead_lettered": r.records_dead_lettered,
            "error_message": r.error_message,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}")
def get_sync_run(
    run_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin", "global_editor")),
):
    run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")
    return {
        "id": run.id,
        "source_platform": run.source_platform,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "records_seen": run.records_seen,
        "records_ok": run.records_ok,
        "records_failed": run.records_failed,
        "records_dead_lettered": run.records_dead_lettered,
        "validation_report": run.validation_report,
        "error_message": run.error_message,
    }


@router.get("/dead-letters")
def list_dead_letters(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
    resolved: bool = False,
    limit: int = 50,
):
    records = (
        db.query(DeadLetterRecord)
        .filter(DeadLetterRecord.resolved.is_(resolved))
        .order_by(DeadLetterRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "sync_run_id": r.sync_run_id,
            "source_platform": r.source_platform,
            "error_message": r.error_message,
            "resolved": r.resolved,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@router.post("/dead-letters/{record_id}/resolve")
def resolve_dead_letter(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from datetime import datetime, timezone
    record = db.query(DeadLetterRecord).filter(DeadLetterRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Dead-letter record not found")
    record.resolved = True
    record.resolved_at = datetime.now(timezone.utc)
    record.resolved_by = current_user.id
    db.commit()
    return {"status": "ok"}


def _run_vmware_sync_bg(source_system_id: str):
    """Background task: runs VMware sync with its own DB session."""
    from app.database import SessionLocal
    from app.sync.vmware_adapter import run_vmware_sync
    db = SessionLocal()
    try:
        run_vmware_sync(db, source_system_id)
    finally:
        db.close()


def _run_nutanix_sync_bg(source_system_id: str):
    from app.database import SessionLocal
    from app.sync.nutanix_adapter import run_nutanix_sync
    db = SessionLocal()
    try:
        run_nutanix_sync(db, source_system_id)
    finally:
        db.close()


@router.post("/trigger/{platform}")
def trigger_sync(
    platform: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """Manually trigger an immediate sync for a platform. Runs in background."""
    if platform not in ("vmware", "nutanix"):
        raise HTTPException(status_code=400, detail="platform must be 'vmware' or 'nutanix'")

    source = db.query(SourceSystem).filter(
        SourceSystem.platform == platform,
        SourceSystem.is_active.is_(True),
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"No active source system configured for {platform}")

    if platform == "vmware":
        background_tasks.add_task(_run_vmware_sync_bg, source.id)
    else:
        background_tasks.add_task(_run_nutanix_sync_bg, source.id)

    return {"status": "triggered", "platform": platform, "source_system_id": source.id}
