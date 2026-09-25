"""Role files (app/roles_io.py) and the role admin endpoints around them."""
from __future__ import annotations

from jose import jwt
from sqlalchemy import select

from app import models
from app.roles_io import committed


def _itemcode(make_service):
    """itemcode as it is live today: viewer + admin, no permissions."""
    return make_service(slug="itemcode", roles=("viewer", "admin"))


def test_committed_itemcode_file_is_valid(client, make_user, sign_in, make_service):
    service, _ = _itemcode(make_service)
    sign_in(make_user(is_platform_admin=True))
    r = client.get("/api/admin/services/itemcode/roles/template")
    assert r.status_code == 200
    assert r.json()["committed"] is True
    keys = [x["key"] for x in r.json()["file"]["roles"]]
    assert keys == ["public", "associate", "manager", "admin"]


def test_dry_run_changes_nothing(client, db, make_user, sign_in, make_service, make_grant):
    service, roles = _itemcode(make_service)
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    viewer = make_user()
    make_grant(viewer, service, roles["viewer"])

    r = client.post("/api/admin/services/itemcode/roles/import", json=committed("itemcode"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["roles_created"] == ["public", "associate", "manager"]
    assert body["roles_removed"] == ["viewer"]
    assert len(body["grants_moved"]) == 1

    db.expire_all()
    keys = {r.key for r in db.scalars(select(models.ServiceRole).where(models.ServiceRole.service_id == service.id))}
    assert keys == {"viewer", "admin"}


def test_apply_moves_viewers_and_gives_everyone_a_role(
    client, db, make_user, make_employee, sign_in, make_service, make_grant
):
    service, roles = _itemcode(make_service)
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    old_viewer = make_user()
    make_grant(old_viewer, service, roles["viewer"])
    approver = make_user(employee=make_employee(is_approver=True))
    plain = make_user(auth_type="local_pin")

    r = client.post(
        "/api/admin/services/itemcode/roles/import?dry_run=false", json=committed("itemcode")
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roles_removed"] == ["viewer"]

    db.expire_all()
    def role_of(u):
        g = db.scalar(select(models.Grant).where(models.Grant.user_id == u.id, models.Grant.service_id == service.id))
        return g.role.key if g else None

    assert role_of(old_viewer) == "associate"   # moved, not dropped
    assert role_of(admin) == "admin"            # platform admin rule
    assert role_of(approver) == "manager"       # is_approver rule
    assert role_of(plain) == "public"           # default: the lowest, view-only level
    # the moved grant pushes a revocation so an old token's role cannot outlive the change
    assert db.scalar(select(models.Revocation).where(models.Revocation.subject == old_viewer.subject))

    after = {r["key"]: r for r in body["service_after"]["roles"]}
    assert "admin" in after["admin"]["permissions"]
    assert "admin" not in after["manager"]["permissions"]
    assert after["public"]["is_default"] is True
    assert after["associate"]["is_default"] is False


def test_missing_mode_keeps_hand_set_roles_and_all_mode_rederives(
    client, db, make_user, sign_in, make_service, make_grant
):
    service, roles = _itemcode(make_service)
    sign_in(make_user(is_platform_admin=True))
    client.post("/api/admin/services/itemcode/roles/import?dry_run=false", json=committed("itemcode"))
    db.expire_all()
    person = make_user()
    manager = db.scalar(select(models.ServiceRole).where(models.ServiceRole.service_id == service.id, models.ServiceRole.key == "manager"))
    make_grant(person, service, manager)

    again = client.post("/api/admin/services/itemcode/roles/import?dry_run=false", json=committed("itemcode")).json()
    assert again["grants_changed"] == [] and again["grants_created"] == []

    rederive = client.post(
        "/api/admin/services/itemcode/roles/import?dry_run=true&assign_mode=all", json=committed("itemcode")
    ).json()
    assert [(g["from"], g["to"]) for g in rederive["grants_changed"]] == [("manager", "public")]


def test_people_override_by_employee_code(client, db, make_user, make_employee, sign_in, make_service):
    service, _ = _itemcode(make_service)
    sign_in(make_user(is_platform_admin=True))
    target = make_user(employee=make_employee(employee_code="MM77"))
    doc = committed("itemcode")
    doc["assign"]["people"] = {"mm77": "manager", "NOBODY": "admin"}
    body = client.post("/api/admin/services/itemcode/roles/import", json=doc).json()
    created = {g["employee_code"]: g["role"] for g in body["grants_created"]}
    assert created["MM77"] == "manager"
    assert any("NOBODY".lower() in w for w in body["warnings"])


def test_invalid_file_lists_every_problem(client, make_user, sign_in, make_service):
    _itemcode(make_service)
    sign_in(make_user(is_platform_admin=True))
    bad = {
        "service": "itemcode",
        "permissions": {"a.view": "see"},
        "roles": [
            {"key": "Bad Key", "name": "x"},
            {"key": "ok", "name": "OK", "permissions": ["a.view", "a.nope"]},
        ],
        "assign": {"default": "ghost"},
    }
    r = client.post("/api/admin/services/itemcode/roles/import", json=bad)
    assert r.status_code == 422
    problems = r.json()["problems"]
    assert len(problems) == 3
    wrong_service = client.post("/api/admin/services/itemcode/roles/import", json={**committed("itemcode"), "service": "saleshub"})
    assert wrong_service.status_code == 422


def test_edit_and_delete_role(client, db, make_user, sign_in, make_service, make_grant):
    service, roles = _itemcode(make_service)
    sign_in(make_user(is_platform_admin=True))
    client.post("/api/admin/services/itemcode/roles/import?dry_run=false", json={**committed("itemcode"), "assign": None})

    r = client.patch("/api/admin/services/itemcode/roles/manager", json={"permissions": ["view"]})
    assert r.status_code == 200 and r.json()["permissions"] == ["view"]
    r = client.patch("/api/admin/services/itemcode/roles/manager", json={"permissions": ["made.up"]})
    assert r.status_code == 422

    holder = make_user()
    db.expire_all()
    manager = db.scalar(select(models.ServiceRole).where(models.ServiceRole.service_id == service.id, models.ServiceRole.key == "manager"))
    make_grant(holder, service, manager)
    assert client.delete("/api/admin/services/itemcode/roles/manager").status_code == 409

    added = client.post("/api/admin/services/itemcode/roles", json={"key": "auditor", "name": "Auditor", "permissions": ["view"]})
    assert added.status_code == 201
    assert client.delete("/api/admin/services/itemcode/roles/auditor").status_code == 200


def test_service_token_carries_permissions(client, db, make_user, sign_in, make_service, make_grant):
    service, _ = _itemcode(make_service)
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    client.post("/api/admin/services/itemcode/roles/import?dry_run=false", json=committed("itemcode"))
    r = client.post("/api/token/service", json={"slug": "itemcode"})
    assert r.status_code == 200, r.text
    claims = jwt.get_unverified_claims(r.json()["access_token"])
    assert claims["roles"] == ["admin"]
    assert "admin" in claims["permissions"]
