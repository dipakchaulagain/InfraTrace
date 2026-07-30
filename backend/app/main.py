"""
main.py — FastAPI application entry point.
"""
import structlog
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api import auth, vms, hosts, networks, sync_runs, admin, settings as settings_router

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer() if settings.APP_ENV == "development" else structlog.processors.JSONRenderer(),
    ],
)

# Silence noisy 404s from browser telemetry extensions (Grafana Faro, OTel, etc.)
# These hit /api/v1/ingest and are not part of this application.
class _SuppressExtensionNoise(logging.Filter):
    _NOISE_PATHS = ("/api/v1/ingest", "/api/v1/traces", "/api/v1/logs", "/api/v1/metrics")
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in self._NOISE_PATHS)

logging.getLogger("uvicorn.access").addFilter(_SuppressExtensionNoise())

app = FastAPI(
    title="InfraTrace — VM/Host/Network Inventory Management System",
    version="2.0.0",
    description="Unified inventory platform for VMware vCenter and Nutanix Prism Element.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers under /api prefix
app.include_router(auth.router, prefix="/api")
app.include_router(vms.router, prefix="/api")
app.include_router(hosts.router, prefix="/api")
app.include_router(networks.router, prefix="/api")
app.include_router(sync_runs.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


# Silently absorb browser-extension telemetry noise (Grafana Faro, OTel SDKs)
# These are injected by browser extensions and are not part of this application.
@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def absorb_extension_telemetry(request: Request, path: str):
    return JSONResponse(status_code=200, content={"status": "ok"})
