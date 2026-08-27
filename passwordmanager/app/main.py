"""App assembly for the Password Manager service — its own FastAPI app, its own container.
Mirrors servicedesk/app/main.py's shape (docs/05-service-integration.md).

THIS IS A SHELL. No secret storage, no vault, no encryption scheme exists anywhere in this
service yet — see SECURITY.md for what a real implementation would still need. The only
things this app does are: verify an MM OS token, set its own session cookie, and show a
placeholder page. Do not add credential storage here without first satisfying SECURITY.md.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import db_healthy
from .mmos_seam import AuthError, CurrentUser, get_current_user
from .routers import me, mmos

cfg = settings()

# Fail closed: `stub` auth mode registers a dev-only token minter and a local token codec
# that trusts anyone. That is correct for local dev and every test in this repo, but it is a
# full authentication bypass if it ever reaches a real deployment. Absence of configuration
# must never mean absence of authentication, so a production environment that is still in
# stub mode refuses to boot rather than silently serving open. Set AUTH_MODE=http (with
# MMOS_SERVICE_KEY) for any non-development environment. An explicit
# PWMGR_ALLOW_STUB_IN_PROD=1 exists only as a deliberate, logged escape hatch — matching
# servicedesk's SERVICEDESK_ALLOW_STUB_IN_PROD convention.
if cfg.environment == "production" and cfg.auth_mode != "http":
    if os.environ.get("PWMGR_ALLOW_STUB_IN_PROD") != "1":
        raise RuntimeError(
            "Password Manager refuses to start: environment=production but AUTH_MODE="
            f"{cfg.auth_mode!r}. Set AUTH_MODE=http and MMOS_SERVICE_KEY, or set "
            "PWMGR_ALLOW_STUB_IN_PROD=1 to override (never do this on a real server)."
        )

app = FastAPI(title="Password Manager", version=cfg.version, docs_url=None, redoc_url=None)

app.include_router(mmos.router, prefix="")
app.include_router(me.router, prefix="")

# In production ("http" mode), the real mmos-client-py kit would install /_mmos/accept,
# /_mmos/session and /_mmos/health itself, start the deny-list poller and a heartbeat loop —
# see servicedesk/app/main.py for the reference wiring. Not done here: this shell has no
# service key configured yet and no live MM OS to register against. When this service is
# actually registered in MM OS (see README.md), copy that block over unchanged.
if cfg.auth_mode == "http":
    from .mmos_seam import get_real_mmos  # pragma: no cover - no live MM OS in this sandbox

    get_real_mmos().install(app)  # pragma: no cover


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": cfg.version, "db": "up" if db_healthy() else "down"}


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Minimal server-rendered placeholder. Reads the same MM OS token every API route
    reads (bearer header or the `{slug}_mmos_at` cookie set by /_mmos/accept); shows a
    sign-in prompt if there isn't one, or the placeholder vault message if there is. No
    secrets are read, stored, or rendered here — there aren't any."""
    try:
        user: CurrentUser = get_current_user(request)
    except AuthError:
        body = (
            "<p>Not signed in. This page is normally reached via an MM OS launch tile, "
            "which hands off a token this service verifies.</p>"
        )
    else:
        name = _escape(user.name or user.sub)
        body = f"<p>Password Manager — signed in as {name}. Your vault will live here.</p>"

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Password Manager</title>
</head>
<body>
  <main style="font-family: Roboto, Arial, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;">
    <h1 style="color:#005D7F;">Password Manager</h1>
    {body}
    <p style="color:#666; font-size: 0.9rem;">
      This is a build shell — no credential storage exists yet. See SECURITY.md.
    </p>
  </main>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── the built frontend's static assets, served from the same container/port ──────────
# Mounted after the explicit "/" route above so that exact path still wins; this only ever
# serves /assets/* (and would serve a static index.html for any other unmatched path, which
# this shell does not otherwise define).
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if DIST.exists():
    app.mount("/static", StaticFiles(directory=DIST, html=True), name="frontend")
