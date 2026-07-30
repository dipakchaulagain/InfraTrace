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
from app.models.inventory import SourceSystem
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
        if not db.query(User).filter_by(username="admin").first():
            db.add(User(
                username="admin",
                email="admin@infratrace.local",
                hashed_password=get_password_hash("admin"),
                role="admin",
                active=True,
            ))
            print("  Admin user created: admin / admin  ← CHANGE THIS PASSWORD")
        else:
            print("  Admin user already exists, skipped")

        # ---- Source systems (from .env if set) ----
        vcenter_host = settings.VCENTER_HOST
        if vcenter_host:
            url = f"https://{vcenter_host}:{settings.VCENTER_PORT}"
            if not db.query(SourceSystem).filter_by(platform="vmware", base_url=url).first():
                db.add(SourceSystem(
                    platform="vmware",
                    display_name=f"vCenter — {vcenter_host}",
                    base_url=url,
                    is_active=True,
                ))
                print(f"  VMware source system seeded: {url}")
            else:
                print(f"  VMware source already exists, skipped")

        nutanix_url = settings.NUTANIX_BASE_URL
        if nutanix_url:
            if not db.query(SourceSystem).filter_by(platform="nutanix", base_url=nutanix_url).first():
                db.add(SourceSystem(
                    platform="nutanix",
                    display_name=f"Prism Element — {nutanix_url.split('//')[1].split(':')[0]}",
                    base_url=nutanix_url,
                    is_active=True,
                ))
                print(f"  Nutanix source system seeded: {nutanix_url}")
            else:
                print(f"  Nutanix source already exists, skipped")

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
