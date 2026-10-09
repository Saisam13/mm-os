"""Request dependencies: the current session, the current user, guards, audit, client IP."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from ipaddress import ip_address

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .config import settings
from .db import get_db
from .models import AuditLog, Employee, Service, Session, User, UserCapability
from .security import hash_token
from .authorization import permits


def client_ip(request: Request) -> str:
    """Take the Nth-from-the-right X-Forwarded-For entry.

    Trusting the leftmost value lets any caller spoof an address, which would turn the
    private-network allowlist into decoration.
    """
    cfg = settings()
    n = cfg.trusted_proxy_count
    peer = request.client.host if request.client else "0.0.0.0"
    try:
        trusted_peer = any(ip_address(peer) in net for net in cfg.proxy_cidrs)
    except ValueError:
        trusted_peer = False
    if n > 0 and trusted_peer:
        chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(chain) >= n:
            candidate = chain[-n]
            try:
                ip_address(candidate)
                return candidate
            except ValueError:
                pass
    return request.client.host if request.client else "0.0.0.0"


def current_session(request: Request, db: OrmSession = Depends(get_db)) -> Session:
    raw = request.cookies.get(settings().cookie_name)
    if not raw:
        raise HTTPException(401, detail={"error": "no_session", "message": "Sign in to continue."})
    row = db.scalar(select(Session).where(Session.token_hash == hash_token(raw)))
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise HTTPException(401, detail={"error": "session_expired", "message": "Sign in again."})
    return row


def authenticated_user(
    sess: Session = Depends(current_session), db: OrmSession = Depends(get_db)
) -> User:
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(403, detail={"error": "user_inactive", "message": "Access removed."})
    emp = db.get(Employee, user.employee_id)
    if emp is None or emp.status != "active":
        raise HTTPException(403, detail={"error": "employee_inactive", "message": "Access removed."})
    return user


def current_user(user: User = Depends(authenticated_user), db: OrmSession = Depends(get_db), sess: Session = Depends(current_session)) -> User:
    from .provision import must_change_pin
    if must_change_pin(db, user):
        raise HTTPException(403, {"error": "pin_change_required", "message": "Change your temporary PIN before continuing."})
    from .onboarding import needs_onboarding
    if needs_onboarding(user):
        raise HTTPException(403, {"error": "onboarding_required", "message": "Finish account setup before continuing."})
    if user.is_platform_admin and sess.auth_method != "google":
        raise HTTPException(403, {"error": "admin_reauthentication_required", "message": "Platform administrators must sign in with Google."})
    return user


def current_employee(
    user: User = Depends(authenticated_user), db: OrmSession = Depends(get_db)
) -> Employee:
    emp = db.get(Employee, user.employee_id)
    if emp is None or emp.status != "active":
        raise HTTPException(403, detail={"error": "employee_inactive", "message": "Access removed."})
    return emp


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(
            403, detail={"error": "admin_required", "message": "This page is for IT administrators."}
        )
    return user


CAPABILITIES = {
    "people.view", "people.create", "people.edit", "departments.assign",
    "grants.view", "grants.add", "grants.change", "grants.revoke",
    "agents.manage", "admin_roles.manage", "hr_onboarding.create",
    "people.authority",
    "credentials.reset",
    "activity.view", "activity.private.view",
}


def has_capability(db: OrmSession, user: User, capability: str, *, department_id=None, any_scope=False) -> bool:
    """Platform admins own every administration capability; delegated users hold only
    explicit rows. No request-body or frontend flag participates in this decision."""
    return permits(db, user, capability, department_id=department_id, any_scope=any_scope)


def require_capability(capability: str, *, allow_scoped=False):
    if capability not in CAPABILITIES:
        raise ValueError(f"Unknown capability: {capability}")

    def dependency(
        user: User = Depends(current_user), db: OrmSession = Depends(get_db)
    ) -> User:
        if not has_capability(db, user, capability, any_scope=allow_scoped):
            raise HTTPException(
                403,
                detail={"error": "capability_required", "message": f"Requires {capability}."},
            )
        return user

    return dependency


def require_revocation_key(
    request: Request, db: OrmSession = Depends(get_db)
) -> Service:
    """Auth for server-to-server calls from a registered service."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, detail={"error": "service_key_required"})
    key_hash = hash_token(header.removeprefix("Bearer ").strip())
    svc = db.scalar(select(Service).where(Service.service_key_hash == key_hash))
    if svc is None:
        raise HTTPException(401, detail={"error": "service_key_invalid"})
    return svc


def require_service_key(service: Service = Depends(require_revocation_key)) -> Service:
    if not service.is_active:
        raise HTTPException(401, detail={"error": "service_key_invalid"})
    return service


def audit(
    db: OrmSession,
    *,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    service_id: uuid.UUID | None = None,
    ip: str | None = None,
    **metadata,
) -> None:
    """Append an audit row. Called inside the caller transaction, never committed here,
    so a change and its audit entry can never half-succeed."""
    person = db.get(User, actor_user_id) if actor_user_id else None
    employee = person.employee if person else None
    from .provision import FUNCTIONAL_JOB_TITLE
    snapshot = {"subject": f"user:{actor_user_id}" if actor_user_id else "system:mmos",
                "actor_type": ("service" if employee and employee.job_title == FUNCTIONAL_JOB_TITLE else "human") if actor_user_id else "system",
                "name": employee.full_name if employee else None,
                "employee_code": employee.employee_code if employee else None}
    metadata = dict(metadata, actor_snapshot=snapshot)
    from .activity_contract import make_event, canonical
    from .models import ServiceActivity
    import hashlib
    event = make_event(service="mmos", actor=snapshot, action=action,
                       target_type=target_type or "system", target_id=target_id or "mmos",
                       changed_fields=[str(k) for k in metadata if k != "actor_snapshot"],
                       department=employee.hr_department if employee else None,
                       outcome="denied" if "denied" in action or "protected_attempt" in action else "success")
    db.add(ServiceActivity(event_id=event["event_id"], source_service_id=uuid.UUID(int=0), service_slug="mmos",
        actor_subject=event["actor"]["subject"], actor_name=event["actor"]["name"], actor_code=event["actor"]["employee_code"],
        department_id=employee.department_id if employee else None, action=action,
        target_type=event["target"]["type"], target_id=event["target"]["id"], outcome=event["outcome"], restricted=True,
        occurred_at=datetime.fromisoformat(event["occurred_at"]), payload=event,
        digest=hashlib.sha256(canonical(event).encode()).hexdigest()))
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            service_id=service_id,
            ip=ip,
            metadata_=metadata or {},
        )
    )
