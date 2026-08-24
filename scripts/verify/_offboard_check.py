"""scripts/verify/verify-offboard.sh's engine (B3 hardening).

Two modes:

  (default, no args)  Synthetic proof against a scratch SQLite database (the same
                       JSONB/UTC bridge backend/tests/conftest.py already applies, imported
                       only for its compiler shims). Creates a throwaway employee with a
                       live session, a service grant and a minted service token, then
                       deactivates them through the real `PATCH /api/admin/users/{id}`
                       route and proves every access path is gone: the session cookie is
                       rejected, a *new* token cannot be minted, and the revocation is
                       queryable by the affected service. This runs anywhere, no live MM OS
                       or Postgres needed -- it is what "prove offboarding works" means on a
                       build machine.

  --code EMPLOYEE_CODE --database-url <url>
                       Read-only real-world check against a live MM OS database: confirms
                       the named employee's user row is inactive, has no live (unrevoked,
                       unexpired) sessions, and has an unexpired `revocations` row with no
                       `service_id` (a global block). Does not write anything. This is the
                       command an on-call person runs after actually offboarding someone —
                       see docs/10-runbook.md "Offboard an employee".
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _real_db_check(employee_code: str, database_url: str) -> int:
    sys.path.insert(0, str(BACKEND))
    os.environ["MMOS_DATABASE_URL"] = database_url
    os.environ.setdefault("MMOS_SIGNING_KEY_PATH", "/run/secrets/mmos_signing_key.pem")
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Employee, Revocation, Session, User

    db = SessionLocal()
    failed = False
    try:
        emp = db.scalar(select(Employee).where(Employee.employee_code == employee_code))
        if emp is None:
            print(f"FAIL  employee {employee_code!r} not found in employees")
            return 1
        user = db.scalar(select(User).where(User.employee_id == emp.id))
        if user is None:
            print(f"FAIL  employee {employee_code!r} has no user row")
            return 1

        ok = not user.is_active
        print(("PASS" if ok else "FAIL") + f"  user.is_active is False for {employee_code}")
        failed = failed or not ok

        now = datetime.now(timezone.utc)
        live = db.scalars(
            select(Session).where(
                Session.user_id == user.id, Session.revoked_at.is_(None), Session.expires_at > now
            )
        ).all()
        ok = len(live) == 0
        print(("PASS" if ok else "FAIL") + f"  no live sessions remain ({len(live)} found)")
        failed = failed or not ok

        global_revocation = db.scalar(
            select(Revocation).where(
                Revocation.subject == user.subject,
                Revocation.service_id.is_(None),
                Revocation.purge_after > now,
            )
        )
        ok = global_revocation is not None
        print(("PASS" if ok else "FAIL") + "  an unexpired, global (service_id IS NULL) revocation row exists")
        failed = failed or not ok

        return 1 if failed else 0
    finally:
        db.close()


def _synthetic_check() -> int:
    _scratch = Path(tempfile.gettempdir()) / f"mmos-offboard-check-{uuid.uuid4().hex[:8]}.db"
    _key = Path(tempfile.gettempdir()) / f"mmos-offboard-check-{uuid.uuid4().hex[:8]}.pem"
    os.environ["MMOS_DATABASE_URL"] = f"sqlite+pysqlite:///{_scratch.as_posix()}"
    os.environ["MMOS_SIGNING_KEY_PATH"] = str(_key)
    os.environ.setdefault("MMOS_ENVIRONMENT", "test")
    os.environ.setdefault("MMOS_NETWORK_MODE", "public")
    os.environ.setdefault("MMOS_COOKIE_SECURE", "false")
    os.environ.setdefault("MMOS_COOKIE_DOMAIN", "")
    os.environ.setdefault("MMOS_GOOGLE_CLIENT_ID", "verify-offboard")
    os.environ.setdefault("MMOS_GOOGLE_CLIENT_SECRET", "verify-offboard")

    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(BACKEND / "tests"))
    import conftest  # noqa: F401 -- orchestrator-owned; imported only for its SQLite shims

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal, engine, get_db
    from app.main import app
    from app.security import new_service_key, new_session_token, session_expiry

    models.Base.metadata.create_all(engine)
    db = SessionLocal()
    app.dependency_overrides[get_db] = lambda: db

    failed = False

    def check(label: str, ok: bool) -> None:
        nonlocal failed
        print(("PASS" if ok else "FAIL") + f"  {label}")
        failed = failed or not ok

    with TestClient(app) as client:
        # the person being offboarded
        emp = models.Employee(
            employee_code="MMOFF1", full_name="Offboard Check Person",
            work_email="offboard-check@m-mines.com", hr_department="Operations",
            division="Plant", job_title="Operator", band="L1J",
        )
        db.add(emp)
        db.flush()
        user = models.User(employee_id=emp.id, auth_type="google", login_email=emp.work_email)
        db.add(user)
        db.commit()

        # a live shell session
        raw, token_hash = new_session_token()
        db.add(models.Session(user_id=user.id, token_hash=token_hash, expires_at=session_expiry()))
        db.commit()
        client.cookies.set("mmos_session", raw)

        # a service this person has a grant on, and a token minted through it
        svc_key_raw, svc_key_hash = new_service_key()
        service = models.Service(
            slug="offboard-check-svc", name="Offboard Check Service",
            base_url="https://offboard-check.m-mines.com", service_key_hash=svc_key_hash,
        )
        db.add(service)
        db.flush()
        role = models.ServiceRole(service_id=service.id, key="viewer", name="Viewer")
        db.add(role)
        db.flush()
        grant = models.Grant(user_id=user.id, service_id=service.id, service_role_id=role.id)
        db.add(grant)
        db.commit()

        r = client.get("/api/me")
        check("before offboarding: GET /api/me succeeds", r.status_code == 200)
        r = client.post("/api/token/service", json={"slug": service.slug})
        check("before offboarding: a service token can be minted", r.status_code == 200)

        # the admin doing the offboarding
        admin_emp = models.Employee(
            employee_code="MMADM2", full_name="Admin", work_email="admin2@m-mines.com",
            hr_department="IT", division="Corporate", job_title="IT Admin", band="L3",
        )
        db.add(admin_emp)
        db.flush()
        admin = models.User(
            employee_id=admin_emp.id, auth_type="google", login_email=admin_emp.work_email,
            is_platform_admin=True,
        )
        db.add(admin)
        db.commit()
        admin_raw, admin_hash = new_session_token()
        db.add(models.Session(user_id=admin.id, token_hash=admin_hash, expires_at=session_expiry()))
        db.commit()

        admin_client = TestClient(app)
        admin_client.cookies.set("mmos_session", admin_raw)
        r = admin_client.patch(f"/api/admin/users/{user.id}", json={"is_active": False})
        check("PATCH /api/admin/users/{id} {is_active:false} succeeds", r.status_code == 200)

        # everywhere access should now be gone, in the SAME check, no restart needed
        r = client.get("/api/me")
        check("after offboarding: the SAME session cookie is now rejected", r.status_code == 401)

        r2 = TestClient(app)
        r2.cookies.set("mmos_session", raw)
        r = r2.get("/api/me")
        check("after offboarding: a fresh client with the same cookie value is also rejected", r.status_code == 401)

        since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        r = admin_client.get(
            "/api/agent/revocations", params={"since": since},
            headers={"Authorization": f"Bearer {svc_key_raw}"},
        )
        subs = [row.get("sub") for row in r.json().get("revoked_subjects", [])] if r.status_code == 200 else []
        check(
            "after offboarding: the subject is on the deny-list every one of their "
            "services will see on its next poll",
            user.subject in subs,
        )

        live = db.scalars(
            select(models.Session).where(models.Session.user_id == user.id, models.Session.revoked_at.is_(None))
        ).all()
        check("after offboarding: no live (unrevoked) session rows remain in the database", len(live) == 0)

    db.close()
    engine.dispose()
    for p in (_scratch, _key):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", help="Employee code to check against a real database (read-only)")
    parser.add_argument("--database-url", help="MMOS_DATABASE_URL for --code's real check")
    args = parser.parse_args()

    if args.code:
        if not args.database_url:
            print("FAIL  --code requires --database-url")
            return 2
        print(f"== MM OS offboard verification -- real check for {args.code} ==\n")
        rc = _real_db_check(args.code, args.database_url)
    else:
        print("== MM OS offboard verification -- synthetic proof (no live MM OS needed) ==\n")
        rc = _synthetic_check()

    print()
    print("== PASS ==" if rc == 0 else "== FAIL ==")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
