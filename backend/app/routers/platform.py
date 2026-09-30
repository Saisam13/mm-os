"""Owned by A2 — Tokens and Control Plane. See docs/09-build-agents.md.

Admin surface for the service registry, grants, the LLM control plane and the audit log.
Every route here sits behind `require_admin`. Mounted at `/api/admin` by `app/main.py`.
"""
from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session as OrmSession

from .. import access_contract
from ..config import settings
from ..db import get_db
from ..deps import CAPABILITIES, audit, client_ip, current_user, has_capability, require_admin, require_capability
from ..llm_control import (
    LlmFeature,
    LlmFeatureUsageDaily,
    get_or_create_feature,
    service_llm_enabled,
)
from ..models import (
    AuditLog,
    AgentIdentity,
    Department,
    Employee,
    Grant,
    LlmRegistration,
    LlmUsageDaily,
    Revocation,
    Service,
    ServiceRole,
    User,
    UserCapability,
)
from ..roles_io import RoleFileError, revoke_role_holders
from ..roles_io import committed as committed_role_file
from ..roles_io import apply as apply_role_file
from ..roles_io import export as export_role_file
from ..roles_io import validate as validate_role_file
from ..security import new_service_key, permissions_version
from .agent import _config_version
from .tokens import live_grants, token_access


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
    permissions: list[str] = []


class RolePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None
    permissions: list[str] | None = None


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
    preview: bool = False


class GrantBatch(BaseModel):
    user_id: uuid.UUID
    services: list[dict]
    reason: str | None = None


class CapabilityChange(BaseModel):
    capability: str
    scope_department_id: uuid.UUID | None = None


class AgentCreate(BaseModel):
    name: str
    slug: str
    kind: str = "agent"
    service_id: uuid.UUID | None = None


class LlmToggle(BaseModel):
    enabled: bool
    reason: str | None = None


class LlmFeatureToggle(BaseModel):
    enabled: bool
    reason: str | None = None


class LlmFeaturePolicy(BaseModel):
    allowed_providers: list[str] | None = None
    allowed_models: list[str] | None = None
    provider: str | None = None
    model: str | None = None
    reason: str | None = None


# ── output shaping ───────────────────────────────────────────────────────────
def _service_out(s: Service, include_icon: bool = False) -> dict:
    data = {
        "id": str(s.id),
        "slug": s.slug,
        "name": s.name,
        "tagline": s.tagline,
        "category": s.category,
        "base_url": s.base_url,
        "launch_mode": s.launch_mode,
        "has_public_surface": s.has_public_surface,
        "public_url": s.public_url,
        "health_url": s.health_url,
        "is_active": s.is_active,
        "sort_order": s.sort_order,
        "permission_catalog": dict(s.permission_catalog or {}),
        "roles": [
            _role_out(r)
            for r in s.roles
        ],
    }
    if include_icon:
        data["icon"] = s.icon
    return data


def _role_out(r: ServiceRole) -> dict:
    return {
        "id": str(r.id), "key": r.key, "name": r.name, "description": r.description,
        "is_default": r.is_default, "permissions": list(r.permissions or []),
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
        "origin": g.origin,
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
def list_services(admin: User = Depends(current_user), db: OrmSession = Depends(get_db)):
    if not admin.is_platform_admin and not any(has_capability(db, admin, cap) for cap in (
        "grants.view", "grants.add", "people.create", "hr_onboarding.create"
    )):
        raise HTTPException(403, detail={"error": "capability_required"})
    services = db.scalars(select(Service).order_by(Service.sort_order, Service.name)).all()
    return {"services": [_service_out(s) for s in services]}


@router.get("/services/reachability")
async def services_reachability(
    admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    """Can each registered service actually be opened?

    Every launch URL MM OS mints is `{base_url}/_mmos/accept#token=…`, so a `base_url`
    pointing somewhere the service no longer lives makes sign-in fail with no error anyone
    can see — the browser simply ends up back here. That is what happened on 7 Sep, when the
    m-mines.com subdomains stopped resolving to the VPS: the registry still held perfectly
    well-formed https URLs, the services themselves were healthy on their own hostnames, and
    the only symptom was users bouncing back to the MM OS home page.

    This asks each `base_url` the question the browser will ask. `external` services run
    their own session and expose no `/_mmos/health`, so they are only checked for liveness.
    See docs/16-decisions.md D-2026-09-07-3.
    """
    # Read the registry fully before any await: the session is sync and must not be held
    # open across the probes, which take seconds when a host is black-holing packets.
    services = [
        {"slug": s.slug, "name": s.name, "base_url": s.base_url,
         "launch_mode": s.launch_mode, "is_active": s.is_active}
        for s in db.scalars(select(Service).order_by(Service.sort_order, Service.name))
    ]

    async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as http:
        results = await asyncio.gather(*(_probe_service(http, s) for s in services))

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "unreachable": sum(1 for r in results if not r["reachable"]),
        "services": results,
    }


async def _probe_service(http: httpx.AsyncClient, svc: dict) -> dict:
    out = {**svc, "reachable": False, "detail": None, "os_url": None, "issuer": None}
    external = svc["launch_mode"] == "external"
    url = svc["base_url"].rstrip("/") + ("/" if external else "/_mmos/health")

    try:
        resp = await http.get(url)
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never raises
        out["detail"] = f"{type(exc).__name__}: {exc}"
        return out

    if resp.status_code >= 400:
        out["detail"] = f"HTTP {resp.status_code}"
        return out

    if external:
        out["reachable"] = True
        return out

    if "json" not in resp.headers.get("content-type", ""):
        # A parked host, or the wrong app entirely, answers 200 with HTML. That is a broken
        # pointer, not a healthy service, and saying so is the whole point of this route.
        out["detail"] = f"not an MM OS service here — got {resp.headers.get('content-type') or 'no content-type'}"
        return out

    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        out["detail"] = "response was not valid JSON"
        return out

    # The service tells us what IT thinks it is pointed at. A slug mismatch means two
    # registry rows have been crossed; an unreachable os means the service is up but nobody
    # can sign into it, which is a different failure from this one and worth separating.
    reported_slug = body.get("slug")
    if reported_slug and reported_slug != svc["slug"]:
        out["detail"] = f"that URL is the '{reported_slug}' service, not '{svc['slug']}'"
        return out

    os_info = body.get("os") or {}
    out["os_url"] = os_info.get("url")
    out["issuer"] = os_info.get("issuer")
    if os_info and os_info.get("reachable") is False:
        out["detail"] = f"service is up but cannot reach MM OS: {os_info.get('error')}"
        return out

    out["reachable"] = True
    return out


# ── access contract (docs/17-access-contract.md) ─────────────────────────────
@router.get("/services/contract")
async def services_contract(admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    """Does each service follow the access contract, and does its declared permission list
    match the one MM OS holds? One manifest fetch per service, in parallel."""
    services = list(db.scalars(select(Service).order_by(Service.sort_order, Service.name)))
    results = await access_contract.check_services(services)
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "services": results}


@router.get("/services/{slug}/contract")
async def service_contract(slug: str, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    result, _ = await access_contract.check_service(_service_or_404(db, slug))
    return result


@router.get("/services/{slug}/roles/from-service")
async def role_file_from_service(slug: str, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    """A role-file draft built from the service's own manifest. Writes nothing: the admin
    reviews it through the ordinary dry-run import (POST .../roles/import) and applies it
    from there."""
    service = _service_or_404(db, slug)
    list(service.roles)  # load before the await; the draft reads them afterwards
    result, manifest = await access_contract.check_service(service)
    if manifest is None:
        unreachable = result["status"] == access_contract.UNREACHABLE
        raise HTTPException(502 if unreachable else 422, detail={
            "error": result["status"],
            "message": (f"Could not reach {service.name} to read its permission list"
                        if unreachable else
                        f"{service.name} does not publish a permission list MM OS can read")
                       + (f" ({result['detail']})." if result["detail"] else "."),
        })
    file, notes = access_contract.draft_role_file(service, manifest)
    return {"contract": result, "file": file, "notes": notes}


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
    return _service_out(service, include_icon=True)


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
    return _service_out(service, include_icon=True)


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
    _check_permissions(service, body.permissions)
    if body.is_default:
        _clear_default(service)
    role = ServiceRole(
        service_id=service.id,
        key=body.key,
        name=body.name,
        description=body.description,
        is_default=body.is_default,
        permissions=list(dict.fromkeys(body.permissions)),
        sort_order=max((r.sort_order for r in service.roles), default=0) + 10,
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
    return _role_out(role)


def _check_permissions(service: Service, perms: list[str]) -> None:
    catalog = service.permission_catalog or {}
    unknown = [p for p in perms if p not in catalog]
    if unknown:
        raise HTTPException(422, detail={
            "error": "unknown_permission",
            "message": f"Not in {service.slug}'s permission list: {', '.join(unknown)}. "
                       "Import a role file to declare new permissions.",
        })
    if catalog and not perms:
        # docs/17-access-contract.md: a token with no permissions makes the service fall back
        # to its own idea of the role, so MM OS never hands one out for a declared service.
        raise HTTPException(422, detail={
            "error": "empty_permissions",
            "message": f"A {service.name} role must be allowed to do at least one thing. "
                       "Tick at least one permission.",
        })


def _clear_default(service: Service) -> None:
    for r in service.roles:
        r.is_default = False


def _role_or_404(db: OrmSession, service: Service, key: str) -> ServiceRole:
    role = db.scalar(
        select(ServiceRole).where(ServiceRole.service_id == service.id, ServiceRole.key == key)
    )
    if role is None:
        raise HTTPException(404, detail={"error": "role_not_found"})
    return role


@router.patch("/services/{slug}/roles/{key}")
def patch_role(
    slug: str,
    key: str,
    body: RolePatch,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = _service_or_404(db, slug)
    role = _role_or_404(db, service, key)
    changes = body.model_dump(exclude_unset=True)
    if "permissions" in changes:
        changes["permissions"] = changes["permissions"] or []
        _check_permissions(service, changes["permissions"])
        changes["permissions"] = list(dict.fromkeys(changes["permissions"]))
    if changes.get("is_default"):
        _clear_default(service)
    perms_changed = "permissions" in changes and list(role.permissions or []) != changes["permissions"]
    for k, v in changes.items():
        setattr(role, k, v)
    if perms_changed:
        # Holders' live sessions carry the old permission list; send them back through MM OS.
        revoke_role_holders(db, role, actor=admin, reason="role_permissions_changed")
    audit(
        db,
        action="service.role_update",
        actor_user_id=admin.id,
        target_type="service_role",
        target_id=str(role.id),
        service_id=service.id,
        ip=client_ip(request),
        key=role.key,
        fields=list(changes),
    )
    db.commit()
    return _role_out(role)


@router.delete("/services/{slug}/roles/{key}")
def delete_role(
    slug: str,
    key: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    service = _service_or_404(db, slug)
    role = _role_or_404(db, service, key)
    held = db.scalar(select(Grant.id).where(Grant.service_role_id == role.id).limit(1))
    if held:
        raise HTTPException(409, detail={
            "error": "role_in_use",
            "message": "People still hold this role. Move them to another role first "
                       "(a role file's 'replaces' does it in one step).",
        })
    audit(
        db,
        action="service.role_delete",
        actor_user_id=admin.id,
        target_type="service_role",
        target_id=str(role.id),
        service_id=service.id,
        ip=client_ip(request),
        key=role.key,
    )
    db.delete(role)
    db.commit()
    return {"ok": True}


@router.get("/services/{slug}/roles/export")
def export_roles(
    slug: str, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    return export_role_file(_service_or_404(db, slug))


@router.get("/services/{slug}/roles/template")
def role_file_template(
    slug: str, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    """The role file committed for this service (app/role_files/), or the current state
    exported as a starting point when there is none."""
    service = _service_or_404(db, slug)
    doc = committed_role_file(slug)
    return {"committed": doc is not None, "file": doc if doc is not None else export_role_file(service)}


@router.post("/services/{slug}/roles/import")
def import_roles(
    slug: str,
    body: dict,
    request: Request,
    dry_run: bool = Query(True),
    assign_mode: str | None = Query(None, pattern="^(missing|all)$"),
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    """Apply a role file (app/roles_io.py). Defaults to a dry run: the whole import runs
    against real rows and is then rolled back, so the preview is exactly what `dry_run=false`
    will do."""
    service = _service_or_404(db, slug)
    try:
        doc = validate_role_file(body, slug=slug)
    except RoleFileError as e:
        raise HTTPException(422, detail={
            "error": "invalid_role_file", "message": "The role file has problems.", "problems": e.problems,
        })
    plan = apply_role_file(db, service, doc, actor=admin, dry_run=dry_run, assign_mode=assign_mode)
    if dry_run:
        db.rollback()
        return {"dry_run": True, **plan.as_dict()}
    audit(
        db,
        action="service.roles_import",
        actor_user_id=admin.id,
        target_type="service",
        target_id=str(service.id),
        service_id=service.id,
        ip=client_ip(request),
        roles_created=plan.roles_created,
        roles_updated=plan.roles_updated,
        roles_removed=plan.roles_removed,
        grants_moved=len(plan.grants_moved),
        grants_created=len(plan.grants_created),
        grants_changed=len(plan.grants_changed),
    )
    db.commit()
    db.refresh(service)
    return {"dry_run": False, **plan.as_dict(), "service_after": _service_out(service, include_icon=True)}


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


# ── view as ───────────────────────────────────────────────────────────────────
@router.get("/people/{user_id}/access")
def person_access(user_id: uuid.UUID, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    """What each service would receive for this person: roles, permissions and `pv`, computed
    by the same code the token handoff uses (routers/tokens.py) without minting anything.
    `contract` is the last access-contract check of that service in this worker, or None."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail={"error": "user_not_found"})
    emp = db.get(Employee, user.employee_id)
    service_ids = set(db.scalars(select(Grant.service_id).where(Grant.user_id == user.id)))
    services = db.scalars(
        select(Service).where(Service.id.in_(service_ids)).order_by(Service.sort_order, Service.name)
    ) if service_ids else []
    rows = []
    for service in services:
        grants = live_grants(db, user.id, service)
        if not grants:
            continue
        roles, permissions = token_access(grants)
        last = access_contract.last_result(service.slug)
        rows.append({
            "slug": service.slug,
            "name": service.name,
            "is_active": service.is_active,
            "roles": roles,
            "permissions": permissions,
            "pv": permissions_version(permissions),
            "contract": {"status": last["status"], "checked_at": last["checked_at"]} if last else None,
        })
    return {
        "user_id": str(user.id),
        "can_sign_in": bool(user.is_active and emp is not None and emp.status == "active"),
        "services": rows,
    }


# ── grants ────────────────────────────────────────────────────────────────────
@router.get("/grants")
def list_grants(
    service: str | None = Query(None),
    user: uuid.UUID | None = Query(None),
    admin: User = Depends(require_capability("grants.view")),
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
    admin: User = Depends(require_capability("grants.add")),
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
        select(Grant).where(Grant.user_id == body.user_id, Grant.service_id == service.id,
                            Grant.service_role_id == role.id)
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
    admin: User = Depends(require_capability("grants.revoke")),
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
        action="grant.revoke",
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
    admin: User = Depends(require_capability("grants.add")),
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
                    Grant.service_id == service.id, Grant.service_role_id == role.id,
                    Grant.user_id.in_([u.id for u in users])
                )
            ).all()
        }

    if body.preview:
        return {"preview": True, "valid": True, "would_create": len(users) - len(existing),
                "would_skip": len(existing), "errors": []}

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


@router.post("/grants/batch")
def batch_grants(
    body: GrantBatch,
    request: Request,
    actor: User = Depends(current_user),
    db: OrmSession = Depends(get_db),
):
    """Add or replace several services' roles for one human in one transaction."""
    if not has_capability(db, actor, "grants.add"):
        raise HTTPException(403, detail={"error": "capability_required"})
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(404, detail={"error": "user_not_found"})

    validated: list[tuple[Service, list[ServiceRole], bool]] = []
    for item in body.services:
        slug = item.get("service_slug") or item.get("slug")
        service = db.scalar(select(Service).where(Service.slug == slug, Service.is_active.is_(True)))
        keys = item.get("roles") or []
        if service is None or not keys:
            raise HTTPException(422, detail={"error": "invalid_service_role", "service": slug})
        roles = list(db.scalars(select(ServiceRole).where(
            ServiceRole.service_id == service.id, ServiceRole.key.in_(keys)
        )))
        if len({r.key for r in roles}) != len(set(keys)):
            raise HTTPException(422, detail={"error": "invalid_service_role", "service": slug})
        replace = bool(item.get("replace", False))
        if replace and (not has_capability(db, actor, "grants.change") or
                        not has_capability(db, actor, "grants.revoke")):
            raise HTTPException(403, detail={"error": "capability_required"})
        validated.append((service, roles, replace))

    created = revoked = 0
    now = datetime.now(timezone.utc)
    for service, roles, replace in validated:
        existing = list(db.scalars(select(Grant).where(
            Grant.user_id == user.id, Grant.service_id == service.id
        )))
        wanted = {r.id for r in roles}
        if replace:
            for grant in existing:
                if grant.service_role_id not in wanted:
                    db.delete(grant)
                    revoked += 1
            if any(g.service_role_id not in wanted for g in existing):
                db.add(Revocation(subject=user.subject, service_id=service.id,
                                  reason="grant_roles_changed", revoked_by=actor.id,
                                  revoked_at=now, purge_after=now + _REVOCATION_TTL))
        have = {g.service_role_id for g in existing if not replace or g.service_role_id in wanted}
        for role in roles:
            if role.id in have:
                continue
            grant = Grant(user_id=user.id, service_id=service.id, service_role_id=role.id,
                          granted_by=actor.id, reason=body.reason, origin="manual")
            db.add(grant)
            db.flush()
            created += 1
            audit(db, action="grant.create", actor_user_id=actor.id, target_type="grant",
                  target_id=grant.id, service_id=service.id, role=role.key)
        if replace:
            audit(db, action="grant.roles_change", actor_user_id=actor.id, target_type="user",
                  target_id=user.id, service_id=service.id, roles=sorted(r.key for r in roles))
    db.commit()
    return {"created": created, "revoked": revoked, "grants": [
        _grant_out(db, g) for g in db.scalars(select(Grant).where(Grant.user_id == user.id)).all()
    ]}


# ── delegated administration ─────────────────────────────────────────────────
@router.get("/capabilities")
def list_capabilities(
    actor: User = Depends(require_capability("admin_roles.manage")),
    db: OrmSession = Depends(get_db),
):
    rows = db.scalars(select(UserCapability)).all()
    return {"available": sorted(CAPABILITIES), "assignments": [{
        "id": str(row.id), "user_id": str(row.user_id), "capability": row.capability,
        "scope_department_id": str(row.scope_department_id) if row.scope_department_id else None,
        "granted_by": str(row.granted_by) if row.granted_by else None,
    } for row in rows]}


@router.post("/users/{user_id}/capabilities", status_code=201)
def grant_capability(
    user_id: uuid.UUID,
    body: CapabilityChange,
    request: Request,
    actor: User = Depends(require_capability("admin_roles.manage")),
    db: OrmSession = Depends(get_db),
):
    if body.capability not in CAPABILITIES:
        raise HTTPException(422, detail={"error": "unknown_capability"})
    if not actor.is_platform_admin and not has_capability(db, actor, body.capability):
        raise HTTPException(403, detail={"error": "delegation_escalation"})
    if db.get(User, user_id) is None:
        raise HTTPException(404, detail={"error": "user_not_found"})
    if body.scope_department_id and db.get(Department, body.scope_department_id) is None:
        raise HTTPException(422, detail={"error": "invalid_department"})
    existing = db.scalar(select(UserCapability).where(
        UserCapability.user_id == user_id,
        UserCapability.capability == body.capability,
        UserCapability.scope_department_id == body.scope_department_id,
    ))
    if existing:
        return {"id": str(existing.id), "capability": existing.capability}
    row = UserCapability(user_id=user_id, capability=body.capability,
                         scope_department_id=body.scope_department_id, granted_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, action="admin.capability_grant", actor_user_id=actor.id, target_type="user",
          target_id=user_id, ip=client_ip(request), capability=body.capability)
    db.commit()
    return {"id": str(row.id), "capability": row.capability}


@router.delete("/capabilities/{assignment_id}")
def revoke_capability(
    assignment_id: uuid.UUID,
    request: Request,
    actor: User = Depends(require_capability("admin_roles.manage")),
    db: OrmSession = Depends(get_db),
):
    row = db.get(UserCapability, assignment_id)
    if row is None:
        raise HTTPException(404, detail={"error": "capability_not_found"})
    if not actor.is_platform_admin and not has_capability(db, actor, row.capability):
        raise HTTPException(403, detail={"error": "delegation_escalation"})
    audit(db, action="admin.capability_revoke", actor_user_id=actor.id, target_type="user",
          target_id=row.user_id, ip=client_ip(request), capability=row.capability)
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── machine identities (never returned by People APIs) ───────────────────────
@router.get("/agents")
def list_agents(
    actor: User = Depends(require_capability("agents.manage")),
    db: OrmSession = Depends(get_db),
):
    rows = db.scalars(select(AgentIdentity).order_by(AgentIdentity.name)).all()
    return {"agents": [{"id": str(a.id), "name": a.name, "slug": a.slug,
                        "kind": a.kind, "service_id": str(a.service_id) if a.service_id else None,
                        "is_active": a.is_active, "created_at": a.created_at.isoformat()}
                       for a in rows]}


@router.post("/agents", status_code=201)
def create_agent(
    body: AgentCreate,
    request: Request,
    actor: User = Depends(require_capability("agents.manage")),
    db: OrmSession = Depends(get_db),
):
    if body.kind not in {"agent", "automation", "integration"}:
        raise HTTPException(422, detail={"error": "invalid_agent_kind"})
    if db.scalar(select(AgentIdentity).where(AgentIdentity.slug == body.slug)):
        raise HTTPException(409, detail={"error": "agent_exists"})
    row = AgentIdentity(**body.model_dump())
    db.add(row)
    db.flush()
    audit(db, action="agent.create", actor_user_id=actor.id, target_type="agent",
          target_id=row.id, ip=client_ip(request), kind=row.kind)
    db.commit()
    return {"id": str(row.id), "name": row.name, "slug": row.slug, "kind": row.kind,
            "service_id": str(row.service_id) if row.service_id else None, "is_active": row.is_active}


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


# ── LLM control plane: per-feature governance (INT-5) ────────────────────────────
def _feature_out(db: OrmSession, feature: LlmFeature, *, service_enabled: bool) -> dict:
    cutoff = date.today() - timedelta(days=30)
    usage = db.scalars(
        select(LlmFeatureUsageDaily)
        .where(LlmFeatureUsageDaily.feature_id == feature.id, LlmFeatureUsageDaily.day >= cutoff)
        .order_by(LlmFeatureUsageDaily.day)
    ).all()
    return {
        "feature_key": feature.feature_key,
        "name": feature.name,
        "provider": feature.provider,
        "model": feature.model,
        "allowed_providers": list(feature.allowed_providers or []),
        "allowed_models": list(feature.allowed_models or []),
        "feature_enabled": feature.enabled,
        # Effective = service kill switch AND feature kill switch; what the service actually sees.
        "enabled": bool(service_enabled and feature.enabled),
        "disabled_reason": feature.disabled_reason,
        "last_seen_at": feature.last_seen_at.isoformat() if feature.last_seen_at else None,
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


def _service_or_404(db: OrmSession, slug: str) -> Service:
    service = db.scalar(select(Service).where(Service.slug == slug))
    if service is None:
        raise HTTPException(404, detail={"error": "service_not_found"})
    return service


def _feature_or_404(db: OrmSession, service: Service, feature_key: str) -> LlmFeature:
    feature = db.scalar(
        select(LlmFeature).where(
            LlmFeature.service_id == service.id, LlmFeature.feature_key == feature_key
        )
    )
    if feature is None:
        raise HTTPException(404, detail={"error": "llm_feature_not_found"})
    return feature


@router.get("/llm/features")
def list_all_features(admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    """Every AI feature across every service, with its policy and 30-day usage -- the central
    view of everything AI that runs anywhere in the platform."""
    features = db.scalars(select(LlmFeature)).all()
    svc_enabled: dict = {}
    out = []
    for f in features:
        service = db.get(Service, f.service_id)
        if service is None:
            continue
        if service.id not in svc_enabled:
            svc_enabled[service.id] = service_llm_enabled(db, service)
        row = _feature_out(db, f, service_enabled=svc_enabled[service.id])
        row["slug"] = service.slug
        row["service_name"] = service.name
        out.append(row)
    return {"features": out}


@router.get("/llm/{slug}/features")
def list_service_features(
    slug: str, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    service = _service_or_404(db, slug)
    svc_enabled = service_llm_enabled(db, service)
    features = db.scalars(
        select(LlmFeature).where(LlmFeature.service_id == service.id).order_by(LlmFeature.feature_key)
    ).all()
    return {
        "slug": service.slug,
        "name": service.name,
        "llm_enabled": svc_enabled,
        "features": [_feature_out(db, f, service_enabled=svc_enabled) for f in features],
    }


@router.post("/llm/{slug}/features/{feature_key}/toggle")
def toggle_feature(
    slug: str,
    feature_key: str,
    body: LlmFeatureToggle,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    """Per-feature kill switch. Independent of the service-level toggle -- the effective state
    a service sees is the AND of the two, so IT can kill one feature without touching the
    others."""
    service = _service_or_404(db, slug)
    feature = _feature_or_404(db, service, feature_key)
    feature.enabled = body.enabled
    if body.enabled:
        feature.disabled_by = None
        feature.disabled_at = None
        feature.disabled_reason = None
    else:
        feature.disabled_by = admin.id
        feature.disabled_at = datetime.now(timezone.utc)
        feature.disabled_reason = body.reason
    action = "llm.feature.enable" if body.enabled else "llm.feature.disable"
    audit(
        db, action=action, actor_user_id=admin.id, target_type="llm_feature",
        target_id=str(feature.id), service_id=service.id, ip=client_ip(request),
        feature_key=feature_key, reason=body.reason,
    )
    db.commit()
    return {
        "feature_key": feature.feature_key,
        "feature_enabled": feature.enabled,
        "enabled": bool(service_llm_enabled(db, service) and feature.enabled),
        "config_version": _config_version(db, service),
    }


@router.post("/llm/{slug}/features/{feature_key}/policy")
def set_feature_policy(
    slug: str,
    feature_key: str,
    body: LlmFeaturePolicy,
    request: Request,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    """Set the provider/model policy for one feature: the allowlist of providers/models it may
    use (empty list = unrestricted), and optionally pin the default provider/model. Auto-creates
    the feature row if an admin sets policy ahead of the service ever reporting it."""
    service = _service_or_404(db, slug)
    feature, _created = get_or_create_feature(db, service, feature_key)
    if body.allowed_providers is not None:
        feature.allowed_providers = list(body.allowed_providers)
    if body.allowed_models is not None:
        feature.allowed_models = list(body.allowed_models)
    if body.provider is not None:
        feature.provider = body.provider or None
    if body.model is not None:
        feature.model = body.model or None
    audit(
        db, action="llm.feature.policy", actor_user_id=admin.id, target_type="llm_feature",
        target_id=str(feature.id), service_id=service.id, ip=client_ip(request),
        feature_key=feature_key,
        allowed_providers=body.allowed_providers, allowed_models=body.allowed_models,
    )
    db.commit()
    return {
        "feature_key": feature.feature_key,
        "allowed_providers": list(feature.allowed_providers or []),
        "allowed_models": list(feature.allowed_models or []),
        "provider": feature.provider,
        "model": feature.model,
        "config_version": _config_version(db, service),
    }


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
