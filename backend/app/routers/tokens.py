"""Owned by A2 — Tokens and Control Plane. See docs/09-build-agents.md.

POST /api/token/service — the handoff that turns a live MM OS session into a short-lived,
per-service JWT. This is the one call every "open a service" click goes through.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..deps import audit, client_ip, current_employee, current_user
from ..models import Employee, Grant, Service, User
from ..ratelimit import check_rate_limit
from ..security import mint_service_token

router = APIRouter()

# ── rate limit: 60 requests/minute per user ─────────────────────────────────
# L1/L2 phase (28 Aug 2026): this was an in-process sliding window, so it only held within a
# single worker -- the reason the deployment was pinned to `--workers 1`. It now shares one
# budget across every worker/replica through the `rate_limits` table (app/ratelimit.py):
# same 60/min window, same "over-budget requests write nothing" property, correct regardless
# of how many workers serve. Keyed per user, namespaced "token:" so it never collides with
# auth.py's per-IP "pin:" buckets in the same shared table.
_RATE_LIMIT = 60
_RATE_WINDOW_SECONDS = 60.0


class TokenRequest(BaseModel):
    slug: str


def live_grants(db: OrmSession, user_id, service: Service) -> list[Grant]:
    """The person's grants on `service` that have not expired."""
    now = datetime.now(timezone.utc)
    grants = db.scalars(select(Grant).where(Grant.user_id == user_id, Grant.service_id == service.id))
    return [g for g in grants if g.expires_at is None or g.expires_at > now]


def token_access(grants: list[Grant]) -> tuple[list[str], list[str]]:
    """(roles, permissions) exactly as a service token carries them: sorted role keys, and the
    sorted union of those roles' permission lists. Admin -> People "view as" reads the same
    function, so what it shows is what the service receives."""
    roles = sorted({grant.role.key for grant in grants})
    permissions = sorted({p for grant in grants for p in (grant.role.permissions or [])})
    return roles, permissions


@router.post("/token/service")
def issue_service_token(
    body: TokenRequest,
    request: Request,
    user: User = Depends(current_user),
    employee: Employee = Depends(current_employee),
    db: OrmSession = Depends(get_db),
):
    if check_rate_limit(db, bucket=f"token:{user.id}", limit=_RATE_LIMIT, window_seconds=_RATE_WINDOW_SECONDS):
        raise HTTPException(
            429,
            detail={
                "error": "rate_limited",
                "message": "Too many token requests. Slow down and try again shortly.",
            },
        )

    service = db.scalar(
        select(Service).where(Service.slug == body.slug, Service.is_active.is_(True))
    )
    grants = live_grants(db, user.id, service) if service is not None else []

    if service is None or not grants:
        audit(
            db,
            action="token.denied",
            actor_user_id=user.id,
            target_type="service",
            target_id=body.slug,
            ip=client_ip(request),
        )
        db.commit()
        raise HTTPException(
            403,
            detail={
                "error": "grant_not_found",
                "message": f"You have no access to {body.slug}.",
            },
        )

    roles, permissions = token_access(grants)
    grant_expiries = [g.expires_at for g in grants if g.expires_at is not None]
    token, jti, ttl = mint_service_token(
        user=user, employee=employee, service_slug=service.slug,
        roles=roles, permissions=permissions,
        expires_at=min(grant_expiries) if grant_expiries else None,
    )
    audit(
        db,
        action="token.issue",
        actor_user_id=user.id,
        target_type="service",
        target_id=str(service.id),
        service_id=service.id,
        ip=client_ip(request),
        jti=jti,
    )
    db.commit()

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "launch_url": f"{service.base_url.rstrip('/')}/_mmos/accept#token={token}",
    }
