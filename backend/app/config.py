"""
config.py — Application-wide settings loaded from environment variables.
All defaults are safe for local development; override via .env or Docker secrets.

The .env file lives at the repo root (not inside backend/) — one file for
both the Docker Compose flow and local (non-Docker) development, resolved
relative to this file's own location so it's found regardless of the
process's current working directory. See .env.example at the repo root.

VMware/Nutanix connector credentials and sync-engine tuning are deliberately
NOT environment variables — they're configured exclusively via Admin ->
Settings in the UI (stored encrypted in the database) so there's exactly one
place to manage them, not two paths that can drift out of sync.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    DATABASE_URL: str = "postgresql://infratrace_app:changeme@localhost:5432/infratrace"

    # -------------------------------------------------------------------------
    # JWT / Session
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
    # Brute-force lockout — throttles repeated failed attempts using the
    # existing access_logs trail rather than a separate rate-limit store.
    # -------------------------------------------------------------------------
    LOGIN_LOCKOUT_THRESHOLD: int = 5
    LOGIN_LOCKOUT_WINDOW_MINUTES: int = 15
    RESET_CODE_LOCKOUT_THRESHOLD: int = 8
    RESET_CODE_LOCKOUT_WINDOW_MINUTES: int = 15

    # -------------------------------------------------------------------------
    # Audit logging
    # -------------------------------------------------------------------------
    AUDIT_LOG_VM_VIEWS: bool = False   # routine reads are noisy; off by default

    # -------------------------------------------------------------------------
    # DB backup/restore — bind-mounted to ./backup on the host (see
    # docker-compose.yml) so files survive container recreation and can be
    # copied to another machine for disaster recovery.
    # -------------------------------------------------------------------------
    BACKUP_DIR: str = "/app/backups"

    # -------------------------------------------------------------------------
    # Default admin account — created by seed.py on first boot only (skipped
    # if a user with this username already exists). Change the password via
    # Admin -> Users immediately after first login.
    # -------------------------------------------------------------------------
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_EMAIL: str = "admin@infratrace.local"
    DEFAULT_ADMIN_PASSWORD: str = "admin"

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
