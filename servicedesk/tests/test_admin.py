"""Administration page endpoints (app/routers/admin.py): every route requires Service
Desk's own `admin` role, and the basic CRUD shape for each of the four tabs."""
from __future__ import annotations

from .conftest import auth, token_for

ADMIN = lambda: auth(token_for("MM-ITADMIN", roles=["admin"]))
NON_ADMIN = lambda: auth(token_for("MM88", roles=["requester"]))
AGENT_ONLY = lambda: auth(token_for("MM05", roles=["agent"]))


def test_non_admin_cannot_create_department(client):
    r = client.post("/api/admin/departments", json={"name": "Finance"}, headers=NON_ADMIN())
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "role_required"


def test_agent_role_alone_is_not_admin(client):
    """`agent` is a real Service Desk role (triage, propose, resolve) but it is not `admin`
    — this page's writes need the latter specifically."""
    r = client.post("/api/admin/departments", json={"name": "Finance"}, headers=AGENT_ONLY())
    assert r.status_code == 403


def test_missing_token_is_401_not_403(client):
    r = client.get("/api/admin/departments")
    assert r.status_code == 401


def test_admin_can_create_and_rename_and_deactivate_department(client):
    r = client.post("/api/admin/departments", json={"name": "Finance", "code": "FIN"}, headers=ADMIN())
    assert r.status_code == 201, r.text
    dept = r.json()
    assert dept["is_active"] is True

    r = client.patch(f"/api/admin/departments/{dept['id']}", json={"name": "Finance & Treasury"}, headers=ADMIN())
    assert r.status_code == 200
    assert r.json()["name"] == "Finance & Treasury"

    r = client.patch(f"/api/admin/departments/{dept['id']}", json={"is_active": False}, headers=ADMIN())
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_duplicate_department_name_rejected(client):
    client.post("/api/admin/departments", json={"name": "IT"}, headers=ADMIN())
    r = client.post("/api/admin/departments", json={"name": "IT"}, headers=ADMIN())
    assert r.status_code == 409


def test_local_role_grant_and_revoke(client):
    r = client.put(
        "/api/admin/roles/user:MM05",
        json={"employee_code": "MM05", "full_name": "Mandaleshvar Sharma", "department": "P-Spoke",
              "is_agent": True, "is_department_manager": True, "is_approver": True},
        headers=ADMIN(),
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["is_department_manager"] is True
    assert row["is_approver"] is True

    listed = client.get("/api/admin/roles", headers=ADMIN()).json()
    assert any(x["sub"] == "user:MM05" for x in listed)

    r = client.delete("/api/admin/roles/user:MM05", headers=ADMIN())
    assert r.status_code == 204
    listed = client.get("/api/admin/roles", headers=ADMIN()).json()
    assert not any(x["sub"] == "user:MM05" for x in listed)


def test_people_directory_lists_seed_personas(client):
    r = client.get("/api/admin/people", headers=ADMIN())
    assert r.status_code == 200
    subs = {p["sub"] for p in r.json()}
    assert "user:MM88" in subs and "user:MM81" in subs


def test_approval_rule_crud_and_default(client):
    r = client.post(
        "/api/admin/approval-rules",
        json={
            "name": "Automation over $ threshold", "department": "P-Spoke", "category": None,
            "priority": "high", "approvers": [{"sub": "user:MM81", "employee_code": "MM81"}],
            "mode": "any_of", "is_active": True,
        },
        headers=ADMIN(),
    )
    assert r.status_code == 201, r.text
    rule_id = r.json()["id"]
    assert r.json()["specificity"] == 2

    r = client.patch(
        f"/api/admin/approval-rules/{rule_id}",
        json={
            "name": "Automation over $ threshold", "department": "P-Spoke", "category": None,
            "priority": "urgent", "approvers": [{"sub": "user:MM81", "employee_code": "MM81"}],
            "mode": "any_of", "is_active": True,
        },
        headers=ADMIN(),
    )
    assert r.status_code == 200
    assert r.json()["priority"] == "urgent"

    r = client.put(
        "/api/admin/approval-default", json={"sub": "user:MM-ITADMIN", "employee_code": "MM-ITADMIN"},
        headers=ADMIN(),
    )
    assert r.status_code == 200
    assert client.get("/api/admin/approval-default", headers=ADMIN()).json()["employee_code"] == "MM-ITADMIN"

    r = client.delete(f"/api/admin/approval-rules/{rule_id}", headers=ADMIN())
    assert r.status_code == 204


def test_approval_preview_is_plain_language(client):
    client.post(
        "/api/admin/approval-rules",
        json={
            "name": "P-Spoke rule", "department": "P-Spoke", "category": None, "priority": None,
            "approvers": [{"sub": "user:MM81", "employee_code": "MM81"}], "mode": "any_of", "is_active": True,
        },
        headers=ADMIN(),
    )
    r = client.post(
        "/api/admin/approval-preview",
        json={"department": "P-Spoke", "category": None, "priority": "high", "requester_sub": "user:MM88"},
        headers=ADMIN(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "rule"
    assert "P-Spoke rule" in body["text"]
