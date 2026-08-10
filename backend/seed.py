#!/usr/bin/env python3
"""
seed.py — Bootstrap the database with initial lookup data and a default admin user.

Run once after `alembic upgrade head`:
    python3 seed.py

Safe to re-run — all inserts are idempotent (checks before inserting).
"""
import os
import sys

# Ensure the backend package is on the path when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.metadata import Department, Environment, User
from app.api.auth import get_password_hash
from app.config import settings


def seed():
    db = SessionLocal()
    try:
        # ---- Departments ----
        departments = [
            "Application",
            "Systems",
            "Accounts",
            "Network",
            "Security",
            "Infrastructure",
        ]
        for name in departments:
            if not db.query(Department).filter_by(name=name).first():
                db.add(Department(name=name))
        print(f"  Departments: {len(departments)} seeded")

        # ---- Environments ----
        environments = ["Production", "UAT", "Testing", "POC", "Development"]
        for name in environments:
            if not db.query(Environment).filter_by(name=name).first():
                db.add(Environment(name=name))
        print(f"  Environments: {len(environments)} seeded")

        db.flush()

        # ---- Default admin user ----
        # VMware/Nutanix connectors are intentionally NOT seeded from .env —
        # configure them via Admin -> Settings after logging in.
        if not db.query(User).filter_by(username=settings.DEFAULT_ADMIN_USERNAME).first():
            db.add(User(
                username=settings.DEFAULT_ADMIN_USERNAME,
                email=settings.DEFAULT_ADMIN_EMAIL,
                hashed_password=get_password_hash(settings.DEFAULT_ADMIN_PASSWORD),
                role="admin",
                active=True,
                # login_allowed defaults to False at the model level (admin
                # must grant it to accounts created via the UI) — but this is
                # the bootstrap account itself, so it must be able to log in
                # or a fresh deploy has no way to grant that flag to anyone.
                login_allowed=True,
            ))
            print(f"  Admin user created: {settings.DEFAULT_ADMIN_USERNAME} / <DEFAULT_ADMIN_PASSWORD>  ← CHANGE THIS PASSWORD")
        else:
            print("  Admin user already exists, skipped")

        db.commit()
        print("\nSeed complete.")

    except Exception as exc:
        db.rollback()
        print(f"Seed failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding database ...")
    seed()
