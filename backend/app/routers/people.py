"""Admin employee + user management. Owned by A1 (Identity). Everything here requires
`require_admin`. See docs/03-api-contract.md "Admin".
"""
from __future__ import annotations

import re
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
from ..provision import (
    FUNCTIONAL_JOB_TITLE,
    issue_one_time_pin,
    must_change_pin,
    provision_account,
    provision_by_code,
)
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


# ── real-person provisioning ───────────────────────────────────────────────────
@router.post("/provision")
def provision_people(
    body: dict, request: Request, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    """Provision specific named employees (by code) with a real ONE-TIME PIN they must change
    on first login. This is how IT brings real staff online for the actual rollout, replacing
    the demo seed. It works on people already imported (via the sheet importer); it never reads
    a spreadsheet and never carries a name in its request -- only employee codes.

    Body: {"employee_codes": ["MM05", ...], "pin_length": 6, "platform_admin": false}. Each PIN is
    returned ONCE, in the response, and is never retrievable again -- hand each to its person
    directly. A code with no MM OS login yet is reported under `skipped`, not silently dropped.

    `platform_admin: true` provisions the management layer: the listed people get the EXACT same
    full IT-admin-equivalent access as the itadmin layer (act + approve + see everything), not a
    view-only role -- an explicit owner decision (28 Aug 2026) that deliberately gives heads
    IT-level power. See provision.provision_by_code for how this satisfies the no_pin_admins
    CHECK (admins authenticate as google + keep a one-time PIN)."""
    codes = body.get("employee_codes") or body.get("codes") or []
    if isinstance(codes, str):
        codes = [codes]
    if not isinstance(codes, list) or not codes:
        raise HTTPException(422, {"error": "no_codes", "message": "Provide employee_codes: a non-empty list."})
    length = int(body.get("pin_length") or 6)
    platform_admin = bool(body.get("platform_admin"))

    ip = client_ip(request)
    provisioned: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for raw in codes:
        code = str(raw).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        pin, status = provision_by_code(db, code, length=length, platform_admin=platform_admin)
        if status == "provisioned":
            provisioned.append({"employee_code": code, "pin": pin, "platform_admin": platform_admin})
            audit(
                db, action="user.provision", actor_user_id=admin.id, target_type="employee",
                target_id=code, ip=ip, platform_admin=platform_admin,
            )
        else:
            skipped.append({"employee_code": code, "reason": status})
    db.commit()
    return {"provisioned": provisioned, "skipped": skipped}


# ── functional-mailbox accounts ────────────────────────────────────────────────
# The operational "add & customize" surface for the FUNCTIONAL-MAILBOX accounts MM OS now
# provisions (purchase.c2@, central.stores@, sales@ ...). These endpoints share ONE per-row
# core with the CLI loader (scripts/provision_functional.py) via app.provision.provision_account
# so an account created here and one loaded from the roster CSV are byte-for-byte the same.
# A "functional account" is any Employee whose job_title is FUNCTIONAL_JOB_TITLE.


def _account_out(db: OrmSession, u: User, e: Employee) -> dict:
    return {
        "id": str(u.id),
        "employee_id": str(e.id),
        "employee_code": e.employee_code,
        "email": u.login_email or e.work_email,
        "label": e.full_name,
        "department": e.hr_department,
        "approval_level": e.approval_level,
        "is_platform_admin": u.is_platform_admin,
        "auth_type": u.auth_type,
        "is_active": u.is_active,
        "pin_set": bool(u.pin_set_at),
        "must_change_pin": must_change_pin(db, u),
    }


def _derive_employee_code(db: OrmSession, email: str) -> str:
    """Derive a unique employee_code (String(16)) for a functional mailbox with no explicit
    code -- from the mailbox local-part, e.g. "purchase.c2@..." -> "PURCHASE.C2". Adds a short
    random suffix if that base is already taken by a different account."""
    local = email.split("@", 1)[0]
    base = re.sub(r"[^A-Za-z0-9.]", "", local).upper()[:16].strip(".") or "FN"
    candidate = base
    while db.scalar(select(Employee).where(Employee.employee_code == candidate)):
        candidate = (base[:9] + secrets.token_hex(3).upper())[:16]
    return candidate


def _resolve_code(db: OrmSession, *, email: str, explicit: str | None) -> str:
    """Which employee_code this account keys on: an explicit code wins; otherwise reuse the
    code of any existing account already on this email (so re-adding the same mailbox updates
    in place rather than erroring on the unique work_email); otherwise derive a fresh one."""
    if explicit:
        return explicit
    existing = db.scalar(select(Employee).where(Employee.work_email == email))
    if existing is None:
        user = db.scalar(select(User).where(User.login_email == email))
        existing = db.get(Employee, user.employee_id) if user else None
    return existing.employee_code if existing else _derive_employee_code(db, email)


def _account_by_user_id(db: OrmSession, user_id: str) -> tuple[User, Employee]:
    user = _get_or_404(db, User, user_id, "account_not_found")
    emp = db.get(Employee, user.employee_id)
    if emp is None:
        raise HTTPException(404, {"error": "account_not_found"})
    return user, emp


@router.get("/accounts")
def list_accounts(
    dept: str | None = None,
    admin: User = Depends(require_admin),
    db: OrmSession = Depends(get_db),
):
    """List functional-mailbox accounts (Employee.job_title == FUNCTIONAL_JOB_TITLE), optionally
    filtered by department. Personal-employee accounts are managed on the People page instead."""
    stmt = (
        select(User, Employee)
        .join(Employee, User.employee_id == Employee.id)
        .where(Employee.job_title == FUNCTIONAL_JOB_TITLE)
        .order_by(Employee.hr_department, Employee.employee_code)
    )
    if dept:
        stmt = stmt.where(Employee.hr_department == dept)
    rows = list(db.execute(stmt))
    return {"accounts": [_account_out(db, u, e) for u, e in rows]}


@router.post("/accounts")
def create_account(
    body: dict, request: Request, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    """Create OR customize one functional account. Idempotent on email: re-posting the same
    mailbox updates it in place. Returns the account plus a one-time PIN the FIRST time a PIN is
    issued (a freshly created account, or when `reset: true`); the PIN is shown once, never
    retrievable again. Blank approval_level / falsey platform_admin never demote an existing
    account (see app.provision.provision_account).

    New accounts default to `is_active=False` -- review-then-enable is the norm now, so a
    freshly created mailbox cannot sign in until an admin enables it (here, via PATCH, or in
    the admin Accounts page). Pass `active: true` to create it already enabled. Re-posting an
    EXISTING account never changes its is_active either way (see provision_account)."""
    email = (body.get("email") or body.get("login_email") or "").strip()
    if not email:
        raise HTTPException(422, {"error": "missing_email", "message": "email is required."})
    department = (body.get("department") or "").strip()
    role = (body.get("role") or "requester").strip() or "requester"
    approval_level = body.get("approval_level")
    approval_level = approval_level.strip() if isinstance(approval_level, str) else None
    platform_admin = bool(body.get("platform_admin"))
    active = bool(body.get("active"))
    reset = bool(body.get("reset"))
    code = _resolve_code(db, email=email, explicit=(body.get("employee_code") or "").strip() or None)

    result = provision_account(
        db,
        employee_code=code,
        login_email=email,
        department=department,
        role=role,
        approval_level=approval_level or None,
        platform_admin=platform_admin,
        active=active,
        commit=True,
        reset=reset,
    )
    if result.user_action == "admin_no_email":
        db.rollback()
        raise HTTPException(422, {"error": "admin_no_email", "message": "A management head needs an email to sign in as."})
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"error": "account_conflict", "message": "That employee code or email already belongs to another account."})

    emp = db.scalar(select(Employee).where(Employee.employee_code == code))
    user = db.scalar(select(User).where(User.employee_id == emp.id))
    audit(
        db, action="account.provision", actor_user_id=admin.id, target_type="employee",
        target_id=code, ip=client_ip(request), platform_admin=result.platform_admin,
        created=result.employee_action in ("created",),
    )
    db.commit()
    return {
        "account": _account_out(db, user, emp),
        "pin": result.pin,
        "created": result.employee_action == "created",
    }


@router.post("/accounts/bulk")
def bulk_accounts(
    body: dict, request: Request, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    """Bulk create/update functional accounts from parsed roster rows (the frontend parses the
    CSV and sends JSON). `dry_run: true` reports what WOULD change and writes nothing; `dry_run:
    false` applies and returns the one-time PIN list. Each row: {employee_code?, email, department,
    role?, approval_level?, platform_admin?, active?}.

    New accounts default to `is_active=False` -- IT reviews the import and enables each mailbox
    in the admin Accounts page. A row (or the whole import) can pass `active: true` to create
    already enabled instead. An account that already exists is never re-enabled or re-disabled
    by this endpoint either way (see app.provision.provision_account)."""
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(422, {"error": "no_rows", "message": "Provide rows: a non-empty list."})
    dry_run = bool(body.get("dry_run", True))
    reset = bool(body.get("reset"))
    default_active = bool(body.get("active"))  # whole-import override; a row's own "active" wins

    out_rows: list[dict] = []
    pins: list[dict] = []
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    seen: set[str] = set()
    try:
        for raw in rows:
            email = (raw.get("email") or raw.get("login_email") or "").strip()
            if not email:
                continue
            code = (raw.get("employee_code") or "").strip() or _resolve_code(db, email=email, explicit=None)
            if code in seen:
                continue
            seen.add(code)
            approval = raw.get("approval_level")
            approval = approval.strip() if isinstance(approval, str) else None
            result = provision_account(
                db,
                employee_code=code,
                login_email=email,
                department=(raw.get("department") or "").strip(),
                role=(raw.get("role") or "requester").strip() or "requester",
                approval_level=approval or None,
                platform_admin=bool(raw.get("platform_admin")),
                active=bool(raw["active"]) if "active" in raw else default_active,
                commit=not dry_run,
                reset=reset,
            )
            if result.employee_action in ("created", "would_create"):
                counts["created"] += 1
            elif result.employee_action in ("updated", "would_update"):
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
            out_rows.append({
                "employee_code": result.employee_code,
                "email": result.login_email,
                "employee_action": result.employee_action,
                "user_action": result.user_action,
                "platform_admin": result.platform_admin,
                "approval_level": result.approval_level,
                "active": result.active,
            })
            if result.pin:
                pins.append({
                    "employee_code": result.employee_code,
                    "email": result.login_email,
                    "pin": result.pin,
                    "platform_admin": result.platform_admin,
                })
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"error": "account_conflict", "message": "A row's employee code or email conflicts with an existing account."})

    if dry_run:
        db.rollback()
        return {
            "dry_run": True,
            "would_create": counts["created"],
            "would_update": counts["updated"],
            "unchanged": counts["unchanged"],
            "rows": out_rows,
        }

    audit(
        db, action="account.bulk_provision", actor_user_id=admin.id, target_type="employee",
        target_id=None, ip=client_ip(request),
        created=counts["created"], updated=counts["updated"],
    )
    db.commit()
    return {
        "dry_run": False,
        "created": counts["created"],
        "updated": counts["updated"],
        "unchanged": counts["unchanged"],
        "rows": out_rows,
        "pins": pins,
    }


@router.post("/accounts/{account_id}/reset-pin")
def reset_account_pin(
    account_id: str, request: Request, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    """Reissue a one-time must-change PIN for a functional account. Returns the PIN once."""
    user, _emp = _account_by_user_id(db, account_id)
    pin = issue_one_time_pin(db, user)
    audit(
        db, action="account.reset_pin", actor_user_id=admin.id, target_type="user",
        target_id=user.id, ip=client_ip(request),
    )
    db.commit()
    return {"pin": pin}


@router.patch("/accounts/{account_id}")
def patch_account(
    account_id: str, body: dict, request: Request, admin: User = Depends(require_admin), db: OrmSession = Depends(get_db)
):
    """Customize one functional account. Only keys present in the body change; an ABSENT key is
    left untouched. To CLEAR approval_level send it as null or "" explicitly. Toggling
    platform_admin on satisfies models.py's no_pin_admins CHECK the same way provisioning does
    (flip to google auth, set login_email)."""
    user, emp = _account_by_user_id(db, account_id)
    ip = client_ip(request)
    now = datetime.now(timezone.utc)
    changed: list[str] = []

    if "department" in body and body["department"]:
        emp.hr_department = str(body["department"]).strip()
        changed.append("department")
    if "label" in body and body["label"]:
        emp.full_name = str(body["label"]).strip()
        changed.append("label")

    if "approval_level" in body:  # present => explicit set/clear (null/"" clears)
        val = body["approval_level"]
        emp.approval_level = str(val).strip() if isinstance(val, str) and val.strip() else None
        changed.append("approval_level")

    if "platform_admin" in body:
        want = bool(body["platform_admin"])
        if want and not user.is_platform_admin:
            email = user.login_email or emp.work_email
            if not email:
                raise HTTPException(422, {"error": "admin_no_email", "message": "A management head needs an email to sign in as."})
            user.login_email = email
            user.auth_type = "google"  # no_pin_admins: an admin can never be local_pin
            user.is_platform_admin = True
        elif not want:
            user.is_platform_admin = False
        changed.append("platform_admin")

    if "is_active" in body:
        new_active = bool(body["is_active"])
        was_active = user.is_active
        user.is_active = new_active
        if was_active and not new_active:
            for s in db.scalars(
                select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None))
            ):
                s.revoked_at = now
            db.add(Revocation(
                subject=user.subject, service_id=None, reason="user_deactivated",
                revoked_by=admin.id, purge_after=now + timedelta(hours=2),
            ))
        changed.append("is_active")

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"error": "account_conflict", "message": "That change violates a PIN/admin/email rule."})

    audit(
        db, action="account.update", actor_user_id=admin.id, target_type="user",
        target_id=user.id, ip=ip, fields=changed,
    )
    db.commit()
    return _account_out(db, user, emp)
