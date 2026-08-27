"""MM OS integration surface — docs/05-service-integration.md's contract. Mirrors
servicedesk/app/routers/mmos.py's shape.

`/_mmos/accept` and `/_mmos/health` below are a minimal stand-in for what
`mmos.install(app)` provides, used only in `auth_mode="stub"` (local dev and every test in
this repo). In `auth_mode="http"`, `app/main.py` calls the real
`mmos_client.core.MMOS.install(app)` instead, which serves both paths itself (plus
`/_mmos/session`, the deny-list poller and the heartbeat) — see `app/mmos_seam.py`.
Registering both here unconditionally would double-register the same paths, so the stub
routes below are gated to stub mode only; `/_dev/token` already 404s outside stub mode and
stays unconditional.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..config import settings
from ..db import db_healthy
from ..mmos_seam import COOKIE_NAME, make_dev_token, verify_token

router = APIRouter(tags=["mmos"])
_cfg = settings()

if _cfg.auth_mode == "stub":

    @router.get("/_mmos/health")
    def health():
        cfg = settings()
        return {"ok": True, "service": cfg.mmos_service_slug, "version": cfg.version, "db": "up" if db_healthy() else "down"}

    class AcceptIn(BaseModel):
        token: str

    @router.post("/_mmos/accept")
    def accept(body: AcceptIn, response: Response):
        user = verify_token(body.token)  # 401 on failure, same as any other call
        response.set_cookie(
            COOKIE_NAME, body.token, httponly=True, samesite="lax", max_age=900,
        )
        return {"ok": True, "sub": user.sub}


# A single dev/test persona — this is a shell with no org-chart lookup and no seeded
# employees (rule #1: no real employee names/emails in this repo). Manual-testing
# convenience only, not a feature: 404s the moment AUTH_MODE is anything but "stub" — see
# `## Assumptions`, this must never exist against a real deployment.
class DevTokenIn(BaseModel):
    name: str = "Dev User"
    roles: list[str] = ["viewer"]


@router.post("/_dev/token")
def dev_token(body: DevTokenIn):
    cfg = settings()
    if cfg.auth_mode != "stub":
        raise HTTPException(status_code=404)
    claims = {
        "sub": "user:dev-local", "emp": "DEV-0001", "name": body.name,
        "email": None, "dept": "Unassigned", "division": "Unassigned", "band": "L1",
        "approval_level": None, "roles": body.roles, "platform_admin": False,
    }
    return {"token": make_dev_token(claims, cfg.dev_secret)}
