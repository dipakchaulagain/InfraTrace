# InfraTrace — VM/Host/Network Inventory Management System

Unified inventory platform for **VMware vCenter** and **Nutanix Prism Element**.
Pulls VM, host, and network data via read-only API accounts, normalises it into a shared schema, and exposes it through a dashboard UI with ownership tracking, role-based access control, and full audit history.

---

## Features

**Inventory & visibility**
- Unified VM list across VMware and Nutanix, with sortable columns (name, platform, state, OS, vCPU, memory, disk, owner, department, environment, last synced) and filters (platform, power state, department, environment, owner, cluster, OS detail, tools status, unassigned-only, free-text search)
- VM detail page: infrastructure facts (read-only), NICs and disks with per-IP validity classification, infrastructure change history, and ownership audit trail
- Dedicated **Decommissioned VMs** page (admin / global editor only) with date-range, owner, department, and environment filters — decommissioned VMs never appear in the main list
- Dashboard: VM/power-state/decommissioned/unassigned counts, VMware-vs-Nutanix split, OS distribution chart, department/environment breakdowns, recent sync runs — with clickable stat cards that deep-link into filtered VM views
- CSV export of the current filtered VM list

**Ownership & metadata (Layer B)**
- Owner and optional secondary owner, department, environment, notes
- **OS Detail** — free-text override for the specific OS version, supplementing the platform-reported generic OS type
- **Management IP** — a validated, known-good IPv4 address with a computed Match / Mismatch / No-platform-IP indicator against the platform-reported IP(s)
- Every metadata change is written to a per-VM audit trail (old value → new value, who, when)

**Role-based access control**
| Role | Access |
|---|---|
| **Admin** | Full access to everything, including Settings, Admin, and the Audit Log |
| **Global Editor** | Views all VMs and Hosts/Networks/Sync Health; can edit metadata (owner, secondary owner, department, environment, notes, OS detail, management IP) on any VM |
| **User** | Views and edits only VMs they own (owner/secondary owner, department, environment, notes — not OS detail or management IP); no access to Hosts, Networks, or other non-VM pages |
| **Viewer** | Read-only access to owned VMs only |

RBAC is enforced server-side on every endpoint (ownership-scoped queries, per-field edit permissions) — the frontend's role checks are for navigation/UX only.

**Authentication & security**
- JWT auth backed by server-side sessions, so logout and idle-timeout actually revoke access instead of waiting out the token's natural expiry
- Configurable idle-session timeout (default 30 min, admin-adjustable) with an in-app warning before expiry
- Password policy (length + complexity) enforced on every password set
- Forced password reset on admin-created accounts and first login
- Admin-triggered password reset via a one-time code (no email service required)
- Login access is a separate, admin-controlled toggle per user, off by default

**Audit logging**
- Every significant action is logged: login/logout, session timeout, password changes/resets, user account changes, VM metadata edits, VM decommissioning, and permission-denied attempts
- Admin-only Audit Log page with filters for date range, user, action type, and entity

**Sync engine**
- Retry/backoff via `tenacity`, dead-letter queue for records that fail validation, full `SyncRun` history with per-run validation reports
- Diff/load shared between both platform adapters — only meaningful field changes are recorded, decommissioning is detected (not deleted) when a VM disappears from a source
- Manual sync trigger and dead-letter resolution from the Sync Health page

**Admin**
- Users: create/update, role assignment, login-allowed toggle, forced-reset toggle, one-time reset code generation — via a slide-in panel, not an inline form
- Departments, Environments, Tags (normalized lookups)
- Source system connectors: credentials configured via Settings (encrypted at rest), enable/disable from Admin

---

## Architecture

```
vCenter API ──► VMware Adapter ──┐
                                 ├──► Diff/Load ──► PostgreSQL ──► FastAPI ──► React UI
Prism Element ──► Nutanix Adapter ┘
```

- **Backend**: Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · structlog · passlib/bcrypt · python-jose (JWT) · cryptography (Fernet, for encrypted connector credentials)
- **Sync engine**: tenacity retry/backoff · dead-letter queue · SyncRun audit trail
- **Database**: PostgreSQL 16 · JSONB for NIC/disk arrays · Layer A/B permission boundary
- **Frontend**: React 18 · Vite · TypeScript · Tailwind CSS · TanStack Query · Recharts · React Router

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
│   │   ├── api/           # FastAPI routers: auth, vms, hosts, networks, sync_runs, admin, settings
│   │   ├── models/        # SQLAlchemy ORM: inventory.py (Layer A) + metadata.py (Layer B)
│   │   ├── sync/          # Sync engine: base.py, vmware_adapter.py, nutanix_adapter.py, connector_settings.py
│   │   ├── audit.py       # Single write path into the audit log
│   │   ├── config.py      # Settings (pydantic-settings, reads from .env)
│   │   ├── database.py    # Engine + session factory
│   │   └── main.py        # FastAPI app + CORS + router registration
│   ├── alembic/           # DB migrations
│   ├── scheduler.py       # Sync scheduler (runs adapters on interval)
│   ├── seed.py            # Initial data seed
│   ├── wait_for_db.py     # DB startup wait helper
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/    # Sidebar, Layout, Drawer, StatCard, Pagination, SessionTimeoutWarning, etc.
│   │   ├── pages/         # Dashboard, VMs, VMDetail, DecommissionedVMs, Hosts, Networks,
│   │   │                  # SyncHealth, Settings, Admin, AuditLog, Login, ResetRequired
│   │   ├── lib/           # api.ts (axios client), auth.tsx (auth context), permissions.ts (RBAC matrix), utils.ts
│   │   └── App.tsx        # Router + auth/role guards
│   ├── tailwind.config.js
│   └── Dockerfile
├── docker-compose.yml
├── docs/                   # Project plan, design spec, deployment guide (not tracked in git)
└── Prototype script/       # Phase 1 prototype scripts, reference only (not tracked in git)
```

---

## Layer A / Layer B separation

The sync engine writes **only** Layer A (infrastructure facts):
`vms_current`, `hosts_current`, `clusters_current`, `networks_current`, `sync_runs`, `vm_history`, `dead_letter_records`

Ownership and application data lives **only** in Layer B:
`vm_metadata`, `vm_metadata_audit`, `departments`, `environments`, `tags`, `taggings`, `users`, `user_sessions`, `password_reset_codes`, `access_logs`

The sync engine's DB role has zero grants on Layer B tables — enforced at the database permission level, not just in code.

---

## API Reference

Interactive docs at `/api/docs` (Swagger UI) once the backend is running. All routes below are prefixed with `/api`.

**Auth** (`/auth`)
| Method | Path | Description |
|---|---|---|
| POST | `/auth/token` | Login, returns JWT bound to a server-side session |
| POST | `/auth/logout` | Revoke the current session |
| POST | `/auth/change-password` | Change your own password (also completes a forced first-login reset) |
| POST | `/auth/reset-password` | Complete a self-service reset using an admin-issued one-time code |
| GET | `/auth/me` | Current user profile |

**VMs** (`/vms`)
| Method | Path | Description |
|---|---|---|
| GET | `/vms` | List VMs — filterable, sortable, paginated; owner-scoped for User/Viewer roles |
| GET | `/vms/decommissioned` | List decommissioned VMs (admin / global editor only) |
| GET | `/vms/summary` | Dashboard counts + chart data |
| GET | `/vms/{id}` | VM detail |
| PATCH | `/vms/{id}/metadata` | Update ownership/metadata (admin, global editor, or the owning user — field-level permissions apply) |
| GET | `/vms/{id}/history` | Infrastructure change history |
| GET | `/vms/{id}/metadata-audit` | Ownership/metadata audit trail |

**Hosts / Networks**
| Method | Path | Description |
|---|---|---|
| GET | `/hosts` | List hosts (admin / global editor only) |
| GET | `/networks` | List networks/VLANs (admin / global editor only) |

**Sync** (`/sync`)
| Method | Path | Description |
|---|---|---|
| GET | `/sync/runs` | Sync run history (admin / global editor only) |
| GET | `/sync/runs/{id}` | Sync run detail + validation report |
| GET | `/sync/dead-letters` | Dead-letter queue (admin only) |
| POST | `/sync/dead-letters/{id}/resolve` | Mark a dead-letter record resolved (admin only) |
| POST | `/sync/trigger/{platform}` | Manually trigger a sync for `vmware` or `nutanix` (admin only) |

**Admin** (`/admin`)
| Method | Path | Description |
|---|---|---|
| GET/POST | `/admin/departments` | List / create departments |
| GET/POST | `/admin/environments` | List / create environments |
| GET/POST | `/admin/tags` | List / create tags |
| GET | `/admin/users` | List users (admin only) |
| GET | `/admin/users/lookup` | Minimal id+name list for owner pickers (admin / global editor) |
| POST | `/admin/users` | Create a user (admin only) |
| PATCH | `/admin/users/{id}` | Update a user — role, department, login-allowed, forced-reset flag, active (admin only) |
| POST | `/admin/users/{id}/trigger-reset` | Generate a one-time password reset code (admin only) |
| GET | `/admin/audit-logs` | Query the audit log (admin only) |
| GET | `/admin/sources` | List connector source systems (admin only) |
| PATCH | `/admin/sources/{id}/toggle` | Enable/disable a connector (admin only) |

**Settings** (`/settings`, admin only)
| Method | Path | Description |
|---|---|---|
| GET | `/settings` | Read all current settings (passwords masked) |
| PUT | `/settings/vmware` | Upsert VMware connector credentials |
| PUT | `/settings/nutanix` | Upsert Nutanix connector credentials |
| PUT | `/settings/sync` | Sync engine tuning (page size, retry policy, intervals) |
| PUT | `/settings/general` | Timezone, session idle timeout |
| POST | `/settings/test/{platform}` | Live connection test using saved credentials |

---

## Credentials setup (production)

- Use a **read-only** vCenter role with `System.View` / `System.Read` only
- Use the **Viewer** role in Nutanix Prism Element
- Prefer configuring connectors via **Admin → Settings** in the UI — credentials are encrypted with `SECRET_KEY` and stored in the database, so there's no plaintext credential file to manage or rotate
- If you do use `.env` for connector credentials, store secrets via Docker secrets, Kubernetes Secrets, or your cloud provider's secrets manager — not plain `.env` files in production
- Generate a strong `SECRET_KEY`: `openssl rand -hex 32`
