"""Owned by A2 — Tokens and Control Plane. See docs/09-build-agents.md.

Service -> MM OS. Every route here is authenticated by `require_service_key`
(Authorization: Bearer <service_key>), never by a browser session.

One heartbeat call does three jobs (docs/01-architecture.md, "LLM: control plane, not data
plane"): proves the service is alive, populates the LLM control plane, and lets the service
pick up the kill switch. `/api/revocations` is the deny-list every service polls.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select

from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import audit, client_ip, require_service_key
from ..models import AuditLog, Employee, LlmRegistration, LlmUsageDaily, Revocation, Service, User

router = APIRouter()

# Audit actions that count as one "config version" bump for a service's LLM control plane.
# Deriving the version from a count of these audit rows means we need no extra column on
# the frozen `llm_registrations` table (see handoff Assumptions).
LLM_TOGGLE_ACTIONS = ("llm.enable", "llm.disable")

# A heartbeat must never carry an API key. Field names are matched, not values — we never
# log or store what was rejected, only that something was.
_KEY_FIELD_RE = re.compile(r"(api[_-]?key|secret|password|access[_-]?token)", re.I)


def _looks_like_key(field_name: str) -> bool:
    if field_name == "key_present":  # the one legitimate boolean that contains "key"
        return False
    if field_name.lower() == "key":
        return True
    return bool(_KEY_FIELD_RE.search(field_name))


def _strip_key_fields(d: dict) -> tuple[dict, list[str]]:
    clean: dict = {}
    dropped: list[str] = []
    for k, v in d.items():
        if isinstance(k, str) and _looks_like_key(k):
            dropped.append(k)
        else:
            clean[k] = v
    return clean, dropped


def _get_or_create_registration(db, service: Service) -> LlmRegistration:
    reg = db.scalar(select(LlmRegistration).where(LlmRegistration.service_id == service.id))
    if reg is None:
        # A service that has never reported an `llm` block is visibly `unreported`,
        # never silently blank (docs/01-architecture.md).
        reg = LlmRegistration(service_id=service.id, provider="unreported", enabled=True)
        db.add(reg)
        db.flush()
    return reg


def _config_version(db, service: Service) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.service_id == service.id,
                AuditLog.action.in_(LLM_TOGGLE_ACTIONS),
            )
        )
        or 0
    )


def _poll_after_seconds(db, service: Service) -> int:
    """The configured interval, dropped to 5s for ten minutes after an admin `kill`.

    Derived from the presence of a recent `admin_kill` revocation rather than separate
    process state, so it works the same whether or not this worker handled the kill call.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    hot = db.scalar(
        select(Revocation.id)
        .where(
            Revocation.reason == "admin_kill",
            Revocation.revoked_at >= cutoff,
            or_(Revocation.service_id == service.id, Revocation.service_id.is_(None)),
        )
        .limit(1)
    )
    return 5 if hot else settings().revocation_poll_seconds


@router.get("/revocations")
def revocations(
    since: datetime = Query(...),
    service: Service = Depends(require_service_key),
    db=Depends(get_db),
):
    rows = db.scalars(
        select(Revocation).where(
            Revocation.revoked_at > since,
            or_(Revocation.service_id == service.id, Revocation.service_id.is_(None)),
        )
    ).all()

    revoked_subjects = []
    revoked_jti = []
    for r in rows:
        if r.jti:
            revoked_jti.append(r.jti)
        else:
            revoked_subjects.append(
                {"sub": r.subject, "reason": r.reason, "at": r.revoked_at.isoformat()}
            )

    return {
        "now": datetime.now(timezone.utc).isoformat(),
        "poll_after_seconds": _poll_after_seconds(db, service),
        "revoked_subjects": revoked_subjects,
        "revoked_jti": revoked_jti,
    }


@router.post("/heartbeat")
def heartbeat(
    payload: dict,
    request: Request,
    service: Service = Depends(require_service_key),
    db=Depends(get_db),
):
    clean_top, dropped_top = _strip_key_fields(payload if isinstance(payload, dict) else {})

    llm_in = clean_top.get("llm")
    clean_llm: dict = {}
    dropped_llm: list[str] = []
    if isinstance(llm_in, dict):
        clean_llm, dropped_llm = _strip_key_fields(llm_in)

    dropped = dropped_top + [f"llm.{k}" for k in dropped_llm]

    reg = _get_or_create_registration(db, service)
    if clean_llm:
        reg.provider = clean_llm.get("provider") or reg.provider or "unreported"
        if "model" in clean_llm:
            reg.model = clean_llm.get("model")
        if "key_present" in clean_llm:
            reg.key_present = bool(clean_llm["key_present"])
    reg.last_seen_at = datetime.now(timezone.utc)

    usage = clean_top.get("usage")
    if isinstance(usage, dict):
        try:
            day = date.fromisoformat(usage["day"]) if usage.get("day") else date.today()
        except (ValueError, TypeError):
            day = date.today()
        row = db.scalar(
            select(LlmUsageDaily).where(
                LlmUsageDaily.service_id == service.id, LlmUsageDaily.day == day
            )
        )
        if row is None:
            row = LlmUsageDaily(service_id=service.id, day=day)
            db.add(row)
            db.flush()
        row.requests += int(usage.get("requests") or 0)
        row.input_tokens += int(usage.get("input_tokens") or 0)
        row.output_tokens += int(usage.get("output_tokens") or 0)

    if dropped:
        audit(
            db,
            action="heartbeat.key_rejected",
            target_type="service",
            target_id=str(service.id),
            service_id=service.id,
            ip=client_ip(request),
            fields=dropped,
        )

    db.commit()
    return {"llm_enabled": reg.enabled, "config_version": _config_version(db, service)}


@router.get("/org/chain")
def org_chain(
    sub: str = Query(...),
    service: Service = Depends(require_service_key),
    db=Depends(get_db),
):
    """Section B, seam inventory: a narrow, service-authenticated manager-chain lookup so
    Service Desk (`servicedesk/app/org_chart.py`'s `HttpOrgChartClient`, which already
    assumed exactly this shape -- `GET /api/org/chain?sub=` -> `{"chain": [...]}`,
    requester-first) can compute an approver without a directory dump.

    Minimum disclosure: only the fields approval routing needs (sub, employee_code,
    full_name, department, approval_level, is_approver, manager_sub, email) -- no band, no
    division, no job title, nothing else `/api/admin/employees` would return. Any service
    holding a valid service key may call this; there is no per-endpoint service ACL in this
    build (see handoff/b1-assembly.md ## Assumptions).

    Degrades gracefully rather than erroring: an unknown `sub`, a manager with no `manager_id`,
    or a manager who has an Employee row but no MM OS login yet all simply end the chain where
    they are. A1's handoff found only 11 of 73 real managers resolve from the sheet -- the org
    is genuinely too flat for every requester to have a full chain, so a short or empty
    `chain` is the expected, not the exceptional, response.
    """
    chain: list[dict] = []
    seen: set[str] = set()
    current_sub: str | None = sub

    for _ in range(20):  # hard cap against any accidental manager_id cycle
        if not current_sub or current_sub in seen:
            break
        seen.add(current_sub)
        if not current_sub.startswith("user:"):
            break
        try:
            user_id = uuid.UUID(current_sub.removeprefix("user:"))
        except ValueError:
            break
        person = db.get(User, user_id)
        if person is None:
            break
        employee = db.get(Employee, person.employee_id)
        if employee is None:
            break

        node = {
            "sub": person.subject,
            "employee_code": employee.employee_code,
            "full_name": employee.full_name,
            "department": employee.hr_department,
            "approval_level": employee.approval_level,
            "is_approver": employee.is_approver,
            "manager_sub": None,
            "email": person.login_email or employee.work_email,
        }
        chain.append(node)

        if employee.manager_id is None:
            break
        manager_employee = db.get(Employee, employee.manager_id)
        manager_user = (
            db.scalar(select(User).where(User.employee_id == manager_employee.id))
            if manager_employee is not None
            else None
        )
        if manager_user is None:
            # The manager has no MM OS login yet (not seeded, or not provisioned) -- the
            # chain ends here rather than guessing; org_chart.qualifies() on the caller's
            # side treats a short chain as "escalate to whoever's left," never an error.
            break
        node["manager_sub"] = manager_user.subject
        current_sub = manager_user.subject

    return {"chain": chain}


@router.get("/config")
def agent_config(service: Service = Depends(require_service_key), db=Depends(get_db)):
    reg = _get_or_create_registration(db, service)
    db.commit()
    return {
        "llm_enabled": reg.enabled,
        "config_version": _config_version(db, service),
        "poll_after_seconds": _poll_after_seconds(db, service),
    }


# ── purge job: revocations only need to outlive live tokens (docs/02-data-model.md) ────
def purge_expired_revocations(db) -> int:
    now = datetime.now(timezone.utc)
    result = db.execute(sa_delete(Revocation).where(Revocation.purge_after <= now))
    db.commit()
    return result.rowcount or 0


def _purge_loop() -> None:
    while True:
        time.sleep(3600)
        try:
            with SessionLocal() as db:
                purge_expired_revocations(db)
        except Exception:
            pass


if settings().environment != "test":
    threading.Thread(target=_purge_loop, daemon=True, name="mmos-revocation-purge").start()
