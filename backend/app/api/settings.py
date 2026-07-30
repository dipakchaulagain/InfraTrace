"""
settings.py — Admin Settings API.

Single source of truth for connector credentials and sync tuning.
One canonical SourceSystem row per platform — Settings and Admin
both read/write the same row, no duplicates.

GET  /api/settings           — read all current values (passwords masked)
PUT  /api/settings/vmware    — upsert VMware connector
PUT  /api/settings/nutanix   — upsert Nutanix connector
PUT  /api/settings/sync      — upsert sync engine tuning
POST /api/settings/test/{p}  — live connection test (uses saved creds)
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.database import get_db
from app.models.inventory import AppSetting, SourceSystem
from app.models.metadata import User
from app.sync.connector_settings import encrypt_password

router = APIRouter(prefix="/settings", tags=["settings"])

_PASSWORD_MASK = "••••••••"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VMwareSettingsUpdate(BaseModel):
    host: str
    user: str
    password: Optional[str] = None   # omit / mask = keep existing
    port: int = 443
    insecure: bool = False

    @field_validator("host")
    @classmethod
    def strip_scheme(cls, v: str) -> str:
        for s in ("https://", "http://"):
            if v.startswith(s):
                v = v[len(s):]
        # Also strip any trailing port that the user may have pasted in
        v = v.strip().rstrip("/")
        if ":" in v:
            parts = v.rsplit(":", 1)
            try:
                int(parts[1])
                v = parts[0]   # drop the port — we store it separately
            except ValueError:
                pass
        return v


class NutanixSettingsUpdate(BaseModel):
    base_url: str
    user: str
    password: Optional[str] = None
    insecure: bool = False

    @field_validator("base_url")
    @classmethod
    def normalise_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith("http"):
            v = "https://" + v
        return v


class SyncSettingsUpdate(BaseModel):
    page_size: int = 100
    retry_max_attempts: int = 3
    retry_wait_min: float = 1.0
    retry_wait_max: float = 30.0
    vmware_interval_minutes: int = 240
    nutanix_interval_minutes: int = 240


class GeneralSettingsUpdate(BaseModel):
    timezone: str = "UTC"
    session_idle_timeout_minutes: int = 30


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _upsert_app_setting(db: Session, key: str, value: str, user_id: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = user_id
    else:
        db.add(AppSetting(
            key=key, value=value,
            updated_at=datetime.now(timezone.utc),
            updated_by=user_id,
        ))


def _get_canonical_source(db: Session, platform: str) -> Optional[SourceSystem]:
    """
    Return THE canonical source system row for a platform.
    Prefers a row that already has credentials; otherwise the first one found.
    Never creates a new row here — that's Settings PUT's job.
    """
    rows = db.query(SourceSystem).filter_by(platform=platform).all()
    if not rows:
        return None
    # Prefer a row that has credentials stored
    for row in rows:
        if row.username or row.encrypted_password:
            return row
    return rows[0]


def _get_or_create_canonical_source(db: Session, platform: str) -> SourceSystem:
    """
    Return the canonical row for a platform, creating one if none exists.
    Merges duplicates: if multiple rows exist with credentials, use the one
    with the most complete credentials and deactivate the rest.
    """
    rows = db.query(SourceSystem).filter_by(platform=platform).all()

    if not rows:
        source = SourceSystem(
            platform=platform,
            display_name=f"{platform.capitalize()} connector",
            base_url="",
            is_active=True,
        )
        db.add(source)
        db.flush()
        return source

    if len(rows) == 1:
        return rows[0]

    # Multiple rows — pick the best one (has credentials), mark rest inactive
    credentialed = [r for r in rows if r.username and r.encrypted_password]
    canonical = credentialed[0] if credentialed else rows[0]
    for row in rows:
        if row.id != canonical.id:
            row.is_active = False
    canonical.is_active = True
    db.flush()
    return canonical


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------

@router.get("")
def get_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    from app.config import settings as env_settings

    # VMware
    vmware_row = _get_canonical_source(db, "vmware")
    vmware: Optional[dict] = None
    if vmware_row:
        vmware = {
            "source_id": vmware_row.id,
            "host": _extract_host(vmware_row.base_url),
            "user": vmware_row.username or "",
            "password": _PASSWORD_MASK if vmware_row.encrypted_password else "",
            "port": vmware_row.port if vmware_row.port is not None else 443,
            "insecure": bool(vmware_row.insecure),
            "display_name": vmware_row.display_name,
            "is_active": vmware_row.is_active,
            "configured": bool(vmware_row.username and vmware_row.encrypted_password),
        }
    else:
        # Fall back to showing .env values as prefill (password always blank)
        vmware = {
            "source_id": None,
            "host": env_settings.VCENTER_HOST or "",
            "user": env_settings.VCENTER_USER or "",
            "password": "",
            "port": env_settings.VCENTER_PORT,
            "insecure": env_settings.VCENTER_INSECURE,
            "display_name": "",
            "is_active": False,
            "configured": False,
        }

    # Nutanix
    nutanix_row = _get_canonical_source(db, "nutanix")
    nutanix: Optional[dict] = None
    if nutanix_row:
        nutanix = {
            "source_id": nutanix_row.id,
            "base_url": nutanix_row.base_url or "",
            "user": nutanix_row.username or "",
            "password": _PASSWORD_MASK if nutanix_row.encrypted_password else "",
            "insecure": bool(nutanix_row.insecure),
            "display_name": nutanix_row.display_name,
            "is_active": nutanix_row.is_active,
            "configured": bool(nutanix_row.username and nutanix_row.encrypted_password),
        }
    else:
        nutanix = {
            "source_id": None,
            "base_url": env_settings.NUTANIX_BASE_URL or "",
            "user": env_settings.NUTANIX_USER or "",
            "password": "",
            "insecure": env_settings.NUTANIX_INSECURE,
            "display_name": "",
            "is_active": False,
            "configured": False,
        }

    # Sync engine
    def _sv(key: str, default: str) -> str:
        row = db.get(AppSetting, key)
        return row.value if (row and row.value is not None) else default

    sync = {
        "page_size":                  int(_sv("sync.page_size",                  str(env_settings.SYNC_PAGE_SIZE))),
        "retry_max_attempts":         int(_sv("sync.retry_max_attempts",         str(env_settings.SYNC_RETRY_MAX_ATTEMPTS))),
        "retry_wait_min":           float(_sv("sync.retry_wait_min",             str(env_settings.SYNC_RETRY_WAIT_MIN))),
        "retry_wait_max":           float(_sv("sync.retry_wait_max",             str(env_settings.SYNC_RETRY_WAIT_MAX))),
        "vmware_interval_minutes":    int(_sv("sync.vmware_interval_minutes",    "240")),
        "nutanix_interval_minutes":   int(_sv("sync.nutanix_interval_minutes",   "240")),
    }

    general = {
        "timezone": _sv("app.timezone", "UTC"),
        "session_idle_timeout_minutes": int(_sv(
            "auth.session_idle_timeout_minutes", str(env_settings.SESSION_IDLE_TIMEOUT_MINUTES)
        )),
    }

    return {"vmware": vmware, "nutanix": nutanix, "sync": sync, "general": general}


def _extract_host(base_url: str) -> str:
    """Strip scheme and port from a base_url to get just the hostname."""
    h = (base_url or "").strip().rstrip("/")
    for s in ("https://", "http://"):
        if h.startswith(s):
            h = h[len(s):]
            break
    # Remove port suffix
    if ":" in h and not h.startswith("["):
        parts = h.rsplit(":", 1)
        try:
            int(parts[1])
            h = parts[0]
        except ValueError:
            pass
    return h


# ---------------------------------------------------------------------------
# PUT /api/settings/vmware
# ---------------------------------------------------------------------------

@router.put("/vmware")
def update_vmware_settings(
    payload: VMwareSettingsUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    source = _get_or_create_canonical_source(db, "vmware")

    # Always store a clean https:// URL — port embedded only if non-standard
    port_suffix = f":{payload.port}" if payload.port not in (80, 443) else ""
    source.base_url = f"https://{payload.host}{port_suffix}"
    source.username = payload.user.strip()
    source.port = payload.port
    source.insecure = payload.insecure
    source.display_name = f"vCenter — {payload.host}"
    source.is_active = True

    # Update password only when a new non-mask value is provided
    new_pw = (payload.password or "").strip()
    if new_pw and new_pw != _PASSWORD_MASK:
        source.encrypted_password = encrypt_password(new_pw)

    db.commit()
    db.refresh(source)

    background_tasks.add_task(_test_vmware_bg, source.id)

    return {
        "status": "ok",
        "message": "VMware settings saved.",
        "source_id": source.id,
        "configured": bool(source.username and source.encrypted_password),
    }


# ---------------------------------------------------------------------------
# PUT /api/settings/nutanix
# ---------------------------------------------------------------------------

@router.put("/nutanix")
def update_nutanix_settings(
    payload: NutanixSettingsUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    source = _get_or_create_canonical_source(db, "nutanix")

    source.base_url = payload.base_url
    source.username = payload.user.strip()
    source.insecure = payload.insecure
    try:
        hostname = payload.base_url.split("//")[1].split(":")[0].split("/")[0]
        source.display_name = f"Prism Element — {hostname}"
    except Exception:
        source.display_name = "Prism Element"
    source.is_active = True

    new_pw = (payload.password or "").strip()
    if new_pw and new_pw != _PASSWORD_MASK:
        source.encrypted_password = encrypt_password(new_pw)

    db.commit()
    db.refresh(source)

    background_tasks.add_task(_test_nutanix_bg, source.id)

    return {
        "status": "ok",
        "message": "Nutanix settings saved.",
        "source_id": source.id,
        "configured": bool(source.username and source.encrypted_password),
    }


# ---------------------------------------------------------------------------
# PUT /api/settings/sync
# ---------------------------------------------------------------------------

@router.put("/sync")
def update_sync_settings(
    payload: SyncSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    uid = current_user.id
    _upsert_app_setting(db, "sync.page_size",                  str(payload.page_size),                  uid)
    _upsert_app_setting(db, "sync.retry_max_attempts",         str(payload.retry_max_attempts),         uid)
    _upsert_app_setting(db, "sync.retry_wait_min",             str(payload.retry_wait_min),             uid)
    _upsert_app_setting(db, "sync.retry_wait_max",             str(payload.retry_wait_max),             uid)
    _upsert_app_setting(db, "sync.vmware_interval_minutes",    str(payload.vmware_interval_minutes),    uid)
    _upsert_app_setting(db, "sync.nutanix_interval_minutes",   str(payload.nutanix_interval_minutes),   uid)
    db.commit()
    return {"status": "ok", "message": "Sync settings saved."}


# ---------------------------------------------------------------------------
# PUT /api/settings/general
# ---------------------------------------------------------------------------

@router.put("/general")
def update_general_settings(
    payload: GeneralSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    _upsert_app_setting(db, "app.timezone", payload.timezone, current_user.id)
    _upsert_app_setting(
        db, "auth.session_idle_timeout_minutes", str(payload.session_idle_timeout_minutes), current_user.id
    )
    db.commit()
    return {"status": "ok", "message": "General settings saved."}


# ---------------------------------------------------------------------------
# POST /api/settings/test/{platform}
# ---------------------------------------------------------------------------

@router.post("/test/{platform}")
def test_connection(
    platform: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    if platform == "vmware":
        return _test_vmware_sync(db)
    elif platform == "nutanix":
        return _test_nutanix_sync(db)
    raise HTTPException(status_code=400, detail="platform must be 'vmware' or 'nutanix'")


# ---------------------------------------------------------------------------
# Connection testers
# ---------------------------------------------------------------------------

def _test_vmware_bg(source_id: str) -> None:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _test_vmware_sync(db, source_id)
    finally:
        db.close()


def _test_vmware_sync(db: Session, source_id: Optional[str] = None) -> dict:
    from app.sync.connector_settings import get_vmware_creds
    import ssl

    try:
        from pyVim.connect import SmartConnect, Disconnect
    except ImportError:
        return {"status": "error", "message": "pyvmomi not installed on server"}

    if source_id is None:
        row = _get_canonical_source(db, "vmware")
        source_id = row.id if row else None
    if not source_id:
        return {"status": "error", "message": "No VMware source configured"}

    creds = get_vmware_creds(db, source_id)
    if not creds:
        return {"status": "error", "message": "VMware credentials incomplete — save host, username, and password first"}

    try:
        ctx = None
        if creds.insecure:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        si = SmartConnect(
            host=creds.host, user=creds.user, pwd=creds.password,
            port=creds.port, sslContext=ctx,
        )
        about = si.content.about
        Disconnect(si)
        return {
            "status": "ok",
            "message": f"Connected to {creds.host}",
            "detail": f"{about.fullName} (API {about.apiVersion})",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _test_nutanix_bg(source_id: str) -> None:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        _test_nutanix_sync(db, source_id)
    finally:
        db.close()


def _test_nutanix_sync(db: Session, source_id: Optional[str] = None) -> dict:
    from app.sync.connector_settings import get_nutanix_creds
    import requests as req

    if source_id is None:
        row = _get_canonical_source(db, "nutanix")
        source_id = row.id if row else None
    if not source_id:
        return {"status": "error", "message": "No Nutanix source configured"}

    creds = get_nutanix_creds(db, source_id)
    if not creds:
        return {"status": "error", "message": "Nutanix credentials incomplete — save base URL, username, and password first"}

    try:
        url = f"{creds.base_url.rstrip('/')}/cluster"
        r = req.get(url, auth=(creds.user, creds.password),
                    verify=not creds.insecure, timeout=10)
        r.raise_for_status()
        cluster_name = r.json().get("name", "unknown")
        return {
            "status": "ok",
            "message": f"Connected — cluster '{cluster_name}'",
            "detail": creds.base_url,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
