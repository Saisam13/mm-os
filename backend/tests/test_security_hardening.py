"""Security regression suite. Synthetic users; no production access."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
from sqlalchemy import select
from starlette.requests import Request

from app.config import settings
from app.deps import client_ip, has_capability
from app.models import Department, Revocation, Session, UserCapability
from app.provision import issue_one_time_pin
from app.security import hash_pin
import pytest


def _cap(db, user, name, department=None):
    db.add(UserCapability(user_id=user.id, capability=name,
                          scope_department_id=department.id if department else None))
    db.commit()


def test_A01_people_editor_cannot_reset_platform_admin(db, client, make_user, sign_in):
    admin = make_user(is_platform_admin=True)
    editor = make_user()
    _cap(db, editor, "people.edit")
    sign_in(editor)
    response = client.post(f"/api/admin/users/{admin.id}/pin", json={"pin": "482619"})
    assert response.status_code == 403
    db.refresh(admin)
    assert admin.pin_hash is None


def test_A02_admin_role_delegate_cannot_promote_self(db, client, make_user, sign_in):
    delegate = make_user()
    _cap(db, delegate, "admin_roles.manage")
    sign_in(delegate)
    response = client.patch(f"/api/admin/users/{delegate.id}", json={"is_platform_admin": True})
    assert response.status_code == 403
    db.refresh(delegate)
    assert delegate.is_platform_admin is False


def test_A03_scoped_editor_cannot_modify_other_department(db, client, make_user, sign_in):
    dept = Department(key="audit-a", name="Audit A")
    db.add(dept)
    db.commit()
    editor = make_user()
    victim = make_user()
    _cap(db, editor, "people.edit", dept)
    sign_in(editor)
    assert client.patch(f"/api/admin/employees/{victim.employee_id}",
                        json={"full_name": "Changed outside scope"}).status_code == 403


def test_A03_scoped_delegate_cannot_redelegate_globally(db, client, make_user, sign_in):
    dept = Department(key="audit-a", name="Audit A")
    db.add(dept)
    db.commit()
    delegate, recipient = make_user(), make_user()
    _cap(db, delegate, "admin_roles.manage", dept)
    _cap(db, delegate, "people.edit", dept)
    sign_in(delegate)
    response = client.post(f"/api/admin/users/{recipient.id}/capabilities",
                           json={"capability": "people.edit", "scope_department_id": None})
    assert response.status_code == 403
    assert not has_capability(db, recipient, "people.edit")


def test_A04_employee_exit_revokes_existing_access(db, client, make_user,
                                                          make_service, make_grant, sign_in):
    operator = make_user(is_platform_admin=True)
    departed = make_user(is_platform_admin=True)
    svc, roles = make_service()
    make_grant(departed, svc, roles["viewer"])
    departed_session = sign_in(departed)
    client.cookies.clear()
    sign_in(operator)
    assert client.patch(f"/api/admin/employees/{departed.employee_id}",
                        json={"status": "exited"}).status_code == 200
    db.refresh(departed_session)
    assert departed_session.revoked_at is not None
    assert db.scalar(select(Revocation).where(Revocation.subject == departed.subject)) is not None
    client.cookies.clear()
    sign_in(departed)
    assert client.get("/api/admin/audit").status_code == 403
    assert client.post("/api/token/service", json={"slug": svc.slug}).status_code == 403


def test_A05_kill_blocks_shell_and_new_tokens(db, client, make_user, make_service,
                                                 make_grant, sign_in):
    operator, victim = make_user(is_platform_admin=True), make_user()
    svc, roles = make_service()
    make_grant(victim, svc, roles["viewer"])
    victim_session = sign_in(victim)
    victim_cookie = client.cookies.get(settings().cookie_name)
    client.cookies.clear()
    sign_in(operator)
    assert client.post(f"/api/admin/users/{victim.id}/kill").status_code == 200
    db.refresh(victim_session)
    assert victim_session.revoked_at is not None
    client.cookies.clear()
    client.cookies.set(settings().cookie_name, victim_cookie)
    assert client.post("/api/token/service", json={"slug": svc.slug}).status_code in (401, 403)


def test_A06_pin_reset_revokes_stolen_session(db, client, make_user, sign_in):
    operator, victim = make_user(is_platform_admin=True), make_user()
    session = sign_in(victim)
    client.cookies.clear()
    sign_in(operator)
    assert client.post(f"/api/admin/users/{victim.id}/pin", json={"pin": "938471"}).status_code == 200
    db.refresh(session)
    assert session.revoked_at is not None
    assert db.scalar(select(Revocation).where(Revocation.subject == victim.subject)) is not None


def test_A07_must_change_pin_blocks_token_issue(db, client, make_user,
                                                      make_service, make_grant):
    user = make_user()
    issue_one_time_pin(db, user, pin="864295")
    db.commit()
    svc, roles = make_service()
    make_grant(user, svc, roles["viewer"])
    login = client.post("/api/auth/pin", json={
        "employee_code": user.employee.employee_code, "pin": "864295"
    })
    assert login.status_code == 200 and login.json()["must_change"] is True
    assert client.post("/api/token/service", json={"slug": svc.slug}).status_code in (401, 403)


def test_A08_token_cannot_outlive_grant(db, client, make_user, make_service, make_grant, sign_in):
    user = make_user()
    svc, roles = make_service()
    expires = datetime.now(timezone.utc) + timedelta(seconds=30)
    make_grant(user, svc, roles["viewer"], expires_at=expires)
    sign_in(user)
    response = client.post("/api/token/service", json={"slug": svc.slug})
    assert response.status_code == 200
    claims = jwt.decode(response.json()["access_token"], options={'verify_signature': False})
    assert claims["exp"] <= expires.timestamp()
    assert response.json()["expires_in"] <= 30


def test_A09_grants_delegate_cannot_give_self_service_admin(db, client, make_user,
                                                        make_service, sign_in):
    delegate = make_user()
    svc, roles = make_service()
    _cap(db, delegate, "grants.add")
    sign_in(delegate)
    assert client.post("/api/admin/grants", json={
        "user_id": str(delegate.id), "slug": svc.slug, "role": "admin"
    }).status_code == 403


def test_A10_ordinary_user_cannot_read_account_via_patch(client, make_user, sign_in):
    ordinary, victim = make_user(), make_user()
    sign_in(ordinary)
    response = client.patch(f"/api/admin/users/{victim.id}", json={})
    assert response.status_code == 403
    assert "login_email" not in response.json()


def test_A11_account_route_preserves_last_admin(client, make_user, sign_in):
    from app.provision import FUNCTIONAL_JOB_TITLE
    admin = make_user(is_platform_admin=True)
    admin.employee.job_title = FUNCTIONAL_JOB_TITLE
    # Persist through the user factory's session.
    from sqlalchemy.orm import object_session
    object_session(admin).commit()
    sign_in(admin)
    assert client.patch(f"/api/admin/accounts/{admin.id}",
                        json={"is_active": False}).status_code == 409


def test_A12_pin_change_has_account_lockout(db, client, make_user, sign_in):
    user = make_user(pin_hash=hash_pin("875421"))
    sign_in(user)
    for _ in range(8):
        assert client.post("/api/auth/pin/change",
                           json={"pin": "000000", "new_pin": "982164"}).status_code == 401
    db.refresh(user)
    assert user.failed_pin_attempts >= settings().pin_max_attempts and user.locked_until is not None


def test_scoped_editor_can_edit_and_list_only_own_department(db, client, make_user, sign_in):
    dept = Department(key="security-test", name="Security test")
    db.add(dept)
    db.commit()
    editor, permitted, outside = make_user(), make_user(), make_user()
    permitted.employee.department_id = dept.id
    db.commit()
    _cap(db, editor, "people.edit", dept)
    _cap(db, editor, "people.view", dept)
    sign_in(editor)
    assert client.patch(f"/api/admin/employees/{permitted.employee_id}", json={"full_name": "Allowed edit"}).status_code == 200
    result = client.get("/api/admin/employees")
    assert result.status_code == 200
    assert str(permitted.employee_id) in result.text and str(outside.employee_id) not in result.text


def test_delegate_can_assign_permitted_role_to_other_person(db, client, make_user, make_service, make_grant, sign_in):
    delegate, recipient = make_user(), make_user()
    svc, roles = make_service()
    roles["viewer"].permissions = ["records.read"]
    roles["admin"].permissions = ["records.read", "service.admin"]
    db.commit()
    make_grant(delegate, svc, roles["admin"])
    _cap(db, delegate, "grants.add")
    sign_in(delegate)
    assert client.post("/api/admin/grants", json={"user_id": str(recipient.id), "slug": svc.slug, "role": "viewer"}).status_code == 201


@pytest.mark.parametrize("origin", [None, "https://foreign.invalid"])
def test_A14_browser_mutation_requires_own_origin(client, origin):
    client.headers.pop("origin", None)
    headers = {"Origin": origin} if origin else {}
    assert client.post("/api/auth/pin", json={"employee_code": "MM0", "pin": "999999"}, headers=headers).status_code == 403


def test_A13_forwarding_header_requires_trusted_peer():
    request = Request({"type": "http", "client": ("198.51.100.20", 4000), "headers": [(b"x-forwarded-for", b"127.0.0.1")]})
    assert client_ip(request) == "198.51.100.20"


def test_A21_retained_snapshot_includes_revocation_before_legacy_watermark(db, client, make_user, make_service):
    from app.security import hash_token as hash_service_key
    user = make_user()
    svc, _ = make_service(service_key_hash=hash_service_key("mmk_security_snapshot"))
    now = datetime.now(timezone.utc)
    db.add(Revocation(subject=user.subject, service_id=svc.id, reason="late_commit", revoked_at=now-timedelta(seconds=10), purge_after=now+timedelta(hours=1)))
    db.commit()
    result = client.get("/api/agent/revocations", params={"since": now.isoformat()}, headers={"Authorization": "Bearer mmk_security_snapshot"})
    assert result.status_code == 200 and result.json()["snapshot"] is True
    assert user.subject in {row["sub"] for row in result.json()["revoked_subjects"]}


def test_A22_disabled_service_can_fetch_its_disable_state(db, client, make_service):
    from app.security import hash_token as hash_service_key
    svc, _ = make_service(is_active=False, service_key_hash=hash_service_key("mmk_disabled"))
    result = client.get("/api/agent/revocations", headers={"Authorization": "Bearer mmk_disabled"})
    assert result.status_code == 200 and result.json()["service_active"] is False
    assert client.get("/api/agent/config", headers={"Authorization": "Bearer mmk_disabled"}).status_code == 401


def test_A23_bootstrap_preserves_demoted_inactive_admin(db, make_user):
    from app.seed import PLATFORM_ADMIN_EMAIL, seed_platform_admin, grant_admin_all_services
    target = make_user(login_email=PLATFORM_ADMIN_EMAIL, is_active=False, is_platform_admin=False)
    seed_platform_admin(db)
    assert grant_admin_all_services(db) == []
    db.commit()
    db.refresh(target)
    assert not target.is_active and not target.is_platform_admin


@pytest.mark.parametrize("target", ["//foreign.invalid", "/\\foreign.invalid", "/\t/foreign.invalid"])
def test_google_return_path_stays_inside_shell(target):
    from app.routers.auth import _safe_next
    assert _safe_next(target) == "/"
