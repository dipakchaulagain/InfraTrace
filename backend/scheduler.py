#!/usr/bin/env python3
"""
scheduler.py — In-process sync scheduler.

Reads sync intervals from app_settings (set via UI Settings → Sync Engine).
Falls back to --interval-hours CLI arg (default 4) if no DB setting exists.

Each platform runs on its own independently configurable interval.
One platform failing never blocks the other.

Usage:
    python3 scheduler.py                    # default 4h for both
    python3 scheduler.py --run-once         # run immediately and exit
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import structlog
from dotenv import load_dotenv

load_dotenv()

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ],
)
log = structlog.get_logger()


def _get_intervals(default_minutes: int) -> tuple[int, int]:
    """Read per-platform intervals (minutes) from DB."""
    from app.database import SessionLocal
    from app.sync.connector_settings import get_sync_engine_settings
    db = SessionLocal()
    try:
        cfg = get_sync_engine_settings(db)
        return cfg.vmware_interval_minutes, cfg.nutanix_interval_minutes
    except Exception:
        return default_minutes, default_minutes
    finally:
        db.close()


def _sync_platform(platform: str) -> None:
    """Run one sync pass for the given platform using its own DB session."""
    from app.database import SessionLocal
    from app.models.inventory import SourceSystem

    db = SessionLocal()
    try:
        source = (
            db.query(SourceSystem)
            .filter(SourceSystem.platform == platform, SourceSystem.is_active.is_(True))
            .first()
        )
        if not source:
            log.warning("scheduler_no_active_source", platform=platform)
            return

        log.info("scheduler_sync_start", platform=platform, source=source.display_name)

        if platform == "vmware":
            from app.sync.vmware_adapter import run_vmware_sync
            result = run_vmware_sync(db, source.id)
        else:
            from app.sync.nutanix_adapter import run_nutanix_sync
            result = run_nutanix_sync(db, source.id)

        log.info("scheduler_sync_done",
                 platform=platform,
                 status=result.get("status"),
                 run_id=result.get("run_id", "—"))
    except Exception as exc:
        log.error("scheduler_sync_error", platform=platform, error=str(exc))
    finally:
        db.close()


def _get_backup_settings() -> tuple[bool, int]:
    """Read (enabled, interval_minutes) for scheduled backups from DB."""
    from app.database import SessionLocal
    from app.models.inventory import AppSetting
    db = SessionLocal()
    try:
        enabled_row = db.get(AppSetting, "backup.enabled")
        interval_row = db.get(AppSetting, "backup.interval_minutes")
        enabled = bool(enabled_row and enabled_row.value == "true")
        interval = int(interval_row.value) if interval_row and interval_row.value else 1440
        return enabled, interval
    except Exception:
        return False, 1440
    finally:
        db.close()


def _run_scheduled_backup() -> None:
    """Run one scheduled backup + retention cleanup, logging the result to
    the audit trail (same AccessLog table Admin's Audit Log page reads) so
    scheduled-backup failures are never silent."""
    from app.database import SessionLocal
    from app.models.inventory import AppSetting
    from app.audit import log_event
    from app import backup as backup_lib

    db = SessionLocal()
    try:
        result = backup_lib.create_backup(reason="scheduled")
        if result.status == "ok":
            retention_row = db.get(AppSetting, "backup.retention_count")
            retention = int(retention_row.value) if retention_row and retention_row.value else 10
            deleted = backup_lib.apply_retention(retention)
            log_event(db, actor=None, action="backup_created", result="success",
                       details={"filename": result.filename, "size_bytes": result.size_bytes,
                                "reason": "scheduled", "retention_deleted": deleted})
            log.info("scheduler_backup_done", filename=result.filename, size_bytes=result.size_bytes)
        else:
            log_event(db, actor=None, action="backup_created", result="failure",
                       details={"reason": "scheduled", "error": result.message})
            log.error("scheduler_backup_error", error=result.message)
        db.commit()
    except Exception as exc:
        log.error("scheduler_backup_error", error=str(exc))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="InfraTrace sync scheduler")
    parser.add_argument(
        "--interval-hours", type=float, default=4.0,
        help="Default sync interval in hours (overridden per-platform by DB settings)",
    )
    parser.add_argument(
        "--run-once", action="store_true",
        help="Run both syncs once immediately then exit (useful for cron-invoked runs)",
    )
    args = parser.parse_args()

    log.info("scheduler_start",
             default_interval_minutes=int(args.interval_hours * 60),
             run_once=args.run_once)

    last_run: dict[str, float] = {"vmware": 0.0, "nutanix": 0.0, "backup": 0.0}

    if args.run_once:
        _sync_platform("vmware")
        _sync_platform("nutanix")
        log.info("run_once_complete")
        sys.exit(0)

    while True:
        now = time.time()
        vmware_minutes, nutanix_minutes = _get_intervals(int(args.interval_hours * 60))
        intervals_secs = {
            "vmware":  vmware_minutes  * 60,
            "nutanix": nutanix_minutes * 60,
        }

        for platform, interval_secs in intervals_secs.items():
            due_in = (last_run[platform] + interval_secs) - now
            if due_in <= 0:
                log.info("scheduler_platform_due", platform=platform,
                         interval_minutes=interval_secs // 60)
                _sync_platform(platform)
                last_run[platform] = time.time()

        backup_enabled, backup_interval_minutes = _get_backup_settings()
        if backup_enabled:
            due_in = (last_run["backup"] + backup_interval_minutes * 60) - now
            if due_in <= 0:
                log.info("scheduler_backup_due", interval_minutes=backup_interval_minutes)
                _run_scheduled_backup()
                last_run["backup"] = time.time()

        # Poll every 30 seconds so interval changes from the UI take
        # effect quickly without restarting the container
        time.sleep(30)


if __name__ == "__main__":
    main()
