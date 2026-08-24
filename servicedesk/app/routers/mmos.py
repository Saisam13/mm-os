"""MM OS integration surface — docs/05-service-integration.md's five-point contract, plus
the OS-bar badge count (docs/07: "MM OS badge count").

`/_mmos/accept` and `/_mmos/health` below are a minimal stand-in for what `mmos.install(app)`
provides, used only in `auth_mode="stub"` (local dev and every test in this repo). In
`auth_mode="http"`, `app/main.py` calls the real `mmos_client.core.MMOS.install(app)`
instead, which serves both paths itself (plus `/_mmos/session`, the deny-list poller and the
heartbeat) -- see `app/mmos_seam.py`'s "B1" docstring note. Registering both here
unconditionally would double-register the same paths, so the stub routes below are gated to
stub mode only; `/api/badge` and `/_dev/token` are unaffected by auth mode (badge has no auth
dependency at all, and `/_dev/token` already 404s outside stub) and stay unconditional.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import db_healthy, get_db
from ..mmos_seam import COOKIE_NAME, make_dev_token, verify_token
from ..models import Ticket
from ..org_chart import SEED_PERSONAS
from ..schemas import BadgeOut

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


class DevTokenIn(BaseModel):
    persona: str  # one of app.org_chart.SEED_PERSONAS's keys: operator, supervisor, hod, apex
    roles: list[str] = ["requester"]


@router.post("/_dev/token")
def dev_token(body: DevTokenIn):
    """Manual-testing convenience, not a feature: mints a stub token for one of the seeded
    personas so `servicedesk/README.md`'s "How to verify" steps and the frontend's dev
    sign-in screen work without a live MM OS to sign in through. 404s the moment
    `AUTH_MODE` is anything but `stub` — see `## Assumptions`, this must never exist against
    a real deployment."""
    cfg = settings()
    if cfg.auth_mode != "stub":
        raise HTTPException(status_code=404)
    person = SEED_PERSONAS.get(body.persona)
    if person is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_persona", "known": list(SEED_PERSONAS)})
    claims = {
        "sub": person["sub"], "emp": person["employee_code"], "name": person["full_name"],
        "email": person["email"], "dept": person["department"], "division": person["division"],
        "band": person["band"], "approval_level": person["approval_level"],
        "roles": body.roles, "platform_admin": False,
    }
    return {"token": make_dev_token(claims, cfg.dev_secret)}


@router.get("/api/badge", response_model=BadgeOut)
def badge(sub: str, db: Session = Depends(get_db)):
    """`GET /api/badge?sub=...` — the count `/api/me`'s `badges.servicedesk_open` shows on
    the OS bar. No auth dependency: this is a service-to-service call from MM OS itself
    (docs/03-api-contract.md's `/api/me` assembles it), scoped to a single `sub` it already
    knows, not a way to enumerate anyone's tickets."""
    open_count = db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.requester_sub == sub, Ticket.status.notin_(("closed", "rejected"))
        )
    ).scalar_one()
    waiting_count = db.execute(
        select(func.count()).select_from(Ticket).where(
            Ticket.approver_sub == sub, Ticket.status == "manager_review"
        )
    ).scalar_one()
    return BadgeOut(open=open_count, approvals_waiting=waiting_count)
