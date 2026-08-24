"""Owned by A2 — Tokens and Control Plane. See docs/09-build-agents.md.

Admin surface for the service registry, grants, the LLM control plane and the audit log.
Every route here sits behind `require_admin`. Mounted at `/api/admin` by `app/main.py`.
"""
from __future__ import annotations

import base64
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..db import get_db
from ..deps import audit, client_ip, require_admin
from ..models import (
    AuditLog,
    Employee,
    Grant,
    LlmRegistration,
    LlmUsageDaily,
    Revocation,
    Service,
    ServiceRole,
    User,
)
from ..security import new_service_key
from .agent import _config_version


def _employee_of(db: OrmSession, user_id: uuid.UUID) -> Employee | None:
    user = db.get(User, user_id)
    return db.get(Employee, user.employee_id) if user else None


router = APIRouter()

# Matches the SQL default in docs/02-data-model.md (`purge_after` = now() + 2h). The
# SQLAlchemy model mirrors the column but not that default, so it is supplied here.
_REVOCATION_TTL = timedelta(hours=2)


# ── request bodies ───────────────────────────────────────────────────────────
class ServiceCreate(BaseModel):
    slug: str
    name: str
    base_url: str
    tagline: str | None = None
    category: str = "internal"
    icon: str | None = None
    launch_mode: str = "handoff"
    has_public_surface: bool = False
    public_url: str | None = None
    health_url: str | None = None
    sort_order: int = 100


class ServicePatch(BaseModel):
    name: str | None = None
    tagline: str | None = None
    category: str | None = None
    base_url: str | None = None
    icon: str | None = None
    launch_mode: str | None = None
    has_public_surface: bool | None = None
    public_url: str | None = None
    health_url: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class RoleCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    is_default: bool = False


class GrantCreate(BaseModel):
    user_id: uuid.UUID
    slug: str
    role: str
    reason: str | None = None
    expires_at: datetime | None = None


class GrantBulk(BaseModel):
    slug: str
    role: str
    band: list[str] | None = None
    department: list[str] | None = None
    reason: str | None = None


class LlmToggle(BaseModel):
    enabled: bool
    reason: str | None = None


# ── output shaping ───────────────────────────────────────────────────────────
def _service_out(s: Service) -> dict:
    return {
        "id": str(s.id),
        "slug": s.slug,
        "name": s.name,
        "tagline": s.tagline,
        "category": s.category,
        "base_url": s.base_url,
        "icon": s.icon,
        "launch_mode": s.launch_mode,
        "has_public_surface": s.has_public_surface,
        "public_url": s.public_url,
        "health_url": s.health_url,
        "is_active": s.is_active,
        "sort_order": s.sort_order,
        "roles": [
            # `description` added by B1 -- seam inventory section A.4: brand/UI-DECISIONS.md
            # "role meanings shown inline" on the Access page has no data source without it.
            # `ServiceRole.description` already existed on the frozen model; it was simply
            # never serialized. `id` added alongside it so a role is addressable without a
            # second round-trip through (service_id, key).
            {"id": str(r.id), "key": r.key, "name": r.name, "description": r.description, "is_default": r.is_default}
            for r in s.roles
        ],
    }


def _grant_out(db: OrmSession, g: Grant) -> dict:
    """Nested shape added by B1 -- seam inventory section A.4: brand/UI-DECISIONS.md's
    per-person drill-down needs "who granted it and when," which the flat
    `{user_id, service_slug, role}` this used to return has no room for without a second
    admin-side fetch per row. `granted_by` is None for the handful of grants seeded before
    any admin existed to attribute them to (see app/seed.py)."""
    user_emp = _employee_of(db, g.user_id)
    granter_emp = _employee_of(db, g.granted_by) if g.granted_by else None
    return {
        "id": str(g.id),
        "user": {
            "id": str(g.user_id),
            "name": user_emp.full_name if user_emp else None,
            "employee_code": user_emp.employee_code if user_emp else None,
        },
        "service": {"slug": g.service.slug, "name": g.service.name},
        "role": {"key": g.role.key, "name": g.role.name},
        "granted_by": (
            {"id": str(g.granted_by), "name": granter_emp.full_name if granter_emp else None}
            if g.granted_by
            else None
        ),
        "reason": g.reason,
        "expires_at": g.expires_at.isoformat() if g.expires_at else None,
        "created_at": g.created_at.isoformat(),
    }


def _encode_cursor(created_at: datetime, id_: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{id_}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    iso, id_str = raw.split("|", 1)
    return datetime.fromisoformat(iso), uuid.UUID(id_str)


# ── services ──────────────────────────────────────────────────────────────────
@router.get("/services")
def list_services(admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    services = db.scalars(select(Service).order_by(Service.sort_order, Service.name)).all()
    return {"services": [_service_out(s) for s in services]}


@router.post("/services", status_code=201)
def create_service(
    body: ServiceCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    if db.scalar(select(Service).where(Service.slug == body.slug)):
        raise HTTPException(
            409, detail={"error": "service_exists", "message": f"{body.slug} already exists."}
        )
    service = Service(**body.model_dump())
    db.add(service)
    db.flush()
    audit(
        db,
        action="service.create",
        actor_user_id=admin.id,
        target_type="service",
        target_id=str(service.id),
        service_id=service.id,
        ip=client_ip(request),
        slug=service.slug,
    )
    db.commit()
    return _service_out(service)


@router.patch("/services/{slug}")
def patch_service(
    slug: str,
    body: ServicePatch,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = db.scalar(select(Service).where(Service.slug == slug))
    if service is None:
        raise HTTPException(404, detail={"error": "service_not_found"})
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(service, k, v)
    audit(
        db,
        action="service.update",
        actor_user_id=admin.id,
        target_type="service",
        target_id=str(service.id),
        service_id=service.id,
        ip=client_ip(request),
        fields=list(changes),
    )
    db.commit()
    return _service_out(service)


@router.post("/services/{slug}/roles", status_code=201)
def add_role(
    slug: str,
    body: RoleCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = db.scalar(select(Service).where(Service.slug == slug))
    if service is None:
        raise HTTPException(404, detail={"error": "service_not_found"})
    if db.scalar(
        select(ServiceRole).where(ServiceRole.service_id == service.id, ServiceRole.key == body.key)
    ):
        raise HTTPException(409, detail={"error": "role_exists"})
    role = ServiceRole(
        service_id=service.id,
        key=body.key,
        name=body.name,
        description=body.description,
        is_default=body.is_default,
    )
    db.add(role)
    db.flush()
    audit(
        db,
        action="service.role_create",
        actor_user_id=admin.id,
        target_type="service_role",
        target_id=str(role.id),
        service_id=service.id,
        ip=client_ip(request),
        key=role.key,
    )
    db.commit()
    return {"id": str(role.id), "key": role.key, "name": role.name, "description": role.description, "is_default": role.is_default}


@router.post("/services/{slug}/rotate-key")
def rotate_key(
    slug: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = db.scalar(select(Service).where(Service.slug == slug))
    if service is None:
        raise HTTPException(404, detail={"error": "service_not_found"})
    raw, digest = new_service_key()
    service.service_key_hash = digest
    audit(
        db,
        action="service.rotate_key",
        actor_user_id=admin.id,
        target_type="service",
        target_id=str(service.id),
        service_id=service.id,
        ip=client_ip(request),
    )
    db.commit()
    return {"service_key": raw}


# ── grants ────────────────────────────────────────────────────────────────────
@router.get("/grants")
def list_grants(
    service: str | None = Query(None),
    user: uuid.UUID | None = Query(None),
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    q = select(Grant)
    if service:
        q = q.join(Service, Grant.service_id == Service.id).where(Service.slug == service)
    if user:
        q = q.where(Grant.user_id == user)
    grants = db.scalars(q).all()
    return {"grants": [_grant_out(db, g) for g in grants]}


@router.post("/grants", status_code=201)
def create_grant(
    body: GrantCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = db.scalar(select(Service).where(Service.slug == body.slug))
    if service is None:
        raise HTTPException(404, detail={"error": "service_not_found"})
    role = db.scalar(
        select(ServiceRole).where(ServiceRole.service_id == service.id, ServiceRole.key == body.role)
    )
    if role is None:
        raise HTTPException(404, detail={"error": "role_not_found"})
    if db.scalar(
        select(Grant).where(Grant.user_id == body.user_id, Grant.service_id == service.id)
    ):
        raise HTTPException(409, detail={"error": "grant_exists"})
    grant = Grant(
        user_id=body.user_id,
        service_id=service.id,
        service_role_id=role.id,
        granted_by=admin.id,
        reason=body.reason,
        expires_at=body.expires_at,
    )
    db.add(grant)
    db.flush()
    audit(
        db,
        action="grant.create",
        actor_user_id=admin.id,
        target_type="grant",
        target_id=str(grant.id),
        service_id=service.id,
        ip=client_ip(request),
        user_id=str(body.user_id),
        role=body.role,
    )
    db.commit()
    return _grant_out(db, grant)


@router.delete("/grants/{id}")
def delete_grant(
    id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    grant = db.get(Grant, id)
    if grant is None:
        raise HTTPException(404, detail={"error": "grant_not_found"})
    user = db.get(User, grant.user_id)
    now = datetime.now(timezone.utc)
    # Same transaction as the delete — access removal is never a two-step that can
    # half-fail (docs/03-api-contract.md, "Rules that hold everywhere").
    db.add(
        Revocation(
            subject=user.subject,
            service_id=grant.service_id,
            reason="grant_removed",
            revoked_by=admin.id,
            revoked_at=now,
            purge_after=now + _REVOCATION_TTL,
        )
    )
    audit(
        db,
        action="grant.delete",
        actor_user_id=admin.id,
        target_type="grant",
        target_id=str(grant.id),
        service_id=grant.service_id,
        ip=client_ip(request),
    )
    db.delete(grant)
    db.commit()
    return {"ok": True}


@router.post("/grants/bulk")
def bulk_grants(
    body: GrantBulk,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = db.scalar(select(Service).where(Service.slug == body.slug))
    if service is None:
        raise HTTPException(404, detail={"error": "service_not_found"})
    role = db.scalar(
        select(ServiceRole).where(ServiceRole.service_id == service.id, ServiceRole.key == body.role)
    )
    if role is None:
        raise HTTPException(404, detail={"error": "role_not_found"})

    q = select(User).join(Employee, User.employee_id == Employee.id)
    if body.band:
        q = q.where(Employee.band.in_(body.band))
    if body.department:
        q = q.where(Employee.hr_department.in_(body.department))
    users = db.scalars(q).all()

    existing: set[uuid.UUID] = set()
    if users:
        existing = {
            g.user_id
            for g in db.scalars(
                select(Grant).where(
                    Grant.service_id == service.id, Grant.user_id.in_([u.id for u in users])
                )
            ).all()
        }

    created = 0
    for u in users:
        if u.id in existing:
            continue
        db.add(
            Grant(
                user_id=u.id,
                service_id=service.id,
                service_role_id=role.id,
                granted_by=admin.id,
                reason=body.reason,
            )
        )
        created += 1

    audit(
        db,
        action="grant.bulk_create",
        actor_user_id=admin.id,
        target_type="service",
        target_id=str(service.id),
        service_id=service.id,
        ip=client_ip(request),
        created=created,
        band=body.band,
        department=body.department,
    )
    db.commit()
    return {"created": created, "skipped": len(users) - created}


# ── LLM control plane ──────────────────────────────────────────────────────────
@router.get("/llm")
def llm_overview(admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    cutoff = date.today() - timedelta(days=30)
    regs = db.scalars(select(LlmRegistration)).all()
    out = []
    for reg in regs:
        usage = db.scalars(
            select(LlmUsageDaily)
            .where(LlmUsageDaily.service_id == reg.service_id, LlmUsageDaily.day >= cutoff)
            .order_by(LlmUsageDaily.day)
        ).all()
        service = db.get(Service, reg.service_id)
        out.append(
            {
                "slug": service.slug if service else None,
                # `name` added by B1 -- the LLM page needs to show a human label, not just
                # a slug, and this list is the one place that already has the join.
                "name": service.name if service else None,
                "provider": reg.provider,
                "model": reg.model,
                "key_present": reg.key_present,
                "enabled": reg.enabled,
                "disabled_reason": reg.disabled_reason,
                "last_seen_at": reg.last_seen_at.isoformat() if reg.last_seen_at else None,
                # renamed usage -> usage_30d by B1 to match the window it actually covers
                # (`cutoff = today - 30 days` above) -- see handoff/b1-assembly.md.
                "usage_30d": [
                    {
                        "day": u.day.isoformat(),
                        "requests": u.requests,
                        "input_tokens": int(u.input_tokens),
                        "output_tokens": int(u.output_tokens),
                    }
                    for u in usage
                ],
            }
        )
    return {"registrations": out}


@router.post("/llm/{slug}/toggle")
def toggle_llm(
    slug: str,
    body: LlmToggle,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = db.scalar(select(Service).where(Service.slug == slug))
    if service is None:
        raise HTTPException(404, detail={"error": "service_not_found"})
    reg = db.scalar(select(LlmRegistration).where(LlmRegistration.service_id == service.id))
    if reg is None:
        reg = LlmRegistration(service_id=service.id, provider="unreported")
        db.add(reg)
        db.flush()

    reg.enabled = body.enabled
    if body.enabled:
        reg.disabled_by = None
        reg.disabled_at = None
        reg.disabled_reason = None
    else:
        reg.disabled_by = admin.id
        reg.disabled_at = datetime.now(timezone.utc)
        reg.disabled_reason = body.reason

    # `llm.disable` is the action named explicitly in the brief; `llm.enable` mirrors it
    # for the other direction so config_version (derived from this audit trail) bumps
    # symmetrically both ways — see handoff Assumptions.
    action = "llm.enable" if body.enabled else "llm.disable"
    audit(
        db,
        action=action,
        actor_user_id=admin.id,
        target_type="service",
        target_id=str(service.id),
        service_id=service.id,
        ip=client_ip(request),
        reason=body.reason,
    )
    db.commit()
    return {"enabled": reg.enabled, "config_version": _config_version(db, service)}


# ── audit log ──────────────────────────────────────────────────────────────────
@router.get("/audit")
def list_audit(
    actor: uuid.UUID | None = Query(None),
    action: str | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(50),
    cursor: str | None = Query(None),
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    q = select(AuditLog)
    if actor:
        q = q.where(AuditLog.actor_user_id == actor)
    if action:
        q = q.where(AuditLog.action == action)
    if date_from:
        q = q.where(AuditLog.created_at >= date_from)
    if date_to:
        q = q.where(AuditLog.created_at <= date_to)
    if cursor:
        try:
            c_created, c_id = _decode_cursor(cursor)
        except Exception:
            raise HTTPException(400, detail={"error": "bad_cursor"})
        q = q.where(
            or_(
                AuditLog.created_at < c_created,
                and_(AuditLog.created_at == c_created, AuditLog.id < c_id),
            )
        )
    q = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    rows = db.scalars(q).all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    # `actor`/`service` names added by B1 -- docs/08-v1-plan.md's v1 definition of done #6
    # ("audit_log answers who granted what, to whom, when") needs a human name, not just the
    # id this used to return alone. Batched rather than per-row to avoid an N+1 query over a
    # page of up to 200 rows.
    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    service_ids = {r.service_id for r in rows if r.service_id}
    actor_names: dict[uuid.UUID, str | None] = {}
    if actor_ids:
        for uid in actor_ids:
            emp = _employee_of(db, uid)
            actor_names[uid] = emp.full_name if emp else None
    services_by_id: dict[uuid.UUID, Service] = {}
    if service_ids:
        for svc in db.scalars(select(Service).where(Service.id.in_(service_ids))).all():
            services_by_id[svc.id] = svc

    return {
        "entries": [
            {
                "id": str(r.id),
                "actor": (
                    {"id": str(r.actor_user_id), "name": actor_names.get(r.actor_user_id)}
                    if r.actor_user_id
                    else None
                ),
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "service": (
                    {
                        "slug": services_by_id[r.service_id].slug if r.service_id in services_by_id else None,
                        "name": services_by_id[r.service_id].name if r.service_id in services_by_id else None,
                    }
                    if r.service_id
                    else None
                ),
                "ip": r.ip,
                "metadata": r.metadata_,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


# ── emergency kill ──────────────────────────────────────────────────────────────
@router.post("/users/{id}/kill")
def kill_user(
    id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    user = db.get(User, id)
    if user is None:
        raise HTTPException(404, detail={"error": "user_not_found"})

    now = datetime.now(timezone.utc)
    # Subject-level: global, blocks every service's verification of this user at once.
    db.add(
        Revocation(
            subject=user.subject,
            service_id=None,
            reason="admin_kill",
            revoked_by=admin.id,
            revoked_at=now,
            purge_after=now + _REVOCATION_TTL,
        )
    )
    # jti-level, defence in depth: also kill any token we know we issued recently, in
    # case a service matches purely on jti. Recent issuance is read back from audit_log
    # since MM OS does not otherwise keep a table of live jtis.
    recent_cutoff = now - timedelta(seconds=settings().service_token_ttl_seconds)
    recent_issues = db.scalars(
        select(AuditLog).where(
            AuditLog.actor_user_id == id,
            AuditLog.action == "token.issue",
            AuditLog.created_at >= recent_cutoff,
        )
    ).all()
    for entry in recent_issues:
        jti = (entry.metadata_ or {}).get("jti")
        if jti:
            db.add(
                Revocation(
                    subject=user.subject,
                    service_id=entry.service_id,
                    jti=jti,
                    reason="admin_kill",
                    revoked_by=admin.id,
                    revoked_at=now,
                    purge_after=now + _REVOCATION_TTL,
                )
            )

    audit(
        db,
        action="user.kill",
        actor_user_id=admin.id,
        target_type="user",
        target_id=str(id),
        ip=client_ip(request),
    )
    db.commit()
    return {"ok": True}
