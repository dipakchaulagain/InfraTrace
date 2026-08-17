# InfraTrace — VM/Host/Network Inventory Management System
![Alt Text](frontend/public/login-logo.png)

Unified inventory platform for **VMware vCenter** and **Nutanix Prism Element**.
Pulls VM, host, and network data via read-only API accounts, normalises it into a shared schema, and exposes it through a dashboard UI with ownership tracking, role-based access control, and full audit history.

---

## Features

**Inventory & visibility**
- Unified VM list across VMware and Nutanix, with sortable columns (name, platform, state, OS, vCPU, memory, disk, owner, department, environment, last synced) and filters (platform, power state, department, environment, owner, application, tag, cluster, OS detail, tools status, unassigned-only, free-text search)
- **Column picker** — toggle any column on/off (including metadata ones not shown by default: OS Detail, IP Address, Cluster, Host, Tools Status, Secondary Owner, Applications, Tags, Notes), persisted per-browser
- **Quick-edit** — a per-row Edit button opens a slide-in metadata form without leaving the list, same permissions as the VM Detail page
- **Bulk edit** — select multiple VMs (checkbox column) and apply owner, secondary owner, department, environment, OS Detail, applications, tags, and/or notes to all of them at once; each field is opt-in per edit (only checked fields are touched) and Applications/Tags replace each VM's full list rather than merge. IP Address is deliberately not offered here — it's a per-VM fact, not something to set identically across a batch. Partial success is normal: a VM that's since been deleted, or that an owner-scoped role no longer owns, is skipped and reported rather than failing the whole batch
- VM detail page: infrastructure facts (read-only), NICs and disks with per-IP validity classification, infrastructure change history, and ownership audit trail
- Dedicated **Decommissioned VMs** page (admin / global editor only) showing vCPU, memory, disk, and IP alongside ownership, with date-range, owner, department, and environment filters — decommissioned VMs never appear in the main list
- Dashboard: VM/power-state/decommissioned/unassigned counts, VMware-vs-Nutanix split, OS distribution chart, department/environment breakdowns, recent sync runs — with clickable stat cards that deep-link into filtered VM views
- Click-through filtering: clicking a Department/Application/Environment/Tag entry (or its VM count) in Metadata, or a user's VM count on the Users list, opens the VMs page pre-filtered to matching VMs

**Ownership & metadata (Layer B)**
- Owner and optional secondary owner, department, environment, notes
- **OS Detail** — free-text override for the specific OS version, supplementing the platform-reported generic OS type
- **IP Address** — a validated, known-good IPv4 address with a computed Match / Mismatch / No-platform-IP indicator against the platform-reported IP(s)
- **Applications** and **Tags** — multi-select from managed lists (Metadata → Applications / Tags); an entry must exist there before it can be attached to a VM
- Every metadata change is written to a per-VM audit trail (old value → new value, who, when)

**Role-based access control**
| Role | Access |
|---|---|
| **Admin** | Full access to everything, including Settings, Admin, and the Audit Log |
| **Global Editor** | Views all VMs and Hosts/Networks/Sync Health; can edit metadata (owner, secondary owner, department, environment, notes, OS detail, IP address, applications, tags) on any VM; full access to Metadata — can create/delete Departments, Applications, Environments, and Tags |
| **Global Viewer** | Read-only access to all VMs, Hosts, Networks, and Metadata (plus the Dashboard) — no ownership scoping, but can't edit any VM metadata and sees Metadata's lookup lists view-only (no create/delete); no access to Sync Health, Decommissioned VMs, Settings, Admin, or the Audit Log |
| **User** | Views and edits only VMs they own (owner/secondary owner, department, environment, notes — not OS detail, IP address, applications, or tags); no access to Hosts, Networks, or other non-VM pages |
| **Viewer** | Read-only access to owned VMs only |

RBAC is enforced server-side on every endpoint (ownership-scoped queries, per-field edit permissions) — the frontend's role checks are for navigation/UX only.

**Authentication & security**
- JWT auth backed by server-side sessions, so logout and idle-timeout actually revoke access instead of waiting out the token's natural expiry
- Configurable idle-session timeout (default 30 min, admin-adjustable) with an in-app warning before expiry
- Password policy (length + complexity) enforced on every password set
- Forced password reset on admin-created accounts, first login, and whenever an admin flags an existing account for reset — the user logs in with their current/temporary password as normal and is redirected straight to a reset page (current + new + confirm password), no separate reset code or email service involved
- Login access is a separate, admin-controlled toggle per user, off by default
- Brute-force lockout on login attempts (5 failures within a 15-minute window by default), keyed by account or by IP when the account is unknown
- Changing your own password revokes every other active session, so a compromised password can't keep a stray session alive after you change it
- Security response headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy) on every response

**Audit logging**
- Every significant action is logged: login/logout, session timeout, password changes/resets, user account changes (including deletion), VM metadata edits, VM decommissioning, DB backup/restore attempts, and permission-denied attempts
- Admin-only Audit Log page with filters for date range, user, action type, and entity

**Sync engine**
- Retry/backoff via `tenacity`, dead-letter queue for records that fail validation, full `SyncRun` history with per-run validation reports
- Diff/load shared between both platform adapters — only meaningful field changes are recorded, decommissioning is detected (not deleted) when a VM disappears from a source
- Manual sync trigger and dead-letter resolution from the Sync Health page

**Admin**
- Users: create/update, role assignment, login-allowed toggle, force a password reset on next login, and a VM Count column (click through to that user's VMs) — via a slide-in panel, not an inline form
- **Delete a user** (admin only, can't delete yourself or the last remaining admin) — any VM they owned has its owner cleared in the same transaction, with a per-VM audit entry recording the previous owner's name and a top-level audit-log entry for the deletion itself
- CSV export of every active VM with full metadata (ownership, department, environment, OS detail, IP address, applications, tags, notes)
- Source system connectors: credentials configured via Settings (encrypted at rest), enable/disable from Admin

**Metadata** (Admin and Global Editor full access; Global Viewer read-only)
- Departments, Applications, Environments, Tags — each a managed lookup with a VM Count column, click-through to a filtered VM list, create, and delete (blocked with the affected VM list shown if anything still uses that entry). Global Viewer sees the same lists and click-through but no create/delete controls — enforced server-side, not just hidden in the UI
- **Users** — read-only list of every user who currently owns at least one VM (username, full name, email, department, VM Count with click-through); account management itself (create/edit/role/delete) stays on Admin → Users, and Global Editor/Global Viewer only ever get this trimmed-down field set, never the full admin user record

**Database Backup & Restore** (Settings → Database Backup, admin only)
- Full PostgreSQL backups via `pg_dump` (custom/compressed format) — a true native-tool backup, not a hand-rolled export
- Scheduled automatic backups (configurable interval + retention count) or one-off "Backup now"
- Backups are written to a host-mounted `./backup` folder, so they survive container recreation and can be copied to another machine
- Restore from any listed backup, or upload a `.dump` file from elsewhere — restore requires typing the filename to confirm, and runs as a single transaction so a failed restore leaves the existing database untouched
- Every backup/restore attempt (success or failure) is written to the Audit Log

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
- Start the FastAPI server — internal only; reachable through the frontend's Nginx proxy at `/api/`, not published directly (closes off an X-Forwarded-For spoofing vector — see "Docker Compose notes" below)
- Start the sync scheduler (runs every 4 hours automatically)
- Build and serve the React UI on **port 80**

On first boot, `seed.py` generates a random password for the `admin` account and prints it once to the
`api` container's logs — there's no fixed default to guess or ship. Retrieve it with:

```bash
docker compose logs api | grep "Generated password"
```

Open http://localhost and log in with `admin` / that password (or `DEFAULT_ADMIN_USERNAME` /
`DEFAULT_ADMIN_PASSWORD` if you set them in `.env` — see below).
**Change the admin password immediately** via Admin → Users.

### Optional: override before first boot

A single `.env` at the repo root (not inside `backend/`) covers both the Docker Compose flow and local
development. Copy the template if you want to set anything before starting:

```bash
cp .env.example .env
# then edit .env
```

**Not** configured via `.env`: VMware/Nutanix connector credentials and sync-engine tuning (page size, retry
policy, sync interval) are admin-only, set exclusively via **Admin → Settings** in the UI after first login —
there's deliberately no environment-variable path for these, so there's exactly one place to manage them.

### Configuration reference

`.env.example` keeps its comments short and points here for the reasoning behind each variable.

**App**
- `APP_ENV` (`development`\|`production`) — affects log formatting only.
- `LOG_LEVEL` — structlog level.
- `CORS_ORIGINS` — comma-separated list of origins allowed to call the API.

**Database**
- `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` — only take effect on the *first* `docker-compose up` against a fresh volume. Postgres applies `POSTGRES_PASSWORD` only when initializing a brand-new data volume; changing it later requires running `ALTER ROLE ... WITH PASSWORD` inside the `db` container yourself, or `api`/`scheduler` will fail to authenticate.
- `DATABASE_URL` — only read when running the backend directly (no Docker); see [Local Development](#local-development-without-docker). Docker Compose ignores it and always assembles its own connection string from the `POSTGRES_*` values above.

**Session / JWT**
- `SECRET_KEY` — JWT signing key, and the encryption key for connector passwords stored in the database. Defaults to an insecure placeholder; set a real one (`openssl rand -hex 32`) before exposing this beyond localhost. Changing it after connectors are already configured breaks decryption of their stored passwords — you'd need to re-enter them via Settings.
- `ALGORITHM` — JWT signing algorithm.
- `ACCESS_TOKEN_EXPIRE_MINUTES` — JWT lifetime (minutes); the session is also revocable server-side before this via logout/idle-timeout, so this is just the outer cap.
- `SESSION_IDLE_TIMEOUT_MINUTES` — idle timeout (minutes) before a session is force-revoked. Also admin-adjustable at runtime via Settings → General; this env var is only the fallback default used until an admin saves a value there.

**Default admin account**
- `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` — the account seeded once by `seed.py` on first boot (skipped if the username already exists, so it's safe to leave these as-is on every subsequent restart). Leave `DEFAULT_ADMIN_PASSWORD` blank to auto-generate one (logged once, see above) or set it to pin a specific password. Change it via Admin → Users after logging in regardless.

**DB Backup & Restore**
- `BACKUP_DIR` — Docker-only default is `/app/backups`, the path `docker-compose.yml` bind-mounts to `./backup` on the host. Only set this if running outside Docker, pointed at a real local folder.

**Image tag** (registry-pull deploys only)
- `IMAGE_TAG` — pin a release, e.g. `IMAGE_TAG=v1.3.0`. Defaults to `latest`.

---

## Deploying prebuilt images

Every push of a `vX.Y.Z` tag builds and publishes two images to GHCR via
[`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml):
`ghcr.io/dipakchaulagain/infratrace-backend` (shared by the `api` and `scheduler` services, which differ
only in their startup command) and `ghcr.io/dipakchaulagain/infratrace-frontend`. `docker-compose.yml`
references both by name, so a deploy target needs only `docker-compose.yml` and `.env` — no source
checkout or local build:

```bash
# one-time: only needed if the GHCR packages are private
docker login ghcr.io -u <github-username>

cp .env.example .env
# edit .env — set POSTGRES_PASSWORD, SECRET_KEY, etc.; leave DEFAULT_ADMIN_PASSWORD
# blank to get a generated one, or optionally pin IMAGE_TAG to a specific release

docker compose pull
docker compose up -d
docker compose logs api | grep "Generated password"
```

Omit `IMAGE_TAG` in `.env` to track `latest`, or set it (e.g. `IMAGE_TAG=v1.3.0`) to pin a specific
release for a reproducible deploy.

To build from source instead of pulling from GHCR — e.g. right after cloning the repo — use
`docker-compose.build.yml` on its own; it's a standalone file (same `db`/`api`/`scheduler`/`frontend`
services as `docker-compose.yml`, just with `build:` for `api`/`scheduler` from `./backend` and
`frontend` from `./frontend`, tagged `infratrace-backend:local` / `infratrace-frontend:local` so they
don't collide with the GHCR image names):

```bash
cp .env.example .env
# edit .env — same variables as above

docker compose -f docker-compose.build.yml up -d --build
```

### Docker Compose notes

- **Log rotation** — every service uses the `json-file` driver capped at `10m` × `5` files, since Docker's default keeps logs forever and can fill the disk on a long-running host.
- **`api` has no published port** — the frontend's Nginx already proxies `/api/` (including `/api/docs`) to the `api` container over the internal Docker network (see `frontend/nginx.conf`). Publishing port 8000 directly would let traffic bypass Nginx entirely, which matters because `deps.py` trusts the `X-Forwarded-For` header set by that proxy — a client hitting the `api` container straight could otherwise spoof its own IP into the audit log / session records.
- **`scheduler` waits on `api`'s healthcheck, not just `db`'s** — instead of also running `alembic upgrade head` in `scheduler`, it waits for `api`'s healthcheck (only reachable after `api`'s own startup command finishes migrations). Running migrations from both services concurrently on a fresh boot raced and could crash whichever container lost.
- **`scheduler`'s `SECRET_KEY` must match `api`'s exactly** — it's used to decrypt connector passwords that `api` encrypted when they were saved via Admin → Settings. A mismatch silently breaks sync auth.
- **`postgres_data` volume has a fixed name** (`infratrace_postgres_data`) rather than the Compose-project-derived default, so it doesn't depend on the project's `name:` staying the same across renames.

---

## Local Development (without Docker)

Prefer Docker? Build from source with Compose instead of the manual venv/npm setup below:
`docker compose -f docker-compose.build.yml up -d --build` (see
[Deploying prebuilt images](#deploying-prebuilt-images) above). The rest of this section runs each
service directly on the host, without Docker.

### Backend

```bash
# From the repo root — same .env file the Docker Compose flow uses:
cp .env.example .env
# then edit .env and uncomment DATABASE_URL, pointed at localhost (Docker
# Compose assembles its own from POSTGRES_*, but running the backend
# directly needs an explicit connection string)

cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# or: source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

# Start PostgreSQL separately (or use Docker for just the DB):
docker run -d --name infratrace-db -p 5432:5432 \
  -e POSTGRES_DB=infratrace -e POSTGRES_USER=infratrace_app -e POSTGRES_PASSWORD=changeme \
  postgres:16

alembic upgrade head
python seed.py
uvicorn app.main:app --reload
```

`config.py` resolves `.env` relative to its own location (the repo root), not the current working
directory — so this works whether you launch `uvicorn` from `backend/` or anywhere else.

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
│   │   ├── backup.py      # pg_dump/pg_restore wrappers for DB Backup & Restore
│   │   ├── config.py      # Settings (pydantic-settings, reads from .env)
│   │   ├── database.py    # Engine + session factory
│   │   └── main.py        # FastAPI app + CORS + router registration
│   ├── alembic/           # DB migrations
│   ├── scheduler.py       # Sync scheduler (runs adapters on interval)
│   ├── seed.py            # Initial data seed
│   ├── wait_for_db.py     # DB startup wait helper
│   └── requirements.txt
├── frontend/
│   ├── public/             # icon.png (favicon/sidebar), login-logo.png (Login/ResetRequired)
│   ├── src/
│   │   ├── components/    # Sidebar, Layout, Drawer, StatCard, Pagination, SessionTimeoutWarning, Toast,
│   │   │                  # MetadataEntityManager (shared create/delete/count/click-through for
│   │   │                  # Departments/Applications/Environments/Tags), etc.
│   │   ├── pages/         # Dashboard, VMs, VMDetail, DecommissionedVMs, Hosts, Networks,
│   │   │                  # SyncHealth, Settings, Admin, Metadata, AuditLog, Login, ResetRequired
│   │   ├── lib/           # api.ts (axios client), auth.tsx (auth context), permissions.ts (RBAC matrix), utils.ts
│   │   └── App.tsx        # Router + auth/role guards
│   ├── tailwind.config.js
│   └── Dockerfile
├── docker-compose.yml
├── backup/                 # DB backups (bind-mounted, not tracked in git) — see Database Backup & Restore
├── docs/                   # Project plan, design spec, deployment guide (not tracked in git)
└── Prototype script/       # Phase 1 prototype scripts, reference only (not tracked in git)
```

---

## Layer A / Layer B separation

The sync engine writes **only** Layer A (infrastructure facts):
`vms_current`, `hosts_current`, `clusters_current`, `networks_current`, `sync_runs`, `vm_history`, `dead_letter_records`

Ownership and application data lives **only** in Layer B:
`vm_metadata`, `vm_metadata_audit`, `departments`, `environments`, `applications`, `vm_applications`, `tags`, `taggings`, `users`, `user_sessions`, `access_logs`

The sync engine's DB role has zero grants on Layer B tables — enforced at the database permission level, not just in code.

---

## API Reference

Interactive docs at `/api/docs` (Swagger UI) once the backend is running. All routes below are prefixed with `/api`.

`GET /api/health` — unauthenticated liveness check (also what Docker's healthcheck polls).

**Auth** (`/auth`)
| Method | Path | Description |
|---|---|---|
| POST | `/auth/token` | Login, returns JWT bound to a server-side session |
| POST | `/auth/logout` | Revoke the current session |
| POST | `/auth/change-password` | Change your own password (also completes a forced reset — first login or admin-triggered) |
| GET | `/auth/me` | Current user profile |

**VMs** (`/vms`)
| Method | Path | Description |
|---|---|---|
| GET | `/vms` | List VMs — filterable, sortable, paginated; owner-scoped for User/Viewer roles |
| GET | `/vms/decommissioned` | List decommissioned VMs (admin / global editor only) |
| GET | `/vms/export` | CSV-ready export of every active VM with full metadata (admin only) |
| GET | `/vms/summary` | Dashboard counts + chart data |
| GET | `/vms/{id}` | VM detail |
| PATCH | `/vms/{id}/metadata` | Update ownership/metadata (admin, global editor, or the owning user — field-level permissions apply) |
| PATCH | `/vms/bulk-metadata` | Apply the same metadata change(s) to up to 200 VMs at once — same field-level permissions and IP-Address exclusion as the single-VM endpoint; returns `{updated, skipped}`, skipping (not failing on) VMs that are gone or not owned by the caller |
| GET | `/vms/{id}/history` | Infrastructure change history |
| GET | `/vms/{id}/metadata-audit` | Ownership/metadata audit trail |

**Hosts / Networks**
| Method | Path | Description |
|---|---|---|
| GET | `/hosts` | List hosts (admin / global editor only) |
| GET | `/networks` | List networks/VLANs with per-VLAN VM counts (admin / global editor only) |

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
| GET/POST | `/admin/departments` | List (with VM counts, any authenticated role) / create departments (admin / global editor) |
| DELETE | `/admin/departments/{id}` | Delete a department (admin / global editor) — blocked (400, with the affected VM list) if any VM still uses it |
| GET/POST | `/admin/environments` | List (with VM counts, any authenticated role) / create environments (admin / global editor) |
| DELETE | `/admin/environments/{id}` | Delete an environment (admin / global editor) — blocked if still in use |
| GET/POST | `/admin/applications` | List (with VM counts, any authenticated role) / create applications (admin / global editor) |
| DELETE | `/admin/applications/{id}` | Delete an application (admin / global editor) — blocked if still in use |
| GET/POST | `/admin/tags` | List (with VM counts, any authenticated role) / create tags (admin / global editor) |
| DELETE | `/admin/tags/{id}` | Delete a tag (admin / global editor) — blocked if still in use |
| GET | `/admin/users` | List users with each user's owned-VM count — admin gets the full account record (role, active, login-allowed, etc.); global editor / global viewer get a trimmed username/full name/email/department/VM-count view only, for the Metadata → Users cross-reference |
| GET | `/admin/users/lookup` | Minimal id+name list for owner pickers (admin / global editor) |
| POST | `/admin/users` | Create a user (admin only) |
| PATCH | `/admin/users/{id}` | Update a user — role, department, login-allowed, forced-reset flag, active (admin only) |
| DELETE | `/admin/users/{id}` | Delete a user (admin only; not yourself, not the last remaining admin) — clears ownership on any VMs they owned |
| GET | `/admin/users/{id}/owned-vms` | VMs owned by this user — used to preview impact before deleting |
| POST | `/admin/users/{id}/trigger-reset` | Force a password reset on this user's next login (admin only) |
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
| PUT | `/settings/backup` | Backup schedule: enabled, interval, retention count |
| POST | `/settings/backup/run` | Trigger a full DB backup immediately |
| GET | `/settings/backup/download/{filename}` | Download a backup file |
| POST | `/settings/backup/upload` | Upload a backup file (e.g. from another machine) |
| POST | `/settings/backup/restore` | Restore the database from a backup file — replaces all current data |

---

## Database Backup & Restore

Full PostgreSQL backups via `pg_dump`/`pg_restore` (the native tools, custom/compressed format) — not a
hand-rolled export — so a backup is a true full-fidelity copy and restore is reliable.

### Where backups live

`docker-compose.yml` bind-mounts `./backup` (a folder in the project root, next to this README) into both
the `api` and `scheduler` containers at `/app/backups`. Because it's a bind mount rather than a named Docker
volume, it's a plain host folder — it survives `docker-compose down`/`up`, container rebuilds, and image
upgrades, and can be copied or synced anywhere.

Files are named `backup_<db-name>_<YYYYMMDD_HHMMSS>.dump`, e.g. `backup_infratrace_20260802_084519.dump`.

### Enabling scheduled backups

**Settings → Database Backup**:
- **Enable scheduled backups** — off by default
- **Backup interval (minutes)** — how often the scheduler container takes a backup (default 1440 = daily; changes take effect within 30 seconds, same polling loop the sync engine uses)
- **Retention (backups to keep)** — oldest backups beyond this count are deleted automatically after every run (default 10)
- **Backup now** — trigger an on-demand backup immediately, independent of the schedule

`pg_dump` takes a consistent snapshot in a single transaction — it never blocks or locks the live database
against concurrent reads/writes.

### Restoring

From **Settings → Database Backup**, click the restore icon next to any listed backup (or upload a `.dump`
file first — it appears in the same list once uploaded). You must type the exact filename to confirm before
the restore runs, since **this replaces all current data**. The restore itself runs as a single transaction
(`pg_restore --single-transaction --clean --if-exists`): if anything fails partway through, Postgres rolls
back the entire restore and the existing database is left exactly as it was — never a partial or broken
state. Every attempt (success or failure) is recorded in the Audit Log.

After a successful restore, sessions created after the backup was taken no longer exist in the restored
data — you may need to sign in again.

### Cross-machine recovery

Since backups are just files in `./backup`, moving one to a different machine and restoring it there works
the same way it would locally:

1. On the new machine, clone this repo and copy the backup file into `./backup` (create the folder first if
   `docker-compose` hasn't been run yet).
2. Start the stack: `docker-compose up -d`. Since the database is fresh, migrations run and it seeds the
   default `admin` / `admin` account — this is expected; the restore in the next step replaces it anyway.
3. Log in, go to **Settings → Database Backup** — the copied-in file appears in the list automatically (no
   upload needed, since it's already in the mounted folder).
4. Click restore, type the filename to confirm.

Restoring an old backup rolls the schema back to whatever it was when that backup was taken — pair a backup
with the matching app version (git tag/commit) for a clean recovery rather than mixing an old backup with a
newer app build expecting newer tables/columns.

---

## Credentials setup (production)

- Use a **read-only** vCenter role with `System.View` / `System.Read` only
- Use the **Viewer** role in Nutanix Prism Element
- Configure connectors via **Admin → Settings** in the UI — the only way to set them. Credentials are encrypted with `SECRET_KEY` and stored in the database; there's no plaintext credential file to manage or rotate
- Generate a strong `SECRET_KEY`: `openssl rand -hex 32` — store it via Docker secrets, Kubernetes Secrets, or your cloud provider's secrets manager in production, not a plain `.env` file
- Change `DEFAULT_ADMIN_PASSWORD` (or just change the admin password via Admin → Users after first login) before exposing this beyond localhost
