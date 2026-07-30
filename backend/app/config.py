"""
config.py — Application-wide settings loaded from environment variables.
All defaults are safe for local development; override via .env or Docker secrets.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    DATABASE_URL: str = "postgresql://infratrace_app:changeme@localhost:5432/infratrace"

    # -------------------------------------------------------------------------
    # JWT / Auth
    # -------------------------------------------------------------------------
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours

    # Idle-session timeout — admin-overridable at runtime via AppSetting
    # ("auth.session_idle_timeout_minutes"), this is just the fallback default.
    SESSION_IDLE_TIMEOUT_MINUTES: int = 30

    # -------------------------------------------------------------------------
    # Password policy / reset
    # -------------------------------------------------------------------------
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_RESET_CODE_TTL_MINUTES: int = 30

    # -------------------------------------------------------------------------
    # Audit logging
    # -------------------------------------------------------------------------
    AUDIT_LOG_VM_VIEWS: bool = False   # routine reads are noisy; off by default

    # -------------------------------------------------------------------------
    # VMware vCenter credentials
    # -------------------------------------------------------------------------
    VCENTER_HOST: Optional[str] = None
    VCENTER_USER: Optional[str] = None
    VCENTER_PASSWORD: Optional[str] = None
    VCENTER_PORT: int = 443
    VCENTER_INSECURE: bool = False

    # -------------------------------------------------------------------------
    # Nutanix Prism Element credentials
    # -------------------------------------------------------------------------
    NUTANIX_BASE_URL: Optional[str] = None
    NUTANIX_USER: Optional[str] = None
    NUTANIX_PASSWORD: Optional[str] = None
    NUTANIX_INSECURE: bool = False

    # -------------------------------------------------------------------------
    # Sync engine
    # -------------------------------------------------------------------------
    SYNC_PAGE_SIZE: int = 100
    SYNC_RETRY_MAX_ATTEMPTS: int = 3
    SYNC_RETRY_WAIT_MIN: float = 1.0
    SYNC_RETRY_WAIT_MAX: float = 30.0

    # -------------------------------------------------------------------------
    # App
    # -------------------------------------------------------------------------
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]


settings = Settings()
