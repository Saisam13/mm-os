"""MM OS integration surface — mirrors servicedesk/app/routers/mmos.py's stub-mode shape.

`/_mmos/accept` and `/_mmos/health` below are a minimal stand-in for what `mmos.install(app)`
provides, used only in `auth_mode="stub"` (local dev and every test in this repo). In
`auth_mode="http"`, `app/main.py` calls the real `mmos_client.core.MMOS.install(app)`
instead, which serves both paths itself (plus `/_mmos/session`, the deny-list poller and the
heartbeat) — see `app/mmos_seam.py`. Registering both here unconditionally would
double-register the same paths, so the stub routes below are gated to stub mode only;
`/_dev/token` is a manual-testing convenience and already 404s outside stub mode.
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


# ── manual-testing convenience, not a feature ────────────────────────────
# No real employee data is baked into this repo (rule #1 of the build brief) — the dev
# persona below is a placeholder, not a seeded roster like servicedesk's SEED_PERSONAS.
_DEV_PERSONA = {
    "sub": "user:dev-local",
    "employee_code": "DEV-0",
    "name": "Local Dev User",
    "email": None,
    "department": "Information Technology",
    "division": "Corporate",
    "band": "L1",
    "approval_level": None,
}


class DevTokenIn(BaseModel):
    roles: list[str] = ["employee"]


@router.post("/_dev/token")
def dev_token(body: DevTokenIn):
    """Mints a stub token for a single placeholder persona so this shell can be exercised
    without a live MM OS to sign in through. 404s the moment `AUTH_MODE` is anything but
    `stub` — this must never exist against a real deployment."""
    cfg = settings()
    if cfg.auth_mode != "stub":
        raise HTTPException(status_code=404)
    person = _DEV_PERSONA
    claims = {
        "sub": person["sub"], "emp": person["employee_code"], "name": person["name"],
        "email": person["email"], "dept": person["department"], "division": person["division"],
        "band": person["band"], "approval_level": person["approval_level"],
        "roles": body.roles, "platform_admin": False,
    }
    return {"token": make_dev_token(claims, cfg.dev_secret)}
