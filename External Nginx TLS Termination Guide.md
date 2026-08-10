# External Nginx TLS Termination Guide

How to put InfraTrace behind a host-level Nginx that terminates TLS/SSL for a
real domain name, instead of exposing the stack's own frontend container
directly on port 80.

Two variants are covered, depending on where the terminating Nginx itself
runs:

- **Option A — host Nginx.** Nginx runs directly on the host (or a separate
  edge/LB host), and reaches the `frontend` container via its published port.
- **Option B — dockerized Nginx.** Nginx runs as its own container, joined to
  a shared Docker network so it can reach `frontend` by service name instead
  of a published host port.

Either way, the `frontend` container keeps doing what it already does today:
serve the SPA and proxy `/api/` to the `api` container over the internal
Docker network. TLS is terminated once, at the edge Nginx; everything behind
it stays plain HTTP, unchanged from the default setup.

```
Option A:
Internet (443, TLS)
      │
      ▼
Host Nginx  ──HTTP──▶  frontend container (port 80)  ──HTTP──▶  api container (port 8000)
(cert here)             (Docker, published on               (Docker, internal only)
                         127.0.0.1:80 only)

Option B:
Internet (443, TLS)
      │
      ▼
Nginx container  ──HTTP──▶  frontend container (port 80)  ──HTTP──▶  api container (port 8000)
(cert mounted in,          (Docker, no published port —
 joined to nginx-network)   reached via nginx-network by
                            service name "frontend")
```

---

## 1. Prerequisites

- A domain name (or subdomain) with an A/AAAA record pointing at this host's
  public IP.
- Ports 80 and 443 open inbound on this host's firewall.
- Nginx installed on the host (not the one in the `frontend` container):
  ```bash
  sudo apt update && sudo apt install -y nginx
  ```
- `docker compose` stack already runnable on this host (see the main
  [README](../README.md) for first-boot steps).

---

## 2. Stop exposing the frontend container publicly

By default `docker-compose.yml` publishes the frontend on `80:80`, i.e. every
interface on the host. Once an edge Nginx is the public entry point, nothing
else should be able to reach the container directly.

### Option A — host Nginx

The host Nginx reaches the container over `127.0.0.1`, so restrict the
published port to loopback only. Edit the `frontend` service's `ports:` in
`docker-compose.yml`:

```yaml
  frontend:
    ...
    ports:
      - "127.0.0.1:80:80"
```

Apply it:

```bash
docker compose up -d
```

If Nginx instead runs on a *separate* edge host rather than this one, skip
this and use your firewall to restrict port 80 on this host to only that
edge host's IP, since `127.0.0.1` wouldn't be reachable from it.

### Option B — dockerized Nginx on a shared network

If the terminating Nginx also runs as a container, it's simpler and more
secure to skip publishing a host port entirely and instead put both
containers on a shared user-defined Docker network — Nginx then reaches the
frontend by its Compose service name (`frontend`), using Docker's built-in
DNS, and the frontend is never exposed on the host at all.

Create the shared network once (it's not owned by either compose project, so
it survives `docker compose down` on both sides):

```bash
docker network create nginx-network
```

In `docker-compose.yml`, declare it as external and attach the `frontend`
service to it *in addition to* the default network (needed so it can still
reach `api`/`db`), and drop its `ports:` mapping:

```yaml
services:
  frontend:
    ...
    # no ports: — only reachable via nginx-network now
    networks:
      - default
      - nginx-network

networks:
  nginx-network:
    external: true
```

Apply it:

```bash
docker compose up -d
```

Then join your Nginx container (or its own compose file) to the same
network, e.g. for a standalone container:

```bash
docker run -d --name edge-nginx \
  --network nginx-network \
  -p 80:80 -p 443:443 \
  -v /etc/nginx/sites-available/vims.example.com:/etc/nginx/conf.d/vims.conf:ro \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  nginx:alpine
```

or, if it's itself a Compose service, add the same `networks:` entries shown
above to that service too. Either way, the config in step 5 changes only
its `proxy_pass` target, from `http://127.0.0.1:80` to `http://frontend:80`
— Docker's embedded DNS resolves the service name for any container attached
to `nginx-network`.

Certificates in this option still come from Certbot running on the host
(step 4) — only the mount path changes, from a native Nginx `include` to the
`-v /etc/letsencrypt:/etc/letsencrypt:ro` volume above. Renewal (step 7)
still runs on the host; the container just needs a restart or reload to
pick up renewed files, since Certbot's own reload hook won't reach into a
container.

---

## 3. Point CORS_ORIGINS at the real domain

The API only accepts cross-origin requests from origins listed in
`CORS_ORIGINS`. Set it to the public HTTPS URL before going live — in the
project's `.env` (see `.env.example`):

```
CORS_ORIGINS=https://vims.example.com
```

Then recreate the `api` container so it picks up the change:

```bash
docker compose up -d api
```

(The frontend calls the API via a relative `/api` path, not an absolute URL,
so no frontend rebuild is needed for a domain change — this only affects
the backend's CORS check.)

---

## 4. Get a certificate (Let's Encrypt via Certbot)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot certonly --nginx -d vims.example.com
```

This obtains the certificate and stores it under
`/etc/letsencrypt/live/vims.example.com/` without yet touching your Nginx
config (the server block below references it explicitly, so `--nginx`'s
auto-edit isn't relied on).

Certbot installs a renewal timer automatically; verify it:

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

---

## 5. Nginx server block

Create `/etc/nginx/sites-available/vims.example.com`:

```nginx
# Plain HTTP — redirect everything to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name vims.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name vims.example.com;

    ssl_certificate     /etc/letsencrypt/live/vims.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vims.example.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Matches the frontend container's own limits for the backup
    # download/upload/restore endpoints (see settings/backup routes) —
    # this proxy sits in front of that one, so both need to allow it.
    client_max_body_size 500m;
    proxy_read_timeout 300s;

    location / {
        proxy_pass http://127.0.0.1:80;
        # Option B (dockerized Nginx on nginx-network) instead:
        # proxy_pass http://frontend:80;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`X-Forwarded-For` is passed through using `$proxy_add_x_forwarded_for` (not
overwritten), and the frontend container's own Nginx does the same thing on
its hop to `api` — so `api`'s `get_client_ip()` (`backend/app/api/deps.py`)
still sees the real client IP as the first entry in the chain, not this
proxy's or the frontend container's address.

Enable the site and reload:

**Option A** (host Nginx):

```bash
sudo ln -s /etc/nginx/sites-available/vims.example.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**Option B** (dockerized Nginx): the file is already mounted straight into
`conf.d` by the `docker run` command in step 2, so there's no `sites-enabled`
symlink step — just validate and reload inside the container:

```bash
docker exec edge-nginx nginx -t
docker exec edge-nginx nginx -s reload
```

If Certbot's `options-ssl-nginx.conf` / `ssl-dhparams.pem` don't exist yet on
your system (they're created the first time Certbot edits an Nginx config),
either run `certbot --nginx` once to generate them, or drop the two
`include`/`ssl_dhparam` lines and rely on Nginx's own TLS defaults instead.

---

## 6. Verify

```bash
curl -I https://vims.example.com
curl https://vims.example.com/api/health
```

- Confirm the padlock/certificate in a browser and that plain `http://` now
  redirects to `https://`.
- Log in through the UI and confirm API calls succeed (check the browser
  network tab for `/api/...` requests returning 200, not CORS errors — a CORS
  error here almost always means step 3 was skipped or the domain doesn't
  match exactly, including scheme).

---

## 7. Renewal

Certbot's systemd timer renews automatically before expiry; the certificate
files are updated in place at the same path, so Nginx just needs a reload to
pick them up, which the Certbot package normally hooks in automatically. If
in doubt:

```bash
sudo certbot renew --dry-run
```

For Option B (dockerized Nginx), the host-side reload hook doesn't reach
into the container — add a renewal hook that restarts it instead:

```bash
sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\ndocker restart edge-nginx\n' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-edge-nginx.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-edge-nginx.sh
```
