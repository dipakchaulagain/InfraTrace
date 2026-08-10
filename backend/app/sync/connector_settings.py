"""
connector_settings.py — Runtime credential resolver.

Credentials are read exclusively from the source_systems DB row (set by an
admin via Admin -> Settings) — there is no environment-variable fallback.
Keeping exactly one place to configure connectors avoids the two paths
drifting out of sync.

Usage:
    from app.sync.connector_settings import get_vmware_creds, get_nutanix_creds
    creds = get_vmware_creds(db, source_system_id)
"""
import base64
import hashlib
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Fernet encryption
# ---------------------------------------------------------------------------

def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        from app.config import settings
        raw = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(raw)
        return Fernet(key)
    except ImportError:
        return None


def encrypt_password(plain: str) -> str:
    f = _get_fernet()
    if f is None:
        return plain
    return f.encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    if not encrypted:
        return encrypted
    f = _get_fernet()
    if f is None:
        return encrypted
    try:
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        # Value may be a legacy plain-text password stored before encryption was set up
        return encrypted


# ---------------------------------------------------------------------------
# Credential dataclasses
# ---------------------------------------------------------------------------

@dataclass
class VMwareCreds:
    host: str
    user: str
    password: str
    port: int
    insecure: bool


@dataclass
class NutanixCreds:
    base_url: str
    user: str
    password: str
    insecure: bool


@dataclass
class SyncEngineSettings:
    page_size: int
    retry_max_attempts: int
    retry_wait_min: float
    retry_wait_max: float
    vmware_interval_minutes: int
    nutanix_interval_minutes: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_host_from_url(base_url: str) -> tuple[str, Optional[int]]:
    """
    Parse a URL like 'https://vcenter.example.com:443' into ('vcenter.example.com', 443).
    Returns (host, port_or_None).
    """
    url = (base_url or "").strip().rstrip("/")
    for scheme in ("https://", "http://"):
        if url.startswith(scheme):
            url = url[len(scheme):]
            break
    # Remove any path after the host
    url = url.split("/")[0]
    # Split host:port
    if ":" in url and not url.startswith("["):
        parts = url.rsplit(":", 1)
        try:
            return parts[0], int(parts[1])
        except ValueError:
            return url, None
    return url, None


def _get_app_setting(db_session, key: str) -> Optional[str]:
    from app.models.inventory import AppSetting
    row = db_session.get(AppSetting, key)
    return row.value if row else None


# ---------------------------------------------------------------------------
# Public resolvers
# ---------------------------------------------------------------------------

def get_vmware_creds(db_session, source_system_id: str) -> Optional[VMwareCreds]:
    """
    Resolve VMware credentials for the given source system row (Admin ->
    Settings). Returns None if host, user, or password cannot be determined.
    """
    from app.models.inventory import SourceSystem

    source = db_session.get(SourceSystem, source_system_id)

    # --- Host + port ---
    host: Optional[str] = None
    port: int = 443

    if source and source.base_url:
        extracted_host, extracted_port = _extract_host_from_url(source.base_url)
        if extracted_host:
            host = extracted_host
        # Prefer the explicit port column; fall back to URL-embedded port
        if source.port is not None:
            port = source.port
        elif extracted_port is not None:
            port = extracted_port

    # --- Username ---
    user: Optional[str] = None
    if source and source.username and source.username.strip():
        user = source.username.strip()

    # --- Password ---
    password: Optional[str] = None
    if source and source.encrypted_password:
        password = decrypt_password(source.encrypted_password)

    # --- Insecure ---
    insecure: bool = bool(source.insecure) if (source and source.insecure is not None) else False

    if not host or not user or not password:
        log.warning(
            "vmware_creds_incomplete",
            source_id=source_system_id,
            has_host=bool(host),
            has_user=bool(user),
            has_password=bool(password),
        )
        return None

    return VMwareCreds(host=host, user=user, password=password, port=port, insecure=insecure)


def get_nutanix_creds(db_session, source_system_id: str) -> Optional[NutanixCreds]:
    """
    Resolve Nutanix credentials for the given source system row.
    Returns None if base_url, user, or password cannot be determined.
    """
    from app.models.inventory import SourceSystem

    source = db_session.get(SourceSystem, source_system_id)

    # --- base_url ---
    base_url: Optional[str] = None
    if source and source.base_url and source.base_url.strip():
        base_url = source.base_url.strip()

    # --- Username ---
    user: Optional[str] = None
    if source and source.username and source.username.strip():
        user = source.username.strip()

    # --- Password ---
    password: Optional[str] = None
    if source and source.encrypted_password:
        password = decrypt_password(source.encrypted_password)

    # --- Insecure ---
    insecure: bool = bool(source.insecure) if (source and source.insecure is not None) else False

    if not base_url or not user or not password:
        log.warning(
            "nutanix_creds_incomplete",
            source_id=source_system_id,
            has_url=bool(base_url),
            has_user=bool(user),
            has_password=bool(password),
        )
        return None

    return NutanixCreds(base_url=base_url, user=user, password=password, insecure=insecure)


# Hardcoded fallback defaults, used only until an admin saves Sync Engine
# settings for the first time (Admin -> Settings). Not environment-configurable
# — see the module docstring.
_DEFAULT_PAGE_SIZE = 100
_DEFAULT_RETRY_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_WAIT_MIN = 1.0
_DEFAULT_RETRY_WAIT_MAX = 30.0


def get_sync_engine_settings(db_session) -> SyncEngineSettings:
    def _int(key: str, default: int) -> int:
        val = _get_app_setting(db_session, key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def _float(key: str, default: float) -> float:
        val = _get_app_setting(db_session, key)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    return SyncEngineSettings(
        page_size=_int("sync.page_size", _DEFAULT_PAGE_SIZE),
        retry_max_attempts=_int("sync.retry_max_attempts", _DEFAULT_RETRY_MAX_ATTEMPTS),
        retry_wait_min=_float("sync.retry_wait_min", _DEFAULT_RETRY_WAIT_MIN),
        retry_wait_max=_float("sync.retry_wait_max", _DEFAULT_RETRY_WAIT_MAX),
        vmware_interval_minutes=_int("sync.vmware_interval_minutes", 240),
        nutanix_interval_minutes=_int("sync.nutanix_interval_minutes", 240),
    )
