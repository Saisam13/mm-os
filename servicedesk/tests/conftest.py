"""Service Desk's own test harness. Deliberately not shared with `backend/tests/conftest.py`
— that file is MM OS's, frozen and read-only to this agent (sprint amendment #4). This one
runs the same suite unchanged on SQLite (here) and Postgres (production) because
app/models.py only uses portable SQLAlchemy types — no JSONB/UUID shim needed.

Environment variables are set *before* importing anything under `app.*`, because
`app/config.py`'s `settings()` is `lru_cache`d and `app/db.py` builds its engine at import
time from it.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp_db = Path(tempfile.gettempdir()) / "servicedesk_test.db"
if _tmp_db.exists():
    _tmp_db.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db}"
os.environ["AUTH_MODE"] = "stub"
os.environ["ORG_CHART_MODE"] = "seed"
os.environ["DEV_SECRET"] = "test-secret"
os.environ["NOTIFICATIONS_ENABLED"] = "false"
os.environ["MMOS_SERVICE_KEY"] = ""  # keeps the heartbeat loop a no-op in tests

import pytest
from fastapi.testclient import TestClient

from app import notifications
from app.db import SessionLocal, engine
from app.main import app
from app.mmos_seam import clear_revocations, make_dev_token
from app.models import Base
from app.org_chart import default_seed, set_org_chart_client


@pytest.fixture(autouse=True)
def _clean_state():
    """Fresh schema, fresh org chart fixture, fresh revocation/notification state — every
    test starts from nothing so ref numbering, event history and approver escalation are
    each independently verifiable."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    set_org_chart_client(default_seed())
    clear_revocations()
    notifications.clear_failed_notifications()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ── people, matching app/org_chart.py's default_seed() so approver computation lines up ──
PEOPLE = {
    "operator": dict(sub="user:op-1", emp="MM19", name="P-Spoke Operator", email=None,
                     dept="P-Spoke", division="Production", band="NON L", approval_level="Operational"),
    "supervisor": dict(sub="user:sup-1", emp="MM05", name="P-Spoke Supervisor", email="supervisor@m-mines.com",
                        dept="P-Spoke", division="Production", band="L2", approval_level="Operational"),
    "hod": dict(sub="user:hod-1", emp="MM02", name="P-Spoke HOD", email="hod@m-mines.com",
                dept="P-Spoke", division="Production", band="L3", approval_level="L3 (HOD)"),
    "apex": dict(sub="user:apex-1", emp="MM01", name="Apex Approver", email="apex@m-mines.com",
                 dept="Corporate", division="Corporate", band="L5", approval_level="L5 (Apex)"),
}


def token_for(person_key: str, roles: list[str] | None = None, **overrides) -> str:
    person = dict(PEOPLE[person_key])
    person.update(overrides)
    claims = {
        "sub": person["sub"], "emp": person["emp"], "name": person["name"], "email": person["email"],
        "dept": person["dept"], "division": person["division"], "band": person["band"],
        "approval_level": person["approval_level"], "roles": roles or ["requester"], "platform_admin": False,
    }
    return make_dev_token(claims)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def custom_token(sub: str, dept: str, roles: list[str] | None = None, **kw) -> str:
    claims = {
        "sub": sub, "emp": kw.get("emp", "MM99"), "name": kw.get("name", "Someone"),
        "email": kw.get("email"), "dept": dept, "division": kw.get("division", dept),
        "band": kw.get("band", "L1"), "approval_level": kw.get("approval_level"),
        "roles": roles or ["requester"], "platform_admin": False,
    }
    return make_dev_token(claims)
