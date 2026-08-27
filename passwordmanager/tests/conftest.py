"""Password Manager's own test harness — mirrors servicedesk/tests/conftest.py's shape.
Not shared with any other service's conftest.

Environment variables are set *before* importing anything under `app.*`, because
`app/config.py`'s `settings()` is `lru_cache`d.
"""
from __future__ import annotations

import os

os.environ["ENVIRONMENT"] = "development"
os.environ["AUTH_MODE"] = "stub"
os.environ["DEV_SECRET"] = "test-secret"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mmos_seam import clear_revocations, make_dev_token


@pytest.fixture(autouse=True)
def _clean_state():
    clear_revocations()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


PERSON = dict(
    sub="user:dev-local", emp="DEV-0", name="Local Dev User", email=None,
    dept="Information Technology", division="Corporate", band="L1", approval_level=None,
)


def token_for(roles: list[str] | None = None, **overrides) -> str:
    person = dict(PERSON)
    person.update(overrides)
    claims = {
        "sub": person["sub"], "emp": person["emp"], "name": person["name"], "email": person["email"],
        "dept": person["dept"], "division": person["division"], "band": person["band"],
        "approval_level": person["approval_level"], "roles": roles or ["employee"], "platform_admin": False,
    }
    return make_dev_token(claims)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
