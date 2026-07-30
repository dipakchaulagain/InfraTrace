# InfraTrace — VM/Host/Network Inventory Management System

Unified inventory platform for **VMware vCenter** and **Nutanix Prism Element**.  
Pulls VM, host, and network data via read-only API accounts, normalises it into a shared schema, and exposes it through a dashboard UI with ownership/tagging and full audit history.

---

## Architecture

```
vCenter API ──► VMware Adapter ──┐
                                 ├──► Diff/Load ──► PostgreSQL ──► FastAPI ──► React UI
Prism Element ──► Nutanix Adapter ┘
```

- **Backend**: Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · structlog
- **Sync engine**: tenacity retry/backoff · dead-letter queue · SyncRun audit trail
- **Database**: PostgreSQL 16 · JSONB for NIC/disk arrays · Layer A/B permission boundary
- **Frontend**: React 18 · Vite · TypeScript · Tailwind CSS · TanStack Query · Recharts

---

## Quick Start (Docker Compose)

Nothing is required to start the stack — every setting has a safe default baked into `docker-compose.yml`.

```bash
docker-compose up -d
```

This will:
- Start PostgreSQL
- Run `alembic upgrade head` (creates all tables)
- Run `seed.py` (seeds departments, environments, default admin user)
- Start the FastAPI server on **port 8000**
- Start the sync scheduler (runs every 4 hours automatically)
- Build and serve the React UI on **port 80**

Open http://localhost and log in with `admin` / `admin`.
**Change the admin password immediately** via Admin → Users.

### Optional: override before first boot

Copy `.env.example` to `.env` in the project root if you want to set anything before starting:

```bash
cp .env.example .env
# then edit .env
```

- `SECRET_KEY` — JWT signing key, and the encryption key for connector passwords stored in the database. Defaults to an insecure placeholder; set a real one (`openssl rand -hex 32`) before exposing this beyond localhost.
- `VCENTER_*` / `NUTANIX_*` — vCenter/Prism connector credentials. **Not required.** It's usually easier to add connectors after logging in via **Admin → Settings** instead — only set these if you want a connector already configured at first boot.

See `.env.example` for the full list, including sync-engine tuning (also adjustable later from the Settings page).

---

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# or: source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
cp .env.example .env            # fill in your values

# Start PostgreSQL separately (or use Docker for just the DB):
docker run -d --name infratrace-db -p 5432:5432 \
  -e POSTGRES_DB=infratrace -e POSTGRES_USER=infratrace_app -e POSTGRES_PASSWORD=changeme \
  postgres:16

alembic upgrade head
python seed.py
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/api/docs

### Run a sync manually (one-shot):

```bash
python scheduler.py --run-once
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173

---

## Project Structure

```
InfraTrace/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers: auth, vms, hosts, sync_runs, admin
│   │   ├── models/       # SQLAlchemy ORM: inventory.py (Layer A) + metadata.py (Layer B)
│   │   ├── sync/         # Sync engine: base.py, vmware_adapter.py, nutanix_adapter.py
│   │   ├── config.py     # Settings (pydantic-settings, reads from .env)
│   │   ├── database.py   # Engine + session factory
│   │   └── main.py       # FastAPI app + CORS + router registration
│   ├── alembic/          # DB migrations
│   ├── scheduler.py      # Sync scheduler (runs adapters on interval)
│   ├── seed.py           # Initial data seed
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/   # Sidebar, Layout, StatCard, Pagination, etc.
│   │   ├── pages/        # Dashboard, VMs, VMDetail, Hosts, SyncHealth, Admin, Login
│   │   ├── lib/          # api.ts (axios), auth.tsx (context), utils.ts
│   │   └── App.tsx       # Router + auth guards
│   ├── tailwind.config.js
│   └── Dockerfile
├── docker-compose.yml
├── docs/
│   ├── Project Plan.md
│   └── Theme & Design Specification.md
└── Prototype script/     # Phase 1 prototype scripts (reference)
```

---

## Layer A / Layer B separation

The sync engine writes **only** Layer A (infrastructure facts):
`vms_current`, `hosts_current`, `clusters_current`, `networks_current`, `sync_runs`, `vm_history`, `dead_letter_records`

Ownership data lives **only** in Layer B:
`vm_metadata`, `vm_metadata_audit`, `departments`, `environments`, `tags`, `taggings`

The sync engine's DB role has zero grants on Layer B tables — enforced at the database permission level, not just in code.

---

## API Reference

Interactive docs at `/api/docs` (Swagger UI) once the backend is running.

Key endpoints:
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/token` | Login, returns JWT |
| GET | `/api/vms` | List VMs (filterable, paginated) |
| GET | `/api/vms/summary` | Dashboard counts + charts data |
| GET | `/api/vms/{id}` | VM detail |
| PATCH | `/api/vms/{id}/metadata` | Update ownership (admin, global editor, or the owning user) |
| GET | `/api/hosts` | List hosts |
| GET | `/api/sync/runs` | Sync run history |
| POST | `/api/sync/trigger/{platform}` | Manual sync trigger (admin) |
| GET | `/api/sync/dead-letters` | Dead-letter queue (admin) |

---

## Credentials setup (production)

- Use a **read-only** vCenter role with `System.View` / `System.Read` only
- Use the **Viewer** role in Nutanix Prism Element  
- Prefer configuring connectors via **Admin → Settings** in the UI — credentials are encrypted with `SECRET_KEY` and stored in the database, so there's no plaintext credential file to manage or rotate
- If you do use `.env` for connector credentials, store secrets via Docker secrets, Kubernetes Secrets, or your cloud provider's secrets manager — not plain `.env` files in production
- Generate a strong `SECRET_KEY`: `openssl rand -hex 32`
