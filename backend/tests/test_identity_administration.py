"""Acceptance coverage for the identity and access administration rebuild."""
import jwt
from sqlalchemy import select

from app.models import (
    AgentIdentity, AuditLog, Department, Employee, Grant, Revocation, UserCapability,
)


def department(db, name="Engineering", key="engineering"):
    row = Department(name=name, key=key)
    db.add(row); db.commit()
    return row


def admin_session(make_user, sign_in):
    user = make_user(is_platform_admin=True)
    sign_in(user)
    return user


def payload(dept, **employee):
    base = {
        "employee_code": "MM900", "full_name": "Synthetic Employee",
        "work_email": "synthetic@m-mines.com", "department_id": str(dept.id),
        "division": "Technology", "job_title": "Engineer", "band": "L2",
    }
    base.update(employee)
    return {"employee": base, "auth_type": "google", "grants": []}


def test_it_admin_creates_person_in_controlled_department(client, db, make_user, sign_in):
    actor = admin_session(make_user, sign_in); dept = department(db)
    response = client.post("/api/admin/people", json=payload(dept))
    assert response.status_code == 201
    body = response.json()
    assert body["employee"]["department"]["name"] == "Engineering"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "person.create")).actor_user_id == actor.id


def test_department_tracks_erpnext_mapping(client, make_user, sign_in):
    admin_session(make_user, sign_in)
    created = client.post("/api/admin/departments", json={
        "name": "Projects", "key": "projects", "erp_department": "Projects - MM",
    })
    assert created.status_code == 201
    department_id = created.json()["id"]
    assert created.json()["erp_department"] == "Projects - MM"

    updated = client.patch(f"/api/admin/departments/{department_id}", json={"erp_department": "Project Operations - MM"})
    assert updated.status_code == 200
    assert updated.json()["erp_department"] == "Project Operations - MM"


def test_hr_onboarding_creator_is_department_scoped(client, db, make_user, sign_in):
    hr = make_user(); allowed = department(db); denied = department(db, "Finance", "finance")
    db.add(UserCapability(user_id=hr.id, capability="hr_onboarding.create", scope_department_id=allowed.id)); db.commit(); sign_in(hr)
    good = payload(allowed, employee_code="MM901", work_email="hr-created@m-mines.com", onboarding_ref="HR-901")
    assert client.post("/api/admin/people", json=good).status_code == 201
    bad = payload(denied, employee_code="MM902", work_email="denied@m-mines.com", onboarding_ref="HR-902")
    assert client.post("/api/admin/people", json=bad).status_code == 403


def test_unauthorized_and_duplicates_fail_safely(client, db, make_user, sign_in):
    sign_in(make_user()); dept = department(db)
    assert client.post("/api/admin/people", json=payload(dept)).status_code == 403
    client.cookies.clear(); admin_session(make_user, sign_in)
    first = payload(dept, onboarding_ref="HR-DUP")
    assert client.post("/api/admin/people", json=first).status_code == 201
    duplicate = payload(dept, employee_code="MM903", work_email="other@m-mines.com", onboarding_ref="HR-DUP")
    assert client.post("/api/admin/people", json=duplicate).status_code == 409


def test_create_person_multiple_services_and_roles_is_atomic(client, db, make_user, sign_in, make_service):
    admin_session(make_user, sign_in); dept = department(db)
    one, _ = make_service("one", roles=("viewer", "editor")); make_service("two", roles=("user",))
    body = payload(dept)
    body["grants"] = [
        {"service_slug": "one", "roles": ["viewer", "editor"]},
        {"service_slug": "two", "roles": ["user"]},
    ]
    response = client.post("/api/admin/people", json=body)
    assert response.status_code == 201 and response.json()["grants_created"] == 3
    person = db.scalar(select(Employee).where(Employee.employee_code == "MM900"))
    assert len(db.scalars(select(Grant).where(Grant.user_id == person.user.id)).all()) == 3
    sign_in(person.user)
    setup = client.post("/api/auth/onboard", json={"employee_code": "MM900", "pin": "827461"})
    assert setup.status_code == 200, setup.text
    response = client.post("/api/token/service", json={"slug": one.slug})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    assert set(jwt.decode(token, options={'verify_signature': False})["roles"]) == {"viewer", "editor"}


def test_invalid_service_role_rolls_back_entire_person(client, db, make_user, sign_in, make_service):
    admin_session(make_user, sign_in); dept = department(db); make_service("one", roles=("viewer",))
    body = payload(dept); body["grants"] = [{"service_slug": "one", "roles": ["not-a-role"]}]
    assert client.post("/api/admin/people", json=body).status_code == 422
    assert db.scalar(select(Employee).where(Employee.employee_code == "MM900")) is None


def test_existing_grants_change_and_revoke_reaches_denylist(client, db, make_user, sign_in, make_service, make_grant):
    actor = admin_session(make_user, sign_in); target = make_user(); service, roles = make_service("multi", roles=("viewer", "editor"))
    old = make_grant(target, service, roles["viewer"], granted_by=actor.id)
    response = client.post("/api/admin/grants/batch", json={
        "user_id": str(target.id), "services": [{"service_slug": "multi", "roles": ["editor"], "replace": True}],
    })
    assert response.status_code == 200 and response.json()["revoked"] == 1
    remaining = db.scalars(select(Grant).where(Grant.user_id == target.id)).all()
    assert [g.role.key for g in remaining] == ["editor"]
    assert db.scalar(select(Revocation).where(Revocation.subject == target.subject)) is not None
    assert db.get(Grant, old.id) is None


def test_people_and_agents_are_separate(client, db, make_user, sign_in):
    admin_session(make_user, sign_in); dept = department(db)
    assert client.post("/api/admin/agents", json={"name": "Invoice Bot", "slug": "invoice-bot", "kind": "automation"}).status_code == 201
    assert client.post("/api/admin/people", json=payload(dept)).status_code == 201
    assert len(client.get("/api/admin/agents").json()["agents"]) == 1
    people = client.get("/api/admin/employees").json()["employees"]
    assert all(p["full_name"] != "Invoice Bot" for p in people)
    assert db.scalar(select(AgentIdentity)).credential_hash is None


def test_delegate_cannot_escalate_beyond_own_authority(client, db, make_user, sign_in):
    delegate = make_user(); target = make_user()
    db.add(UserCapability(user_id=delegate.id, capability="admin_roles.manage")); db.commit(); sign_in(delegate)
    response = client.post(f"/api/admin/users/{target.id}/capabilities", json={"capability": "people.create"})
    assert response.status_code == 403


def test_last_active_it_admin_cannot_be_deactivated_or_stripped(client, db, make_user, sign_in):
    admin = admin_session(make_user, sign_in)
    assert client.patch(f"/api/admin/users/{admin.id}", json={"is_active": False}).status_code == 409
    assert client.patch(f"/api/admin/users/{admin.id}", json={"is_platform_admin": False}).status_code == 409
    assert client.patch(f"/api/admin/employees/{admin.employee_id}", json={"status": "exited"}).status_code == 409
    db.refresh(admin); assert admin.is_active and admin.is_platform_admin
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "admin.protected_attempt")).all()) == 3


def test_bulk_preview_and_commit_use_same_validation(client, db, make_user, sign_in, make_service):
    admin_session(make_user, sign_in); make_user(); service, _ = make_service("bulk", roles=("viewer",))
    request = {"slug": service.slug, "role": "viewer", "band": ["L3"], "preview": True}
    preview = client.post("/api/admin/grants/bulk", json=request)
    assert preview.status_code == 200 and preview.json()["would_create"] == 2
    request["preview"] = False
    committed = client.post("/api/admin/grants/bulk", json=request)
    assert committed.json()["created"] == preview.json()["would_create"]


def test_admin_adds_official_and_personal_email(client, db, make_user, sign_in):
    admin_session(make_user, sign_in); dept = department(db)
    body = payload(dept, work_email=None); body["auth_type"] = "local_pin"
    emp = client.post("/api/admin/people", json=body).json()["employee"]
    r = client.put(f"/api/admin/employees/{emp['id']}/emails",
                   json={"official": "Someone@m-mines.com", "personal": "someone@gmail.com"})
    assert r.status_code == 200, r.text
    assert r.json() == {"official": "someone@m-mines.com", "personal": "someone@gmail.com", "personal_verified": False}
    assert client.get(f"/api/admin/employees/{emp['id']}/emails").json()["personal"] == "someone@gmail.com"
    # a non-company address cannot be the official one, and clearing works
    assert client.put(f"/api/admin/employees/{emp['id']}/emails", json={"official": "x@gmail.com"}).status_code == 422
    assert client.put(f"/api/admin/employees/{emp['id']}/emails", json={"personal": ""}).json()["personal"] is None


def test_admin_removes_official_email_only_when_a_pin_exists(client, db, make_user, sign_in):
    admin_session(make_user, sign_in); dept = department(db)
    emp = client.post("/api/admin/people", json=payload(dept)).json()
    url = f"/api/admin/employees/{emp['employee']['id']}/emails"
    assert client.put(url, json={"official": ""}).status_code == 409  # no PIN yet
    from app.models import User
    u = db.get(User, __import__("uuid").UUID(emp["user"]["id"]))
    from datetime import datetime, timezone
    u.pin_set_at = datetime.now(timezone.utc); db.commit()
    assert client.put(url, json={"official": ""}).json()["official"] is None
    db.refresh(u)
    assert u.auth_type == "local_pin" and u.login_email is None
