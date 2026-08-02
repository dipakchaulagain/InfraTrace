"""
backup.py — Postgres backup/restore core.

Uses pg_dump/pg_restore (native tools, custom/compressed format) rather than
a hand-rolled export, so a backup is a true full-fidelity DB backup and
restore is reliable. Shared by the Settings API (manual trigger, restore,
listing, download, upload) and scheduler.py (scheduled automatic backups).

Every filename that reaches a subprocess argument or filesystem path is
validated against FILENAME_RE first and resolved strictly inside BACKUP_DIR
— this is the only path-traversal defense, since restore/download accept a
client-supplied filename.
"""
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from app.config import settings

log = structlog.get_logger()

BACKUP_DIR = Path(settings.BACKUP_DIR)
DB_NAME = "infratrace"   # matches docker-compose POSTGRES_DB
FILENAME_RE = re.compile(r"^backup_[A-Za-z0-9]+_\d{8}_\d{6}\.dump$")

# pg_dump/pg_restore rarely take this long at this app's stated scale
# (hundreds to low thousands of VMs) — this is a circuit breaker, not a
# tuned expectation.
_SUBPROCESS_TIMEOUT_SECS = 1800


@dataclass
class BackupResult:
    status: str   # "ok" | "error"
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    message: Optional[str] = None


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def ensure_backup_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def list_backups() -> list[dict]:
    """Every valid backup file in BACKUP_DIR, newest first."""
    ensure_backup_dir()
    files = []
    for p in BACKUP_DIR.glob("backup_*.dump"):
        if not FILENAME_RE.match(p.name):
            continue
        stat = p.stat()
        files.append({
            "filename": p.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    files.sort(key=lambda f: f["created_at"], reverse=True)
    return files


def resolve_backup_path(filename: str) -> Path:
    """Validate a client-supplied filename against the naming convention and
    resolve it strictly inside BACKUP_DIR. Raises ValueError on anything
    that doesn't match — including path-traversal attempts — before it
    reaches a subprocess argument or the filesystem."""
    if not FILENAME_RE.match(filename):
        raise ValueError("Invalid backup filename")
    base = BACKUP_DIR.resolve()
    path = (BACKUP_DIR / filename).resolve()
    if path.parent != base:
        raise ValueError("Invalid backup filename")
    return path


def create_backup(reason: str = "manual") -> BackupResult:
    """Run pg_dump in custom (compressed, non-locking) format. pg_dump takes
    a consistent MVCC snapshot in a single transaction — it never blocks
    concurrent reads/writes on the live DB."""
    ensure_backup_dir()
    filename = f"backup_{DB_NAME}_{_timestamp()}.dump"
    final_path = BACKUP_DIR / filename
    tmp_path = final_path.with_suffix(".dump.tmp")

    cmd = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={tmp_path}",
        settings.DATABASE_URL,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECS)
    except subprocess.TimeoutExpired:
        tmp_path.unlink(missing_ok=True)
        log.error("backup_failed", reason=reason, error="timeout")
        return BackupResult(status="error", message="Backup timed out")
    except FileNotFoundError:
        log.error("backup_failed", reason=reason, error="pg_dump not found")
        return BackupResult(status="error", message="pg_dump is not installed in this container")

    if proc.returncode != 0 or not tmp_path.exists():
        tmp_path.unlink(missing_ok=True)
        err = proc.stderr.strip()[-500:] or "pg_dump failed"
        log.error("backup_failed", reason=reason, error=err)
        return BackupResult(status="error", message=err)

    tmp_path.rename(final_path)   # atomic — never leaves a partial file under the real name
    size = final_path.stat().st_size
    log.info("backup_created", filename=filename, size_bytes=size, reason=reason)
    return BackupResult(status="ok", filename=filename, size_bytes=size)


def apply_retention(keep: int) -> list[str]:
    """Delete the oldest backups beyond `keep`. Returns deleted filenames."""
    if keep <= 0:
        return []
    files = list_backups()
    deleted = []
    for f in files[keep:]:
        try:
            (BACKUP_DIR / f["filename"]).unlink()
            deleted.append(f["filename"])
        except OSError:
            pass
    if deleted:
        log.info("backup_retention_cleanup", deleted=deleted, kept=keep)
    return deleted


def restore_backup(path: Path) -> BackupResult:
    """Restore via pg_restore --clean --if-exists --single-transaction: the
    whole restore runs as one transaction, so any failure rolls back
    completely and the existing DB is left exactly as it was — never a
    partial/broken state."""
    if not path.exists():
        return BackupResult(status="error", message="Backup file not found")

    # Release this process's own pooled connections first so pg_restore's
    # DROP TABLE ... isn't stuck waiting on a lock this same process holds.
    try:
        from app.database import engine
        engine.dispose()
    except Exception:
        pass

    cmd = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--single-transaction",
        f"--dbname={settings.DATABASE_URL}",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECS)
    except subprocess.TimeoutExpired:
        log.error("restore_failed", filename=path.name, error="timeout")
        return BackupResult(status="error", message="Restore timed out")
    except FileNotFoundError:
        log.error("restore_failed", filename=path.name, error="pg_restore not found")
        return BackupResult(status="error", message="pg_restore is not installed in this container")
    finally:
        try:
            from app.database import engine
            engine.dispose()
        except Exception:
            pass

    if proc.returncode != 0:
        err = proc.stderr.strip()[-800:] or "pg_restore failed"
        log.error("restore_failed", filename=path.name, error=err)
        return BackupResult(status="error", message=err)

    log.info("restore_completed", filename=path.name)
    return BackupResult(status="ok", filename=path.name)


def sanitize_upload_filename(original: str) -> str:
    """Generate a safe, collision-resistant stored filename for an uploaded
    backup — never trusts the client-supplied name directly, but keeps a
    sanitized fragment of it for the admin's own reference."""
    base = os.path.basename(original or "upload")
    stem = re.sub(r"[^A-Za-z0-9]", "", os.path.splitext(base)[0])[:40] or "upload"
    return f"backup_{stem}_{_timestamp()}.dump"
