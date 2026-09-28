"""Admin employee + user management. Owned by A1 (Identity). Everything here requires
`require_admin`. See docs/03-api-contract.md "Admin".
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from ..db import get_db
from ..deps import audit, client_ip, require_admin
from ..models import Employee, Revocation, Session, User
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
    admin: User = Depends(require_admin),
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
def create_employee(body: dict, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
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
def update_employee(employee_id: str, body: dict, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    emp = _get_or_404(db, Employee, employee_id, "employee_not_found")
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
    admin: User = Depends(require_admin),
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
    admin: User = Depends(require_admin),
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
def update_user(user_id: str, body: dict, request: Request, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
    user = _get_or_404(db, User, user_id, "user_not_found")

    ip = client_ip(request)
    now = datetime.now(timezone.utc)

    if "is_platform_admin" in body:
        user.is_platform_admin = bool(body["is_platform_admin"])

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
def set_user_pin(user_id: str, body: dict | None = None, request: Request = None, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)):
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
