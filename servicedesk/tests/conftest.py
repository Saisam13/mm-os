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
# Five real MiniMines employees (backend/app/demo_seed.py), keyed by employee code — see
# app/org_chart.py's SEED_PERSONAS docstring for why and the manager chain (MM88 -> MM81).
PEOPLE = {
    "MM88": dict(sub="user:MM88", emp="MM88", name="MAMATESH UDAY NAIK", email=None,
                 dept="Projects", division="Projects", band="L2", approval_level="L1 (Associate)"),
    "MM81": dict(sub="user:MM81", emp="MM81", name="Chandrashekhar Keshav Kalvit", email=None,
                 dept="Projects", division="Corporate", band="L4", approval_level="L4 (Div Head)"),
    "MM05": dict(sub="user:MM05", emp="MM05", name="Mandaleshvar Sharma", email=None,
                 dept="P-Spoke", division="Production", band="L4", approval_level="L3 (HOD)"),
    "MM33": dict(sub="user:MM33", emp="MM33", name="Hardhik Pendurthi", email=None,
                 dept="StratOps", division="Corporate", band="NON L", approval_level="Oversight"),
    "MM-ITADMIN": dict(sub="user:MM-ITADMIN", emp="MM-ITADMIN", name="IT Administrator",
                        email="itadmin@m-mines.com", dept="Information Technology",
                        division="Corporate", band="L3", approval_level=None),
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
