#!/usr/bin/env python3
"""
scheduler.py — In-process sync scheduler.

Reads sync intervals from app_settings (set via UI Settings → Sync Engine).
Falls back to --interval-hours CLI arg (default 4) if no DB setting exists.

Each platform runs on its own independently configurable interval.
One platform failing never blocks the other.

Datastore capacity/used metrics run on a separate, typically shorter
interval from the full VM inventory pull (one shared interval across
both platforms) — see run_*_datastore_metrics_sync in the adapters.

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


def _get_intervals(default_minutes: int) -> tuple[int, int, int, int]:
    """Read per-platform VM-inventory intervals (minutes) plus the
    datastore-metrics and host-metrics intervals (seconds — as low as 10s,
    see app/api/settings.py's min_metrics_interval validator) from DB. Each
    metrics interval is deliberately a single shared value across
    platforms, not per-platform — they're lightweight numbers-only
    refreshes (see run_*_datastore_metrics_sync / run_*_host_metrics_sync),
    not the full inventory pull the per-platform intervals control."""
    from app.database import SessionLocal
    from app.sync.connector_settings import get_sync_engine_settings
    db = SessionLocal()
    try:
        cfg = get_sync_engine_settings(db)
        return (
            cfg.vmware_interval_minutes, cfg.nutanix_interval_minutes,
            cfg.datastore_metrics_interval_seconds, cfg.host_metrics_interval_seconds,
        )
    except Exception:
        return default_minutes, default_minutes, 900, 900
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


def _sync_datastore_metrics(platform: str) -> None:
    """Run one lightweight datastore-metrics refresh for the given
    platform's active source, using its own DB session. Independent of
    _sync_platform's full inventory sync — see run_vmware_datastore_metrics_sync
    / run_nutanix_datastore_metrics_sync for why this is safe to run on a
    much shorter interval."""
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
            return

        if platform == "vmware":
            from app.sync.vmware_adapter import run_vmware_datastore_metrics_sync
            result = run_vmware_datastore_metrics_sync(db, source.id)
        else:
            from app.sync.nutanix_adapter import run_nutanix_datastore_metrics_sync
            result = run_nutanix_datastore_metrics_sync(db, source.id)

        log.info("scheduler_datastore_metrics_done",
                 platform=platform, status=result.get("status"), count=result.get("count", 0))
    except Exception as exc:
        log.error("scheduler_datastore_metrics_error", platform=platform, error=str(exc))
    finally:
        db.close()


_DATASTORE_METRICS_ROLLUP_INTERVAL_SECS = 3600   # fixed cadence — only the retention window is user-configurable
_HOST_METRICS_ROLLUP_INTERVAL_SECS = 3600


def _run_datastore_metrics_rollup() -> None:
    """Fold DatastoreMetricsHistory (raw) rows older than 1 hour into hourly
    DatastoreMetricsHistoryRollup buckets, and prune rollup rows past the
    configured retention (Settings -> Sync Engine -> Datastore metrics
    retention). Independent of both sync cadences above — see
    datastore_sync.rollup_and_prune_datastore_metrics."""
    from app.database import SessionLocal
    from app.sync.connector_settings import get_sync_engine_settings
    from app.sync.datastore_sync import rollup_and_prune_datastore_metrics

    db = SessionLocal()
    try:
        retention_days = get_sync_engine_settings(db).datastore_metrics_retention_days
        result = rollup_and_prune_datastore_metrics(db, retention_days)
        db.commit()
        log.info("scheduler_datastore_metrics_rollup_done", **result)
    except Exception as exc:
        log.error("scheduler_datastore_metrics_rollup_error", error=str(exc))
        db.rollback()
    finally:
        db.close()


def _sync_host_metrics(platform: str) -> None:
    """Run one lightweight host CPU/memory metrics refresh for the given
    platform's active source. Independent of _sync_platform's full
    inventory sync — see run_vmware_host_metrics_sync /
    run_nutanix_host_metrics_sync."""
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
            return

        if platform == "vmware":
            from app.sync.vmware_adapter import run_vmware_host_metrics_sync
            result = run_vmware_host_metrics_sync(db, source.id)
        else:
            from app.sync.nutanix_adapter import run_nutanix_host_metrics_sync
            result = run_nutanix_host_metrics_sync(db, source.id)

        log.info("scheduler_host_metrics_done",
                 platform=platform, status=result.get("status"), count=result.get("count", 0))
    except Exception as exc:
        log.error("scheduler_host_metrics_error", platform=platform, error=str(exc))
    finally:
        db.close()


def _run_host_metrics_rollup() -> None:
    """Fold HostMetricsHistory (raw) rows older than 1 hour into hourly
    HostMetricsHistoryRollup buckets, and prune rollup rows past the
    configured retention (Settings -> Sync Engine -> Host metrics
    retention). See host_metrics_sync.rollup_and_prune_host_metrics."""
    from app.database import SessionLocal
    from app.sync.connector_settings import get_sync_engine_settings
    from app.sync.host_metrics_sync import rollup_and_prune_host_metrics

    db = SessionLocal()
    try:
        retention_days = get_sync_engine_settings(db).host_metrics_retention_days
        result = rollup_and_prune_host_metrics(db, retention_days)
        db.commit()
        log.info("scheduler_host_metrics_rollup_done", **result)
    except Exception as exc:
        log.error("scheduler_host_metrics_rollup_error", error=str(exc))
        db.rollback()
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

    last_run: dict[str, float] = {
        "vmware": 0.0, "nutanix": 0.0, "backup": 0.0,
        "vmware_datastore_metrics": 0.0, "nutanix_datastore_metrics": 0.0,
        "datastore_metrics_rollup": 0.0,
        "vmware_host_metrics": 0.0, "nutanix_host_metrics": 0.0,
        "host_metrics_rollup": 0.0,
    }

    if args.run_once:
        _sync_platform("vmware")
        _sync_platform("nutanix")
        log.info("run_once_complete")
        sys.exit(0)

    while True:
        now = time.time()
        vmware_minutes, nutanix_minutes, datastore_metrics_interval_secs, host_metrics_interval_secs = \
            _get_intervals(int(args.interval_hours * 60))
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

        # Datastore metrics — independent, typically shorter interval than
        # the full inventory syncs above (see run_*_datastore_metrics_sync).
        # Interval is in seconds (as low as 10s), not minutes.
        for platform in ("vmware", "nutanix"):
            key = f"{platform}_datastore_metrics"
            due_in = (last_run[key] + datastore_metrics_interval_secs) - now
            if due_in <= 0:
                log.info("scheduler_datastore_metrics_due", platform=platform,
                         interval_seconds=datastore_metrics_interval_secs)
                _sync_datastore_metrics(platform)
                last_run[key] = time.time()

        due_in = (last_run["datastore_metrics_rollup"] + _DATASTORE_METRICS_ROLLUP_INTERVAL_SECS) - now
        if due_in <= 0:
            log.info("scheduler_datastore_metrics_rollup_due")
            _run_datastore_metrics_rollup()
            last_run["datastore_metrics_rollup"] = time.time()

        # Host metrics — same pattern as datastore metrics above (see
        # run_*_host_metrics_sync). Interval is in seconds, not minutes.
        for platform in ("vmware", "nutanix"):
            key = f"{platform}_host_metrics"
            due_in = (last_run[key] + host_metrics_interval_secs) - now
            if due_in <= 0:
                log.info("scheduler_host_metrics_due", platform=platform,
                         interval_seconds=host_metrics_interval_secs)
                _sync_host_metrics(platform)
                last_run[key] = time.time()

        due_in = (last_run["host_metrics_rollup"] + _HOST_METRICS_ROLLUP_INTERVAL_SECS) - now
        if due_in <= 0:
            log.info("scheduler_host_metrics_rollup_due")
            _run_host_metrics_rollup()
            last_run["host_metrics_rollup"] = time.time()

        backup_enabled, backup_interval_minutes = _get_backup_settings()
        if backup_enabled:
            due_in = (last_run["backup"] + backup_interval_minutes * 60) - now
            if due_in <= 0:
                log.info("scheduler_backup_due", interval_minutes=backup_interval_minutes)
                _run_scheduled_backup()
                last_run["backup"] = time.time()

        # Poll every 5 seconds — metrics intervals can now be as low as 10s
        # (Settings -> Sync Engine), so a coarser poll would silently cap
        # the achievable cadence well above whatever's configured.
        time.sleep(5)


if __name__ == "__main__":
    main()
