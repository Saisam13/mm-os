"""FROZEN CONTRACT — do not edit in a build agent. See docs/09-build-agents.md.

App assembly. Every router this file imports is owned by exactly one build agent, so no two
agents ever edit the same file and there are no merge conflicts to resolve.

Router ownership:
    routers/auth.py           A1  Identity
    routers/people.py         A1  Identity (admin employees + users)
    routers/me.py             A1  Identity (/api/me, the call the shell lives on)
    routers/tokens.py         A2  Tokens and handoff
    routers/agent.py          A2  Service-to-MM-OS (heartbeat, config, revocations)
    routers/platform.py       A2  Admin services, roles, grants, LLM, audit

EDITED BY B1 (assembly, run 2) -- see handoff/b1-assembly.md ## Deviations for the exact
reasoning. Added the HTTPException handler near the bottom of this file: every router
raises HTTPException(detail={...}) (the pattern set by frozen deps.py), which FastAPI's
default handler wraps as {"detail": {...}}, while docs/03-api-contract.md documents a flat
{error, message, request_id}. No router changed -- this is the one place that reconciles
the wire shape with the doc.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import http_exception_handler as _default_http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import db_healthy
from .middleware import NetworkGate, RequestId, SecurityHeaders
from .routers import agent, auth, me, people, platform, tokens
from .security import jwks

cfg = settings()
app = FastAPI(title="MM OS", version=cfg.version, docs_url=None, redoc_url=None)

app.add_middleware(SecurityHeaders)
app.add_middleware(NetworkGate)
app.add_middleware(RequestId)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(me.router, prefix="/api", tags=["me"])
app.include_router(tokens.router, prefix="/api", tags=["tokens"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(people.router, prefix="/api/admin", tags=["admin"])
app.include_router(platform.router, prefix="/api/admin", tags=["admin"])


@app.exception_handler(HTTPException)
async def _flatten_error_envelope(request, exc: HTTPException):
    """docs/03-api-contract.md: every error is {"error","message","request_id"} at the top
    level. Every router in this app (frozen deps.py's own pattern) raises
    HTTPException(status_code, detail={"error": ..., "message": ...}), which FastAPI's
    default handler wraps as {"detail": {...}} instead. This is the single place that
    reconciles the two, without touching a router. Any extra key a caller put in `detail`
    (e.g. require_role's `need`/`have`) rides along unchanged."""
    request_id = getattr(request.state, "request_id", None) or "unknown"
    if isinstance(exc.detail, dict):
        body = {
            "error": exc.detail.get("error", "error"),
            "message": exc.detail.get("message") or exc.detail.get("error", ""),
            "request_id": request_id,
        }
        for k, v in exc.detail.items():
            body.setdefault(k, v)
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)
    return await _default_http_exception_handler(request, exc)


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": cfg.version, "db": "up" if db_healthy() else "down"}


@app.get("/.well-known/jwks.json")
def wellknown_jwks():
    return JSONResponse(jwks(), headers={"Cache-Control": "public, max-age=3600"})


# ── the OS bar, served to every registered service ───────────────────────
EMBED = Path(__file__).resolve().parents[2] / "packages" / "embed" / "embed.js"


@app.get("/embed.js")
def embed_js():
    return FileResponse(
        EMBED,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


# ── the built shell, served from the same container and port ─────────────
# SPA fallback (orchestrator fix, live bug): a client-side route like /dashboard or
# /admin/accounts has no file on disk, so plain StaticFiles(html=True) 404s it on a hard
# refresh / deep link. Serve index.html for any unmatched non-API path so the React router
# resolves it. API routes, /healthz, jwks and /embed.js are registered above and matched
# first, so this only ever catches genuine shell routes and missing assets.
from starlette.exceptions import HTTPException as _StarletteHTTPException  # noqa: E402


class _SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except _StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", _SPAStaticFiles(directory=DIST, html=True), name="shell")
