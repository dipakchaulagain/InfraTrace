#!/usr/bin/env python3
"""
wait_for_db.py — Blocks until the DATABASE_URL is reachable, then exits 0.
Called by Docker entrypoint before alembic / uvicorn / scheduler.
Retries up to 30 times with a 2-second pause between attempts.
"""
import os
import sys
import time

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

for attempt in range(1, 31):
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        conn.close()
        print(f"Database ready (attempt {attempt})")
        sys.exit(0)
    except Exception as exc:
        print(f"Attempt {attempt}/30: {exc}")
        time.sleep(2)

print("ERROR: database did not become ready in time", file=sys.stderr)
sys.exit(1)
