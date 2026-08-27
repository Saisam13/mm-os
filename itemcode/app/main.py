"""App assembly for Item Code Studio — its own FastAPI app, its own database, its own
container. A minimal SHELL: authenticates via MM OS's launch-token handoff and shows a
signed-in placeholder page; the item-code generation/registry product does not exist yet.
Mirrors servicedesk/app/main.py's assembly pattern (which mirrors backend/app/main.py).
"""
from __future__ import annotations

import os as _os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import db_healthy
from .mmos_seam import get_real_mmos
from .routers import api, mmos

cfg = settings()

# Fail closed: `stub` auth mode registers the dev-only /_dev/token minter and a local token
# codec that trusts anyone. That is correct for local dev and every test in this repo, but
# it is a full authentication bypass if it ever reaches a real deployment. Absence of
# configuration must never mean absence of authentication, so a production environment that
# is still in stub mode refuses to boot rather than silently serving open. Set
# AUTH_MODE=http (with MMOS_SERVICE_KEY) for any non-development environment. An explicit
# ITEMCODE_ALLOW_STUB_IN_PROD=1 exists only as a deliberate, logged escape hatch.
if cfg.environment == "production" and cfg.auth_mode != "http":
    if _os.environ.get("ITEMCODE_ALLOW_STUB_IN_PROD") != "1":
        raise RuntimeError(
            "Item Code Studio refuses to start: environment=production but AUTH_MODE="
            f"{cfg.auth_mode!r}. Set AUTH_MODE=http and MMOS_SERVICE_KEY, or set "
            "ITEMCODE_ALLOW_STUB_IN_PROD=1 to override (never do this on a real server)."
        )

app = FastAPI(title="Item Code Studio", version=cfg.version, docs_url=None, redoc_url=None)

app.include_router(mmos.router, prefix="")
app.include_router(api.router, prefix="")

# In production ("http" mode), the real mmos-client-py kit installs /_mmos/accept,
# /_mmos/session and /_mmos/health itself (routers/mmos.py's own stub versions of the first
# and third are gated to "stub" mode — see that file), and starts the deny-list poller and
# heartbeat loop for real. Never runs during any test in this repo: every test sets
# AUTH_MODE=stub (tests/conftest.py).
if cfg.auth_mode == "http":
    get_real_mmos().install(app)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": cfg.version, "db": "up" if db_healthy() else "down"}


# ── the built frontend, served from the same container and port ──────────
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
