"""Tests for the functional-mailbox admin surface (POST/PATCH /api/admin/accounts*, the shared
core in app/provision.provision_account). Synthetic data only -- fake codes and *@example.test
addresses, never a real roster row, name, or email.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Employee, Session, User
from app.provision import must_change_pin


def _admin(make_user, sign_in):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    return admin


# ── create one account ───────────────────────────────────────────────────────────────
def test_create_account_makes_functional_account_with_one_time_pin(db, client, make_user, sign_in):
    _admin(make_user, sign_in)

    r = client.post("/api/admin/accounts", json={
        "email": "central.stores@example.test", "department": "Central Stores", "role": "requester",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    pin = body["pin"]
    assert pin and pin.isdigit() and len(pin) == 6
    acct = body["account"]
    assert acct["email"] == "central.stores@example.test"
    assert acct["department"] == "Central Stores"
    assert acct["label"] == "Central Stores"  # derived from mailbox local-part
    assert acct["is_platform_admin"] is False
    assert acct["must_change_pin"] is True
    assert acct["is_active"] is False  # disabled by default -- IT enables after review

    emp = db.scalar(select(Employee).where(Employee.work_email == "central.stores@example.test"))
    assert emp is not None and emp.job_title == "Functional Mailbox"
    user = db.scalar(select(User).where(User.employee_id == emp.id))
    assert must_change_pin(db, user) is True
    assert user.is_active is False


def test_create_account_with_active_true_creates_enabled(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    r = client.post("/api/admin/accounts", json={
        "email": "enabled.desk@example.test", "department": "Sales", "active": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["account"]["is_active"] is True


def test_create_account_is_idempotent_on_email(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    first = client.post("/api/admin/accounts", json={"email": "sales@example.test", "department": "Sales"})
    assert first.status_code == 200
    first_code = first.json()["account"]["employee_code"]

    # Re-posting the same mailbox updates in place: no second Employee, PIN kept (no reset).
    second = client.post("/api/admin/accounts", json={"email": "sales@example.test", "department": "Sales North"})
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False
    assert second.json()["account"]["employee_code"] == first_code
    assert second.json()["pin"] is None  # existing PIN left alone

    emps = db.scalars(select(Employee).where(Employee.work_email == "sales@example.test")).all()
    assert len(emps) == 1
    assert emps[0].hr_department == "Sales North"


# ── bulk: dry-run vs commit ───────────────────────────────────────────────────────────
def test_bulk_dry_run_writes_nothing_then_commit_applies(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    rows = [
        {"employee_code": "FN-A", "email": "purchase.c2@example.test", "department": "Purchase"},
        {"employee_code": "FN-B", "email": "qa.line1@example.test", "department": "QA", "platform_admin": True},
    ]

    dry = client.post("/api/admin/accounts/bulk", json={"rows": rows, "dry_run": True})
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert dry.json()["would_create"] == 2
    assert "pins" not in dry.json()
    # The preview shows accounts will be created disabled (default active=False).
    assert all(r["active"] is False for r in dry.json()["rows"])
    # Nothing written.
    assert db.scalar(select(Employee).where(Employee.employee_code == "FN-A")) is None

    commit = client.post("/api/admin/accounts/bulk", json={"rows": rows, "dry_run": False})
    assert commit.status_code == 200, commit.text
    assert commit.json()["dry_run"] is False
    assert commit.json()["created"] == 2
    assert len(commit.json()["pins"]) == 2
    assert db.scalar(select(Employee).where(Employee.employee_code == "FN-A")) is not None

    # Disabled by default -- IT reviews and enables each mailbox afterward.
    emp_a = db.scalar(select(Employee).where(Employee.employee_code == "FN-A"))
    user_a = db.scalar(select(User).where(User.employee_id == emp_a.id))
    assert user_a.is_active is False

    # FN-B was flagged platform_admin: satisfies no_pin_admins (google auth, keeps a PIN).
    emp_b = db.scalar(select(Employee).where(Employee.employee_code == "FN-B"))
    user_b = db.scalar(select(User).where(User.employee_id == emp_b.id))
    assert user_b.is_platform_admin is True
    assert user_b.auth_type == "google"
    assert user_b.login_email == "qa.line1@example.test"
    assert user_b.is_active is False  # disabled-by-default applies to heads too


def test_bulk_active_true_creates_enabled_accounts(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    rows = [{"employee_code": "FN-EN", "email": "enabled.bulk@example.test", "department": "Sales", "active": True}]
    commit = client.post("/api/admin/accounts/bulk", json={"rows": rows, "dry_run": False})
    assert commit.status_code == 200, commit.text
    emp = db.scalar(select(Employee).where(Employee.employee_code == "FN-EN"))
    user = db.scalar(select(User).where(User.employee_id == emp.id))
    assert user.is_active is True


def test_bulk_rerun_never_redisables_an_enabled_account(db, client, make_user, sign_in):
    """The admin enables a bulk-created account in the Accounts page; re-importing the same
    roster row (still defaulting to active=False) must not disable it again."""
    _admin(make_user, sign_in)
    rows = [{"employee_code": "FN-STAY", "email": "stay.enabled@example.test", "department": "Sales"}]
    client.post("/api/admin/accounts/bulk", json={"rows": rows, "dry_run": False})

    emp = db.scalar(select(Employee).where(Employee.employee_code == "FN-STAY"))
    user = db.scalar(select(User).where(User.employee_id == emp.id))
    assert user.is_active is False
    user.is_active = True
    db.commit()

    client.post("/api/admin/accounts/bulk", json={"rows": rows, "dry_run": False})
    db.refresh(user)
    assert user.is_active is True


def test_bulk_commit_is_idempotent(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    rows = [{"employee_code": "FN-C", "email": "stores.c1@example.test", "department": "Stores"}]
    first = client.post("/api/admin/accounts/bulk", json={"rows": rows, "dry_run": False})
    assert first.json()["created"] == 1

    second = client.post("/api/admin/accounts/bulk", json={"rows": rows, "dry_run": False})
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0
    assert second.json()["unchanged"] == 1
    assert second.json()["pins"] == []  # PIN kept, not reissued
    assert len(db.scalars(select(Employee).where(Employee.employee_code == "FN-C")).all()) == 1


# ── customize: approval level, blank-vs-set semantics ─────────────────────────────────
def test_patch_sets_and_clears_approval_level(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    created = client.post("/api/admin/accounts", json={"email": "hr.desk@example.test", "department": "HR"})
    account_id = created.json()["account"]["id"]

    # Set it.
    r = client.patch(f"/api/admin/accounts/{account_id}", json={"approval_level": "L3 (HOD)"})
    assert r.status_code == 200, r.text
    assert r.json()["approval_level"] == "L3 (HOD)"

    # An absent key never clobbers it.
    r = client.patch(f"/api/admin/accounts/{account_id}", json={"department": "HR Ops"})
    assert r.json()["approval_level"] == "L3 (HOD)"
    assert r.json()["department"] == "HR Ops"

    # Explicit null clears it.
    r = client.patch(f"/api/admin/accounts/{account_id}", json={"approval_level": None})
    assert r.json()["approval_level"] is None


def test_patch_toggles_platform_admin_without_tripping_no_pin_admins(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    created = client.post("/api/admin/accounts", json={"email": "ops.head@example.test", "department": "Ops"})
    account_id = created.json()["account"]["id"]

    r = client.patch(f"/api/admin/accounts/{account_id}", json={"platform_admin": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_platform_admin"] is True
    assert r.json()["auth_type"] == "google"

    user = db.get(User, __import__("uuid").UUID(account_id))
    db.refresh(user)
    assert user.is_platform_admin is True and user.auth_type == "google"

    # Toggle back off.
    r = client.patch(f"/api/admin/accounts/{account_id}", json={"platform_admin": False})
    assert r.json()["is_platform_admin"] is False


def test_patch_deactivate_revokes_sessions(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    created = client.post("/api/admin/accounts", json={"email": "temp.desk@example.test", "department": "Temp"})
    account_id = created.json()["account"]["id"]
    # Newly created accounts are disabled by default; activate first so there is a real
    # active-to-inactive transition to revoke sessions for.
    client.patch(f"/api/admin/accounts/{account_id}", json={"is_active": True})

    r = client.patch(f"/api/admin/accounts/{account_id}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_patch_can_enable_a_disabled_account(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    created = client.post("/api/admin/accounts", json={"email": "review.me@example.test", "department": "Ops"})
    account_id = created.json()["account"]["id"]
    assert created.json()["account"]["is_active"] is False  # created disabled by default

    r = client.patch(f"/api/admin/accounts/{account_id}", json={"is_active": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True


# ── reset PIN ─────────────────────────────────────────────────────────────────────────
def test_reset_pin_reissues_a_must_change_pin(db, client, make_user, sign_in):
    _admin(make_user, sign_in)
    created = client.post("/api/admin/accounts", json={"email": "line.b@example.test", "department": "Line B"})
    account_id = created.json()["account"]["id"]
    first_pin = created.json()["pin"]

    r = client.post(f"/api/admin/accounts/{account_id}/reset-pin")
    assert r.status_code == 200, r.text
    new_pin = r.json()["pin"]
    assert new_pin and new_pin.isdigit() and new_pin != first_pin

    import uuid
    user = db.get(User, uuid.UUID(account_id))
    db.refresh(user)
    assert must_change_pin(db, user) is True


# ── listing ──────────────────────────────────────────────────────────────────────────
def test_list_accounts_only_returns_functional_accounts(db, client, make_user, make_employee, sign_in):
    _admin(make_user, sign_in)
    # A normal (personal) employee+user should NOT appear.
    emp = make_employee(employee_code="MM-REAL", job_title="Engineer")
    make_user(employee=emp, auth_type="google")

    client.post("/api/admin/accounts", json={"email": "central.desk@example.test", "department": "Central"})
    client.post("/api/admin/accounts", json={"email": "west.desk@example.test", "department": "West"})

    r = client.get("/api/admin/accounts")
    assert r.status_code == 200
    codes = {a["employee_code"] for a in r.json()["accounts"]}
    assert "MM-REAL" not in codes
    assert len(r.json()["accounts"]) == 2

    # Department filter.
    r = client.get("/api/admin/accounts", params={"dept": "West"})
    assert [a["department"] for a in r.json()["accounts"]] == ["West"]


# ── authz: a non-admin is refused everywhere ──────────────────────────────────────────
def test_non_admin_is_forbidden(db, client, make_user, sign_in):
    staff = make_user(is_platform_admin=False)
    sign_in(staff)
    assert client.get("/api/admin/accounts").status_code == 403
    assert client.post("/api/admin/accounts", json={"email": "x@example.test", "department": "X"}).status_code == 403
    assert client.post("/api/admin/accounts/bulk", json={"rows": [{"email": "y@example.test", "department": "Y"}]}).status_code == 403
