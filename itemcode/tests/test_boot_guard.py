"""The fail-closed boot guard in app/main.py: environment=production with a non-http
AUTH_MODE must refuse to start rather than silently serving open. Run in a subprocess — the
guard raises at import time, and `app/config.py`'s `settings()` is `lru_cache`d per
process, so this cannot be exercised by re-importing `app.main` inside the same interpreter
that the rest of this suite already imported it in (conftest.py sets AUTH_MODE=stub once,
process-wide).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]


def _run(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{Path(tempfile.gettempdir()) / 'itemcode_bootguard.db'}",
            "DEV_SECRET": "test-secret",
            "MMOS_SERVICE_KEY": "",
        }
    )
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=str(APP_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_production_with_stub_auth_refuses_to_boot():
    result = _run({"ENVIRONMENT": "production", "AUTH_MODE": "stub"})
    assert result.returncode != 0
    assert "refuses to start" in result.stderr


def test_production_with_stub_auth_and_explicit_override_boots():
    result = _run(
        {
            "ENVIRONMENT": "production",
            "AUTH_MODE": "stub",
            "ITEMCODE_ALLOW_STUB_IN_PROD": "1",
        }
    )
    assert result.returncode == 0, result.stderr


def test_development_with_stub_auth_boots():
    result = _run({"ENVIRONMENT": "development", "AUTH_MODE": "stub"})
    assert result.returncode == 0, result.stderr
