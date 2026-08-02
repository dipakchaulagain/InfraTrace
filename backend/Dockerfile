FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by psycopg2, plus PostgreSQL 16 client tools
# (pg_dump/pg_restore) for the DB Backup & Restore feature — pinned to
# match the postgres:16 server image exactly via the official PGDG repo.
# Debian's own default repo only ships client 17, and pg_dump 17's archives
# embed a SET transaction_timeout = ... preamble (a PG17-only GUC) that a
# PG16 server rejects outright on restore — a real, not theoretical,
# version-skew failure, so "newer client is fine against an older server"
# does not hold here and the exact major version must match.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl ca-certificates gnupg && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /etc/apt/trusted.gpg.d/pgdg.asc && \
    echo "deb [signed-by=/etc/apt/trusted.gpg.d/pgdg.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 && \
    apt-get purge -y --auto-remove curl gnupg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the API server. Override CMD for the scheduler container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
