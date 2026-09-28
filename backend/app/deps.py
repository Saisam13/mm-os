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
from .models import AuditLog, Employee, Service, Session, User
from .security import hash_token


def client_ip(request: Request) -> str:
    """Take the Nth-from-the-right X-Forwarded-For entry.

    Trusting the leftmost value lets any caller spoof an address, which would turn the
    private-network allowlist into decoration.
    """
    n = settings().trusted_proxy_count
    if n > 0:
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


def current_user(
    sess: Session = Depends(current_session), db: OrmSession = Depends(get_db)
) -> User:
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(403, detail={"error": "user_inactive", "message": "Access removed."})
    return user


def current_employee(
    user: User = Depends(current_user), db: OrmSession = Depends(get_db)
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


def require_service_key(
    request: Request, db: OrmSession = Depends(get_db)
) -> Service:
    """Auth for server-to-server calls from a registered service."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, detail={"error": "service_key_required"})
    key_hash = hash_token(header.removeprefix("Bearer ").strip())
    svc = db.scalar(select(Service).where(Service.service_key_hash == key_hash))
    if svc is None or not svc.is_active:
        raise HTTPException(401, detail={"error": "service_key_invalid"})
    return svc


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
