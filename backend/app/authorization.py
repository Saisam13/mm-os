"""Shared target, delegation and identity-lifecycle policy.

Mutations and their revocations remain in the caller's transaction. Scoped capabilities
never imply global authority, and profile editing is not privileged credential recovery.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text

from .models import Employee, Grant, Revocation, Session, User, UserCapability


def capability_scopes(db, actor: User, capability: str) -> set:
    return set(db.scalars(select(UserCapability.scope_department_id).where(
        UserCapability.user_id == actor.id, UserCapability.capability == capability,
    )))


def permits(db, actor: User, capability: str, *, department_id=None, any_scope=False) -> bool:
    if actor.is_platform_admin:
        return True
    scopes = capability_scopes(db, actor, capability)
    return bool(scopes) if any_scope else None in scopes or (
        department_id is not None and department_id in scopes
    )


def require_target(db, actor, capability, employee):
    if employee is None or not permits(db, actor, capability, department_id=employee.department_id):
        raise HTTPException(403, {"error": "department_scope_denied", "message": "This record is outside your permitted scope."})


def scope_query(db, actor, capability, query, department_column):
    if actor.is_platform_admin or None in capability_scopes(db, actor, capability):
        return query
    return query.where(department_column.in_(capability_scopes(db, actor, capability)))


def protected_admin_change(db, actor, target, *, removing=False):
    """Serialize protected-admin lifecycle operations on PostgreSQL, then read fresh state."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(72600101)"))
    db.refresh(target)
    db.refresh(actor)
    if not actor.is_platform_admin or not actor.is_active:
        raise HTTPException(403, {"error": "protected_admin", "message": "Requires protected platform administration."})
    if removing and target.is_platform_admin and target.is_active:
        active = db.scalar(select(func.count()).select_from(User).join(Employee).where(
            User.is_platform_admin.is_(True), User.is_active.is_(True), Employee.status == "active",
        )) or 0
        if active <= 1:
            from .deps import audit
            actor_id, target_id = actor.id, target.id
            # Bulk import may have staged other records. Reject the whole mutation,
            # then retain only the denied-attempt event in a separate transaction.
            db.rollback()
            audit(db, action="admin.protected_attempt", actor_user_id=actor_id,
                  target_type="user", target_id=target_id, reason="last_active_admin")
            db.commit()
            raise HTTPException(409, {"error": "last_active_admin", "message": "An active platform administrator must remain."})


def protect_identity_target(db, actor, target):
    if target.is_platform_admin:
        protected_admin_change(db, actor, target)


def protect_credential_target(db, actor, target):
    protect_identity_target(db, actor, target)
    if not actor.is_platform_admin:
        now = datetime.now(timezone.utc)
        privileged = any(g.role.key in {"admin", "owner"} or "service.admin" in (g.role.permissions or [])
                         for g in db.scalars(select(Grant).where(
            Grant.user_id == target.id, or_(Grant.expires_at.is_(None), Grant.expires_at > now),
        )))
        privileged = privileged or db.scalar(select(UserCapability.id).where(
            UserCapability.user_id == target.id,
        ).limit(1)) is not None
        if privileged:
            raise HTTPException(403, {"error": "protected_credentials", "message": "Privileged credential recovery requires platform administration."})


def revoke_identity(db, target, *, reason, actor_id=None, keep_session_id=None):
    """Terminate shell sessions and emit a global cutoff, atomically with the mutation."""
    if target.id is None:
        db.flush()
    now = datetime.now(timezone.utc)
    query = select(Session).where(Session.user_id == target.id, Session.revoked_at.is_(None))
    if keep_session_id is not None:
        query = query.where(Session.id != keep_session_id)
    for session in db.scalars(query):
        session.revoked_at = now
    db.add(Revocation(subject=target.subject, service_id=None, reason=reason,
                      revoked_by=actor_id, revoked_at=now, purge_after=now + timedelta(hours=24)))


def require_grant_ceiling(db, actor, target, service, role, *, expires_at=None):
    """Initial ceiling: delegated assignment is a subset of the delegate's live grants.

    A future independent delegation-ceiling model can narrow this further. Existing broad
    grants.add rows alone cannot create service authority or authorize self-elevation.
    """
    require_target(db, actor, "grants.add", target.employee)
    now = datetime.now(timezone.utc)
    if expires_at is not None and (expires_at.tzinfo is None or expires_at <= now):
        raise HTTPException(422, {"error": "invalid_grant_expiry", "message": "Use a future time including its timezone."})
    if actor.is_platform_admin:
        return
    if actor.id == target.id or target.is_platform_admin:
        raise HTTPException(403, {"error": "delegation_escalation"})
    grants = list(db.scalars(select(Grant).where(
        Grant.user_id == actor.id, Grant.service_id == service.id,
        or_(Grant.expires_at.is_(None), Grant.expires_at > now),
    )))
    desired = set(role.permissions or [])
    candidates = [g for g in grants if g.service_role_id == role.id or (
        desired and desired.issubset(set(g.role.permissions or []))
    )]
    if not candidates or not any(g.expires_at is None or (
        expires_at is not None and expires_at <= g.expires_at
    ) for g in candidates):
        raise HTTPException(403, {"error": "delegation_escalation", "message": "The requested access exceeds your delegation ceiling."})
