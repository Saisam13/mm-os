"""Real-person provisioning (app/provision.py + POST /api/admin/provision + the PIN-change
flow in routers/auth.py), including the management-layer full-admin path (owner decision,
28 Aug 2026). No real employee names appear here -- the mechanism is tested with synthetic
codes only.
"""
from __future__ import annotations

from app.provision import (
    clear_must_change,
    issue_one_time_pin,
    must_change_pin,
    provision_by_code,
)
from app.security import verify_pin


# ── the unit: issue_one_time_pin flags must-change ───────────────────────────────────
def test_issue_one_time_pin_sets_must_change_and_a_working_pin(db, make_user):
    user = make_user(auth_type="local_pin")
    pin = issue_one_time_pin(db, user)
    db.commit()

    assert must_change_pin(db, user) is True
    assert user.pin_set_at is not None
    assert verify_pin(pin, user.pin_hash)

    # Clearing the flag (what the self-service change does) drops the must-change row.
    clear_must_change(db, user)
    db.commit()
    assert must_change_pin(db, user) is False


# ── the endpoint returns a one-time PIN, and first login forces a change ──────────────
def test_provision_endpoint_returns_pin_and_first_login_forces_change(
    db, client, make_user, make_employee, sign_in
):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)

    emp = make_employee(employee_code="MM-PROV1")
    make_user(employee=emp, auth_type="local_pin")

    r = client.post("/api/admin/provision", json={"employee_codes": ["MM-PROV1"]})
    assert r.status_code == 200, r.text
    provisioned = r.json()["provisioned"]
    assert len(provisioned) == 1
    pin = provisioned[0]["pin"]
    assert pin and pin.isdigit()

    # First login: the response tells the shell the PIN must be changed.
    client.cookies.clear()
    login = client.post("/api/auth/pin", json={"employee_code": "MM-PROV1", "pin": pin})
    assert login.status_code == 200, login.text
    assert login.json()["must_change"] is True

    # The holder changes it via the self-service endpoint (session now belongs to them).
    changed = client.post("/api/auth/pin/change", json={"pin": pin, "new_pin": "778899"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change"] is False

    # A second login with the NEW pin no longer forces a change.
    client.cookies.clear()
    relogin = client.post("/api/auth/pin", json={"employee_code": "MM-PROV1", "pin": "778899"})
    assert relogin.status_code == 200
    assert relogin.json()["must_change"] is False


# ── management layer: full IT-admin-equivalent access (gap 3) ─────────────────────────
def test_management_layer_provision_grants_platform_admin_and_reaches_admin_routes(
    db, client, make_user, make_employee, sign_in
):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)

    head_emp = make_employee(employee_code="MM-HEAD1", work_email="head1@m-mines.com")
    head = make_user(employee=head_emp, auth_type="local_pin")

    r = client.post(
        "/api/admin/provision",
        json={"employee_codes": ["MM-HEAD1"], "platform_admin": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["provisioned"][0]["platform_admin"] is True

    db.refresh(head)
    assert head.is_platform_admin is True
    # A platform admin can never be a local_pin user (models.py no_pin_admins CHECK), so
    # provisioning flipped them to google auth with their corporate email -- while still
    # keeping the one-time PIN.
    assert head.auth_type == "google"
    assert head.login_email == "head1@m-mines.com"
    assert must_change_pin(db, head) is True

    # The head now actually reaches an admin-only route.
    client.cookies.clear()
    sign_in(head)
    assert client.get("/api/admin/services").status_code == 200


def test_normal_provision_does_not_grant_platform_admin(
    db, client, make_user, make_employee, sign_in
):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)

    emp = make_employee(employee_code="MM-STAFF1", work_email="staff1@m-mines.com")
    staff = make_user(employee=emp, auth_type="local_pin")

    r = client.post("/api/admin/provision", json={"employee_codes": ["MM-STAFF1"]})
    assert r.status_code == 200, r.text

    db.refresh(staff)
    assert staff.is_platform_admin is False
    assert staff.auth_type == "local_pin"  # untouched

    # And a normal provisioned user is locked out of admin routes.
    client.cookies.clear()
    sign_in(staff)
    assert client.get("/api/admin/services").status_code == 403


# ── direct unit for the flag, plus the no-email guard ─────────────────────────────────
def test_provision_by_code_platform_admin_requires_a_work_email(db, make_user, make_employee):
    emp = make_employee(employee_code="MM-NOEMAIL", work_email=None)
    make_user(employee=emp, auth_type="local_pin")

    pin, status = provision_by_code(db, "MM-NOEMAIL", platform_admin=True)
    assert pin is None
    assert status == "no_email"
