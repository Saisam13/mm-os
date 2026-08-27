"""app/main.py's fail-closed boot guard: environment=production with AUTH_MODE=stub must
refuse to start. This is an import-time check (app/main.py raises at module import), so it
is exercised in a subprocess rather than by importing app.main into this process — the
main test run already imported it once under AUTH_MODE=stub/ENVIRONMENT=development and
Python does not re-run module bodies on a second import.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(env_overrides: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_production_with_stub_auth_refuses_to_boot():
    result = _run({"ENVIRONMENT": "production", "AUTH_MODE": "stub", "DEV_SECRET": "x"})
    assert result.returncode != 0
    assert "refuses to start" in result.stderr
    assert "AUTH_MODE" in result.stderr


def test_production_with_stub_auth_and_explicit_override_boots():
    result = _run({
        "ENVIRONMENT": "production", "AUTH_MODE": "stub", "DEV_SECRET": "x",
        "PWMGR_ALLOW_STUB_IN_PROD": "1",
    })
    assert result.returncode == 0, result.stderr


def test_development_with_stub_auth_boots():
    result = _run({"ENVIRONMENT": "development", "AUTH_MODE": "stub", "DEV_SECRET": "x"})
    assert result.returncode == 0, result.stderr
