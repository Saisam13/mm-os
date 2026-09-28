"""Admin employee + user management. Owned by A1 (Identity). Everything here requires
`require_admin`. See docs/03-api-contract.md "Admin".
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..deps import audit, client_ip, current_user, has_capability, require_admin, require_capability
from ..models import Department, Employee, Grant, Revocation, Service, ServiceRole, Session, User, UserCapability
from ..seed import apply_diff, compute_diff, load_sheet_rows
from ..security import hash_pin

router = APIRouter()

EMPLOYEE_FIELDS = (
    "employee_code", "full_name", "work_email", "hr_department", "division",
    "job_title", "band", "approval_level", "manager_id", "is_approver",
    "notes", "status",
)
EMPLOYEE_PATCH_FIELDS = tuple(f for f in EMPLOYEE_FIELDS if f != "employee_code")


def _get_or_404(db: OrmSession, model, raw_id: str, error: str):
    try:
        pk = uuid.UUID(raw_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, {"error": error})
    obj = db.get(model, pk)
    if obj is None:
        raise HTTPException(404, {"error": error})
    return obj


def _employee_out(e: Employee) -> dict:
    return {
        "id": str(e.id),
        "employee_code": e.employee_code,
        "full_name": e.full_name,
        "work_email": e.work_email,
        "department_id": str(e.department_id) if e.department_id else None,
        "department": ({"id": str(e.department.id), "key": e.department.key, "name": e.department.name}
                       if e.department else None),
        "onboarding_ref": e.onboarding_ref,
        "hr_department": e.hr_department,
        "division": e.division,
        "job_title": e.job_title,
        "band": e.band,
        "approval_level": e.approval_level,
        "manager_id": str(e.manager_id) if e.manager_id else None,
        "is_approver": e.is_approver,
        "notes": e.notes,
        "status": e.status,
    }


def _department_out(d: Department) -> dict:
    return {"id": str(d.id), "key": d.key, "name": d.name, "is_active": d.is_active}


@router.get("/departments")
def list_departments(
    actor: User = Depends(current_user),
    db: OrmSession = Depends(get_db),
):
    if not any(has_capability(db, actor, cap) for cap in (
        "people.view", "people.create", "departments.assign", "hr_onboarding.create"
    )):
        raise HTTPException(403, {"error": "capability_required"})
    rows = db.scalars(select(Department).order_by(Department.name)).all()
    return {"departments": [_department_out(d) for d in rows]}


@router.post("/departments", status_code=201)
def create_department(
    body: dict, request: Request, actor: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    name = str(body.get("name", "")).strip()
    key = str(body.get("key", "")).strip().lower()
    if not name or not key:
        raise HTTPException(422, {"error": "missing_fields"})
    if db.scalar(select(Department).where(or_(Department.name == name, Department.key == key))):
        raise HTTPException(409, {"error": "department_exists"})
    row = Department(name=name, key=key)
    db.add(row); db.flush()
    audit(db, action="department.create", actor_user_id=actor.id, target_type="department",
          target_id=row.id, ip=client_ip(request))
    db.commit()
    return _department_out(row)


@router.patch("/departments/{department_id}")
def update_department(
    department_id: str, body: dict, request: Request,
    actor: User = Depends(require_admin), db: OrmSession = Depends(get_db),
):
    row = _get_or_404(db, Department, department_id, "department_not_found")
    if "name" in body:
        row.name = str(body["name"]).strip()
        for employee in db.scalars(select(Employee).where(Employee.department_id == row.id)):
            employee.hr_department = row.name
    if "is_active" in body:
        row.is_active = bool(body["is_active"])
    audit(db, action="department.update", actor_user_id=actor.id, target_type="department",
          target_id=row.id, ip=client_ip(request), fields=list(body))
    db.commit()
    return _department_out(row)


@router.post("/people", status_code=201)
def create_person(
    body: dict,
    request: Request,
    actor: User = Depends(current_user),
    db: OrmSession = Depends(get_db),
):
    """Create the employee, login and all requested grants as one transaction.

    HR-onboarding delegates may use this endpoint without becoming general administrators,
    but must supply a unique onboarding reference and stay inside their department scope.
    """
    can_create = has_capability(db, actor, "people.create")
    hr_create = has_capability(db, actor, "hr_onboarding.create")
    if not (can_create or hr_create):
        raise HTTPException(403, {"error": "capability_required", "message": "Requires people.create."})

    data = body.get("employee", body)
    required = ("employee_code", "full_name", "division", "job_title", "band", "department_id")
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise HTTPException(422, {"error": "missing_fields", "message": f"Required: {missing}"})
    try:
        department_id = uuid.UUID(str(data["department_id"]))
    except (ValueError, TypeError):
        raise HTTPException(422, {"error": "invalid_department"})
    department = db.get(Department, department_id)
    if department is None or not department.is_active:
        raise HTTPException(422, {"error": "invalid_department", "message": "Choose an active department."})

    onboarding_ref = data.get("onboarding_ref")
    if hr_create and not can_create:
        if not onboarding_ref:
            raise HTTPException(422, {"error": "onboarding_ref_required"})
        scoped = db.scalar(select(UserCapability.id).where(
            UserCapability.user_id == actor.id,
            UserCapability.capability == "hr_onboarding.create",
            UserCapability.scope_department_id == department.id,
        ))
        unscoped = db.scalar(select(UserCapability.id).where(
            UserCapability.user_id == actor.id,
            UserCapability.capability == "hr_onboarding.create",
            UserCapability.scope_department_id.is_(None),
        ))
        if scoped is None and unscoped is None:
            raise HTTPException(403, {"error": "department_scope_denied"})

    email = (data.get("work_email") or body.get("login_email") or "").strip().lower() or None
    employee_code = str(data["employee_code"]).strip()
    duplicate = db.scalar(select(Employee).where(or_(
        Employee.employee_code == employee_code,
        Employee.work_email == email if email else False,
        Employee.onboarding_ref == onboarding_ref if onboarding_ref else False,
    )))
    if duplicate:
        raise HTTPException(409, {"error": "identity_conflict", "message": "Employee code, email, or onboarding link already exists."})

    auth_type = body.get("auth_type", "google" if email else "local_pin")
    if auth_type not in {"google", "local_pin"}:
        raise HTTPException(422, {"error": "invalid_auth_type"})
    if auth_type == "google" and not email:
        raise HTTPException(422, {"error": "email_required"})

    # Validate every pair before adding anything, so malformed grants cannot partially land.
    grant_specs: list[tuple[Service, ServiceRole, dict]] = []
    for spec in body.get("grants", []):
        service = db.scalar(select(Service).where(Service.slug == spec.get("service_slug"), Service.is_active.is_(True)))
        if service is None:
            raise HTTPException(422, {"error": "invalid_service_role", "service": spec.get("service_slug")})
        roles = spec.get("roles") or ([spec["role"]] if spec.get("role") else [])
        if not roles:
            raise HTTPException(422, {"error": "roles_required", "service": service.slug})
        for role_key in roles:
            role = db.scalar(select(ServiceRole).where(ServiceRole.service_id == service.id, ServiceRole.key == role_key))
            if role is None:
                raise HTTPException(422, {"error": "invalid_service_role", "service": service.slug, "role": role_key})
            grant_specs.append((service, role, spec))
    if grant_specs and not has_capability(db, actor, "grants.add"):
        raise HTTPException(403, {"error": "capability_required", "message": "Requires grants.add."})

    emp = Employee(
        employee_code=employee_code, full_name=str(data["full_name"]).strip(),
        work_email=email, department_id=department.id, hr_department=department.name,
        onboarding_ref=onboarding_ref, division=data["division"], job_title=data["job_title"],
        band=data["band"], approval_level=data.get("approval_level"), notes=data.get("notes"),
        status=data.get("status", "active"), is_approver=bool(data.get("is_approver", False)),
    )
    db.add(emp)
    try:
        db.flush()
        user = User(
            employee_id=emp.id, login_email=email, auth_type=auth_type,
            pin_hash=hash_pin(f"{secrets.randbelow(1_000_000):06d}"), is_active=True,
        )
        db.add(user)
        db.flush()
        for service, role, spec in grant_specs:
            grant = Grant(user_id=user.id, service_id=service.id, service_role_id=role.id,
                          granted_by=actor.id, reason=spec.get("reason"), origin=spec.get("origin", "manual"))
            db.add(grant)
            db.flush()
            audit(db, action="grant.create", actor_user_id=actor.id, target_type="grant",
                  target_id=grant.id, service_id=service.id, role=role.key, origin=grant.origin)
        audit(db, action="person.create", actor_user_id=actor.id, target_type="employee",
              target_id=emp.id, ip=client_ip(request), onboarding_ref=bool(onboarding_ref),
              grants=len(grant_specs))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"error": "identity_conflict", "message": "Employee code, email, onboarding link, or grant already exists."})
    return {"employee": _employee_out(emp), "user": _user_out(user, emp), "grants_created": len(grant_specs)}


def _user_out(u: User, e: Employee) -> dict:
    return {
        "id": str(u.id),
        "employee_id": str(u.employee_id),
        "employee_code": e.employee_code,
        "full_name": e.full_name,
        "login_email": u.login_email,
        "auth_type": u.auth_type,
        "is_platform_admin": u.is_platform_admin,
        "is_active": u.is_active,
        # PIN login is keyed off pin_set_at, independent of auth_type -- a linked-Google
        # user still keeps pin_hash and can still PIN-login (see routers/auth.py).
        "pin_set": bool(u.pin_set_at),
        "locked": bool(u.locked_until and u.locked_until > datetime.now(timezone.utc)),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


# ── employees ────────────────────────────────────────────────────────────────
@router.get("/employees")
def list_employees(
    q: str | None = None,
    dept: str | None = None,
    status: str | None = None,
    limit: int = Query(50, le=200),
    cursor: str | None = None,
    admin: User = Depends(require_capability("people.view")),
    db: OrmSession = Depends(get_db),
):
    stmt = select(Employee).order_by(Employee.employee_code)
    if dept:
        stmt = stmt.where(Employee.hr_department == dept)
    if status:
        stmt = stmt.where(Employee.status == status)
    if cursor:
        stmt = stmt.where(Employee.employee_code > cursor)
    rows = list(db.scalars(stmt.limit(limit * 4 if q else limit)))
    if q:
        needle = q.lower()
        rows = [
            e for e in rows
            if needle in e.full_name.lower()
            or needle in e.employee_code.lower()
            or (e.work_email and needle in e.work_email.lower())
        ][:limit]
    next_cursor = rows[-1].employee_code if len(rows) == limit else None
    return {"employees": [_employee_out(e) for e in rows], "next_cursor": next_cursor}


@router.post("/employees")
def create_employee(body: dict, admin: User = Depends(require_capability("people.create")), db: OrmSession = Depends(get_db)):
    missing = [f for f in ("employee_code", "full_name", "hr_department", "division", "job_title", "band") if not body.get(f)]
    if missing:
        raise HTTPException(422, {"error": "missing_fields", "message": f"Required: {missing}"})

    emp = Employee(**{f: body.get(f) for f in EMPLOYEE_FIELDS if f in body})
    db.add(emp)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"error": "employee_conflict", "message": "Employee code or work email already exists."})

    audit(db, action="employee.create", actor_user_id=admin.id, target_type="employee", target_id=emp.id, ip=None)
    db.commit()
    return _employee_out(emp)


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: str, body: dict, request: Request, admin: User = Depends(require_capability("people.edit")), db: OrmSession = Depends(get_db)):
    emp = _get_or_404(db, Employee, employee_id, "employee_not_found")
    protected_status_change = (
        body.get("status") in {"suspended", "exited"} and emp.user
        and emp.user.is_platform_admin and emp.user.is_active
    )
    if protected_status_change:
        active_admins = db.scalar(select(func.count()).select_from(User).join(Employee).where(
            User.is_platform_admin.is_(True), User.is_active.is_(True), Employee.status == "active"
        )) or 0
        if not admin.is_platform_admin or active_admins <= 1:
            audit(db, action="admin.protected_attempt", actor_user_id=admin.id,
                  target_type="employee", target_id=emp.id, ip=client_ip(request), requested=list(body))
            db.commit()
            raise HTTPException(409 if admin.is_platform_admin else 403,
                                {"error": "protected_admin", "message": "An active IT Admin must remain."})
    if ("department_id" in body or "hr_department" in body) and not has_capability(db, admin, "departments.assign"):
        raise HTTPException(403, {"error": "capability_required", "message": "Requires departments.assign."})
    if "department_id" in body:
        try:
            department = db.get(Department, uuid.UUID(str(body["department_id"])))
        except (ValueError, TypeError):
            department = None
        if department is None or not department.is_active:
            raise HTTPException(422, {"error": "invalid_department"})
        emp.department_id = department.id
        emp.hr_department = department.name
    elif "hr_department" in body and body["hr_department"] != emp.hr_department:
        department = db.scalar(select(Department).where(Department.name == body["hr_department"], Department.is_active.is_(True)))
        if department is None:
            raise HTTPException(422, {"error": "invalid_department", "message": "Choose an existing department."})
        emp.department_id = department.id
    for f in EMPLOYEE_PATCH_FIELDS:
        if f in body:
            setattr(emp, f, body[f])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"error": "employee_conflict", "message": "Employee code or work email already exists."})

    audit(db, action="employee.update", actor_user_id=admin.id, target_type="employee", target_id=emp.id, fields=list(body))
    db.commit()
    return _employee_out(emp)


@router.post("/employees/import")
def import_employees(
    file: UploadFile,
    commit: bool = Query(False),
    admin: User = Depends(require_capability("people.create")),
    db: OrmSession = Depends(get_db),
):
    """Dry run by default (see docs/03). `?commit=true` applies exactly the same diff that
    was just previewed — computed a second time server-side rather than trusted from the
    client, so nothing can slip in between preview and apply."""
    try:
        rows = load_sheet_rows(file.file)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, {"error": "bad_workbook", "message": str(exc)})

    diff = compute_diff(db, rows)
    result = {
        "new": [{"employee_code": r.employee_code, "full_name": r.full_name} for r in diff.new],
        "changed": [
            {"employee_code": r.employee_code, "full_name": r.full_name, "fields": {k: list(v) for k, v in fd.items()}}
            for r, fd in diff.changed
        ],
        "missing": diff.missing_codes,
        "conflicts": diff.conflicts,
        "proposed_grants": [
            {"employee_code": c, "full_name": n, "text": t} for c, n, t in diff.proposed_grants
        ],
        "committed": False,
    }
    if commit:
        apply_diff(db, diff)
        audit(
            db, action="employee.import", actor_user_id=admin.id,
            new=len(diff.new), changed=len(diff.changed), conflicts=len(diff.conflicts),
        )
        db.commit()
        result["committed"] = True
    return result


# ── users ────────────────────────────────────────────────────────────────────
@router.get("/users")
def list_users(
    q: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(50, le=200),
    admin: User = Depends(require_capability("people.view")),
    db: OrmSession = Depends(get_db),
):
    stmt = select(User, Employee).join(Employee, User.employee_id == Employee.id).order_by(Employee.employee_code)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    rows = list(db.execute(stmt))
    if q:
        needle = q.lower()
        rows = [
            (u, e) for u, e in rows
            if needle in e.full_name.lower()
            or needle in e.employee_code.lower()
            or (u.login_email and needle in u.login_email.lower())
        ]
    rows = rows[:limit]
    return {"users": [_user_out(u, e) for u, e in rows]}


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: dict, request: Request, admin: User = Depends(current_user), db: OrmSession = Depends(get_db)):
    user = _get_or_404(db, User, user_id, "user_not_found")

    ip = client_ip(request)
    now = datetime.now(timezone.utc)

    if "is_platform_admin" in body and not has_capability(db, admin, "admin_roles.manage"):
        raise HTTPException(403, {"error": "capability_required"})
    if "is_active" in body and not has_capability(db, admin, "people.edit"):
        raise HTTPException(403, {"error": "capability_required"})
    if user.is_platform_admin and not admin.is_platform_admin and (
        body.get("is_platform_admin") is False or body.get("is_active") is False
    ):
        audit(db, action="admin.protected_attempt", actor_user_id=admin.id,
              target_type="user", target_id=user.id, ip=ip, requested=list(body))
        db.commit()
        raise HTTPException(403, {"error": "protected_admin"})

    removing_admin = user.is_platform_admin and (
        body.get("is_platform_admin") is False or body.get("is_active") is False
    )
    if removing_admin:
        active_admins = db.scalar(select(func.count()).select_from(User).where(
            User.is_platform_admin.is_(True), User.is_active.is_(True)
        )) or 0
        if active_admins <= 1:
            audit(db, action="admin.protected_attempt", actor_user_id=admin.id,
                  target_type="user", target_id=user.id, ip=ip, requested=list(body))
            db.commit()
            raise HTTPException(409, {"error": "last_active_admin", "message": "MM OS must retain an active IT Admin."})

    if "is_platform_admin" in body:
        new_admin = bool(body["is_platform_admin"])
        if new_admin != user.is_platform_admin:
            user.is_platform_admin = new_admin
            audit(db, action="admin.role_change", actor_user_id=admin.id,
                  target_type="user", target_id=user.id, ip=ip, enabled=new_admin)

    if "is_active" in body:
        new_active = bool(body["is_active"])
        was_active = user.is_active
        user.is_active = new_active

        if was_active and not new_active:
            # Deactivating a user: flip the flag, revoke every live session, and write a
            # revocation row — all in this one transaction (docs/03 "Rules that hold
            # everywhere": access removal is never a two-step that can half-fail).
            live_sessions = db.scalars(
                select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None))
            )
            for s in live_sessions:
                s.revoked_at = now
            db.add(
                Revocation(
                    subject=user.subject,
                    service_id=None,  # global — every service must stop trusting this user
                    reason="user_deactivated",
                    revoked_by=admin.id,
                    purge_after=now + timedelta(hours=2),
                )
            )
            audit(db, action="user.deactivate", actor_user_id=admin.id, target_type="user", target_id=user.id, ip=ip)
        elif new_active and not was_active:
            audit(db, action="user.activate", actor_user_id=admin.id, target_type="user", target_id=user.id, ip=ip)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"error": "user_conflict", "message": "That change violates a PIN/admin rule (e.g. a PIN user cannot be platform admin)."})

    db.commit()
    employee = db.get(Employee, user.employee_id)
    return _user_out(user, employee)


@router.post("/users/{user_id}/pin")
def set_user_pin(user_id: str, body: dict | None = None, request: Request = None, admin: User = Depends(require_capability("people.edit")), db: OrmSession = Depends(get_db)):
    """Issue or reset a PIN. Returns the raw PIN once — it is never retrievable again.

    `{"clear": true}` cannot literally null the stored hash: models.py's `pin_required`
    CHECK forbids `auth_type='local_pin' AND pin_hash IS NULL` (see handoff
    ## Contract objections). Clearing instead resets to an unusable placeholder hash and
    nulls `pin_set_at`, which is the actual "PIN not set" signal the admin UI reads.
    """
    # Every user gets PIN login regardless of auth_type (owner ruling: PIN-first for
    # everyone, plus optional Google linking that keeps pin_hash intact) -- so issuing or
    # resetting a PIN is never blocked by auth_type here.
    user = _get_or_404(db, User, user_id, "user_not_found")

    body = body or {}
    ip = client_ip(request) if request else None

    if body.get("clear"):
        placeholder = f"{secrets.randbelow(1_000_000):06d}"
        user.pin_hash = hash_pin(placeholder)
        user.pin_set_at = None
        user.failed_pin_attempts = 0
        user.locked_until = None
        audit(db, action="user.pin_clear", actor_user_id=admin.id, target_type="user", target_id=user.id, ip=ip)
        db.commit()
        return {"pin": None, "cleared": True}

    pin = body.get("pin")
    if pin is not None:
        pin = str(pin)
    else:
        pin = f"{secrets.randbelow(1_000_000):06d}"

    try:
        user.pin_hash = hash_pin(pin)
    except ValueError as exc:
        raise HTTPException(422, {"error": "bad_pin", "message": str(exc)})

    user.pin_set_at = datetime.now(timezone.utc)
    user.failed_pin_attempts = 0
    user.locked_until = None
    audit(db, action="user.pin_set", actor_user_id=admin.id, target_type="user", target_id=user.id, ip=ip)
    db.commit()
    return {"pin": pin}
