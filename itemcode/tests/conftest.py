"""Item Code Studio's own test harness. Deliberately not shared with any other service's
conftest — each service's tests are isolated. Mirrors servicedesk/tests/conftest.py's
shape: runs on SQLite here, Postgres in production, unchanged app code either way.

Environment variables are set *before* importing anything under `app.*`, because
`app/config.py`'s `settings()` is `lru_cache`d and `app/db.py` builds its engine at import
time from it.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp_db = Path(tempfile.gettempdir()) / "itemcode_test.db"
if _tmp_db.exists():
    _tmp_db.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db}"
os.environ["AUTH_MODE"] = "stub"
os.environ["DEV_SECRET"] = "test-secret"
os.environ["MMOS_SERVICE_KEY"] = ""
os.environ["ENVIRONMENT"] = "development"

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


def token_for(name: str = "Dev User", roles: list[str] | None = None, sub: str = "user:dev-local", **overrides) -> str:
    claims = {
        "sub": sub, "emp": "DEV-0001", "name": name, "email": None,
        "dept": "Unassigned", "division": "Unassigned", "band": "L1",
        "approval_level": None, "roles": roles or ["viewer"], "platform_admin": False,
    }
    claims.update(overrides)
    return make_dev_token(claims)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
