"""`GET /api/me` — the one call the shell lives on. Owned by A1 (Identity).

Shape is fixed by docs/03-api-contract.md. `services` is filtered here, server-side, to the
caller's live grants — the client is never sent a service it has no grant for and asked to
hide it, and an expired grant (`expires_at < now`) never shows up at all.

`GET /public/services` (resolves to `/api/public/services`, mounted alongside `/api/me`
below) added by B1 -- see handoff/b1-assembly.md ## Endpoints added. A3's shell built the
entry page against it (docs/03-api-contract.md), but no agent had router ownership of the
`/api` prefix's bare "/public/*" path free to add it in run 1.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..deps import current_employee, current_user
from urllib.parse import quote

from ..models import Employee, Grant, Service, ServiceRole, User
from ..onboarding import needs_onboarding
from ..provision import FUNCTIONAL_JOB_TITLE, must_change_pin

router = APIRouter()

GMAIL_URL = "https://mail.google.com/mail/u/?authuser={email}"


def _mail_tiles(db: OrmSession, user: User, employee: Employee) -> list[dict]:
    """The person's own mailbox, then their department's shared (functional) mailboxes.

    Gmail sends X-Frame-Options and refuses to load inside another site, so these are
    new-tab links, not embeds. `authuser` makes Gmail open that account if the browser is
    signed into it; otherwise Google asks which account to use."""
    own = user.login_email or employee.work_email
    tiles = []
    if own:
        tiles.append({"kind": "own", "label": "My mail", "email": own, "url": GMAIL_URL.format(email=quote(own))})
    shared = db.execute(
        select(Employee.work_email)
        .join(User, User.employee_id == Employee.id)
        .where(
            Employee.job_title == FUNCTIONAL_JOB_TITLE,
            Employee.hr_department == employee.hr_department,
            Employee.work_email.is_not(None),
            User.is_active.is_(True),
        )
        .order_by(Employee.work_email)
    ).scalars().all()
    for addr in shared:
        if addr != own:
            tiles.append({"kind": "department", "label": f"{employee.hr_department} mail", "email": addr,
                          "url": GMAIL_URL.format(email=quote(addr))})
    return tiles


@router.get("/public/services")
def public_services(db: OrmSession = Depends(get_db)):
    """No session required (docs/03: "reachable without signing in, so every field on it is
    a field published to anyone who can reach the login page"). Names and launch URLs only
    -- no roles, no health, no owner, no counts, no employee data."""
    services = db.scalars(
        select(Service).where(Service.is_active.is_(True)).order_by(Service.sort_order, Service.name)
    ).all()
    return {
        "services": [
            {
                "slug": s.slug,
                "name": s.name,
                "launch_url": s.base_url,
                # third-party services own their own sign-in (ERPNext, Twenty); everything
                # else bounces through MM OS first -- see brand/UI-DECISIONS.md "Entry page".
                "session_owner": "service" if s.launch_mode == "external" else "mmos",
            }
            for s in services
        ]
    }


@router.get("/me")
def me(
    user: User = Depends(current_user),
    employee: Employee = Depends(current_employee),
    db: OrmSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(Grant, Service, ServiceRole)
        .join(Service, Grant.service_id == Service.id)
        .join(ServiceRole, Grant.service_role_id == ServiceRole.id)
        .where(
            Grant.user_id == user.id,
            Service.is_active.is_(True),
            or_(Grant.expires_at.is_(None), Grant.expires_at > now),
        )
        .order_by(Service.sort_order, Service.name)
    ).all()

    services = [
        {
            "slug": service.slug,
            "name": service.name,
            "category": service.category,
            "role": role.key,
            "launch_mode": service.launch_mode,
            "base_url": service.base_url,
            "icon": service.icon,
            # Live health checks are not this router's job (no agent owns a health poller
            # yet) — reporting "unknown" here is honest rather than guessing "up".
            "health": "unknown",
        }
        for _grant, service, role in rows
    ]

    return {
        "user": {
            "id": str(user.id),
            "name": employee.full_name,
            "employee_code": employee.employee_code,
            "email": user.login_email or employee.work_email,
            "auth_type": user.auth_type,
            "department": employee.hr_department,
            "division": employee.division,
            "band": employee.band,
            "approval_level": employee.approval_level,
            "is_platform_admin": user.is_platform_admin,
            # True while the person is still on a provisioned one-time PIN -- the shell routes
            # them to the change-PIN screen (routers/auth.py POST /api/auth/pin/change).
            "must_change_pin": must_change_pin(db, user),
            # True until they have confirmed their employee code and set a PIN once (first
            # Google sign-in, app/onboarding.py) -- the shell routes them to /welcome.
            "needs_onboarding": needs_onboarding(user),
        },
        "services": services,
        "mail": _mail_tiles(db, user, employee),
        "badges": {
            # A5 (Service Desk) owns the real open-ticket count; this stays 0 until that
            # service reports it.
            "servicedesk_open": 0,
            "approvals_waiting": 0,
        },
    }
