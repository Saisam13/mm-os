"""App assembly for the Service Desk service — its own FastAPI app, its own database, its
own container. Mounts the built frontend from the same port, the same pattern MM OS itself
uses (backend/app/main.py).
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import db_healthy, engine
from .mmos_seam import get_real_mmos
from .models import Base
from .routers import admin, comments, decisions, mmos, proposals, tickets
from .seed import ensure_default_approval_routing, ensure_default_sla_config

cfg = settings()

# Fail closed: `stub` auth mode registers the dev-only /_dev/token minter and a local token
# codec that trusts anyone. That is correct for local dev and every test in this repo, but
# it is a full authentication bypass if it ever reaches a real deployment. Absence of
# configuration must never mean absence of authentication, so a production environment that
# is still in stub mode refuses to boot rather than silently serving open. Set
# AUTH_MODE=http (with MMOS_SERVICE_KEY) for any non-development environment. An explicit
# SERVICEDESK_ALLOW_STUB_IN_PROD=1 exists only as a deliberate, logged escape hatch.
import os as _os

if cfg.environment == "production" and cfg.auth_mode != "http":
    if _os.environ.get("SERVICEDESK_ALLOW_STUB_IN_PROD") != "1":
        raise RuntimeError(
            "Service Desk refuses to start: environment=production but AUTH_MODE="
            f"{cfg.auth_mode!r}. Set AUTH_MODE=http and MMOS_SERVICE_KEY, or set "
            "SERVICEDESK_ALLOW_STUB_IN_PROD=1 to override (never do this on a real server)."
        )

# Dev/test convenience: create tables if they do not exist yet (sqlite here; Postgres in
# production is migrated with Alembic — see alembic/versions/0001_initial.py, which mirrors
# this same portable schema).
Base.metadata.create_all(bind=engine)

# Approval Routing must never start out empty — see app/seed.py's docstring. No-op outside
# ORG_CHART_MODE=seed.
ensure_default_approval_routing()

# Nor should the SLA tab — see app/seed.py's ensure_default_sla_config docstring. Runs in
# every mode; idempotent.
ensure_default_sla_config()


async def _heartbeat_loop() -> None:  # pragma: no cover - no live MM OS in this sandbox
    """docs/05: "send a heartbeat every 5 minutes". A no-op when no service key is
    configured (local dev, and every test in this repo), so nothing here ever makes a
    network call during `pytest`."""
    if not cfg.mmos_service_key:
        return
    while True:
        try:
            httpx.post(
                f"{cfg.mmos_os_url}/api/agent/heartbeat",
                headers={"Authorization": f"Bearer {cfg.mmos_service_key}"},
                json={"version": cfg.version, "llm": {"needed": False}},
                timeout=5.0,
            )
        except Exception:
            pass  # availability beats freshness — docs/04-auth-flow.md
        await asyncio.sleep(300)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_heartbeat_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Service Desk", version=cfg.version, docs_url=None, redoc_url=None, lifespan=lifespan)

app.include_router(mmos.router, prefix="")
app.include_router(tickets.router, prefix="/api")
app.include_router(proposals.router, prefix="/api")
app.include_router(decisions.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# B1 (assembly, run 2) -- the real auth wiring A5's handoff flagged as "entirely undone".
# In production ("http" mode), the real mmos-client-py kit installs /_mmos/accept,
# /_mmos/session and /_mmos/health itself (routers/mmos.py's own versions of the first and
# third are gated to "stub" mode -- see that file), starts the deny-list poller and the
# heartbeat loop for real, and registers its own flat-error-envelope exception handler
# (matching MM OS's own -- see backend/app/main.py). Never runs during any test in this
# repo: every test sets AUTH_MODE=stub (tests/conftest.py), so this branch is untouched by
# the 31 passing tests and only exercised on a real deployment.
if cfg.auth_mode == "http":
    get_real_mmos().install(app)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": cfg.version, "db": "up" if db_healthy() else "down"}


# ── the built frontend, served from the same container and port ──────────
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
