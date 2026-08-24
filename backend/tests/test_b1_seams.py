"""B1 (assembly, run 2) — targeted coverage for the seams fixed in this pass. Not exhaustive;
each of A1/A2's own suites already covers the routers these endpoints live in. See
handoff/b1-assembly.md for the full seam-by-seam account.

Covers:
  * the app-wide error envelope (main.py's new exception handler)
  * GET /api/public/services (section B.5)
  * GET /api/agent/org/chain (section B.6)
"""
from __future__ import annotations

from app.security import new_service_key


# ── error envelope, app-wide (section A.1) ────────────────────────────────────────────
def test_error_envelope_is_flat_with_request_id(client):
    r = client.get("/api/me")  # no session -> 401
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "no_session"
    assert isinstance(body["message"], str) and body["message"]
    assert "request_id" in body and body["request_id"]
    assert "detail" not in body


def test_error_envelope_carries_extra_keys(client, db, make_user, make_service, sign_in):
    user = make_user()
    sign_in(user)
    make_service(slug="denied-seam-test")

    r = client.post("/api/token/service", json={"slug": "denied-seam-test"})
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "grant_not_found"
    assert "request_id" in body


# ── GET /api/public/services (section B.5) ────────────────────────────────────────────
def test_public_services_needs_no_session(client, make_service):
    make_service(slug="pub-a", name="Public A", base_url="https://a.example.com", launch_mode="handoff")
    make_service(slug="pub-b", name="Public B", base_url="https://b.example.com", launch_mode="external")

    r = client.get("/api/public/services")
    assert r.status_code == 200
    body = r.json()
    slugs = {s["slug"]: s for s in body["services"]}
    assert slugs["pub-a"] == {
        "slug": "pub-a", "name": "Public A", "launch_url": "https://a.example.com", "session_owner": "mmos",
    }
    assert slugs["pub-b"]["session_owner"] == "service"
    # names and launch URLs only -- no roles, no health, no employee data.
    for row in body["services"]:
        assert set(row) == {"slug", "name", "launch_url", "session_owner"}


def test_public_services_excludes_inactive(client, make_service, db):
    service, _ = make_service(slug="pub-inactive")
    service.is_active = False
    db.commit()

    r = client.get("/api/public/services")
    assert "pub-inactive" not in {s["slug"] for s in r.json()["services"]}


# ── GET /api/agent/org/chain (section B.6) ────────────────────────────────────────────
def _keyed_service(db, make_service, **kw):
    service, roles = make_service(**kw)
    raw, digest = new_service_key()
    service.service_key_hash = digest
    db.commit()
    return service, roles, raw


def test_org_chain_walks_manager_id_up_and_stops_at_the_top(
    client, db, make_employee, make_user, make_service
):
    _, _, raw_key = _keyed_service(db, make_service, slug="servicedesk-seam-test")

    top = make_employee(employee_code="MMTOP", full_name="Top Boss", approval_level="L5 (Apex)")
    top_user = make_user(employee=top, auth_type="google")
    mid = make_employee(employee_code="MMMID", full_name="Middle Manager", manager_id=top.id, approval_level="L3 (HOD)")
    mid_user = make_user(employee=mid, auth_type="google")
    leaf = make_employee(employee_code="MMLEAF", full_name="Leaf Person", manager_id=mid.id, approval_level="Operational")
    leaf_user = make_user(employee=leaf, auth_type="google")

    r = client.get(
        "/api/agent/org/chain",
        params={"sub": leaf_user.subject},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200
    chain = r.json()["chain"]
    assert [n["employee_code"] for n in chain] == ["MMLEAF", "MMMID", "MMTOP"]
    assert chain[0]["manager_sub"] == mid_user.subject
    assert chain[-1]["manager_sub"] is None
    # minimum disclosure -- exactly the fields approval routing needs, nothing else.
    assert set(chain[0]) == {
        "sub", "employee_code", "full_name", "department", "approval_level",
        "is_approver", "manager_sub", "email",
    }


def test_org_chain_degrades_gracefully_with_no_manager(client, db, make_employee, make_user, make_service):
    _, _, raw_key = _keyed_service(db, make_service, slug="servicedesk-seam-test-2")
    solo = make_employee(employee_code="MMSOLO")
    solo_user = make_user(employee=solo, auth_type="google")

    r = client.get(
        "/api/agent/org/chain",
        params={"sub": solo_user.subject},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200
    chain = r.json()["chain"]
    assert len(chain) == 1
    assert chain[0]["manager_sub"] is None


def test_org_chain_degrades_gracefully_for_unknown_subject(client, db, make_service):
    _, _, raw_key = _keyed_service(db, make_service, slug="servicedesk-seam-test-3")

    r = client.get(
        "/api/agent/org/chain",
        params={"sub": "user:00000000-0000-0000-0000-000000000000"},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200
    assert r.json()["chain"] == []


def test_org_chain_requires_service_key(client):
    r = client.get("/api/agent/org/chain", params={"sub": "user:whoever"})
    assert r.status_code == 401


# ── admin API shape drift (section A.4) ───────────────────────────────────────────────
def test_service_roles_include_description(client, make_employee, make_user, make_service, sign_in):
    admin_emp = make_employee(employee_code="MMADMIN")
    admin = make_user(employee=admin_emp, auth_type="google", is_platform_admin=True)
    sign_in(admin)
    make_service(slug="role-desc-test", roles=())

    r = client.post(
        "/api/admin/services/role-desc-test/roles",
        json={"key": "viewer", "name": "Viewer", "description": "Read-only access."},
    )
    assert r.status_code == 201
    assert r.json()["description"] == "Read-only access."

    listed = client.get("/api/admin/services").json()["services"]
    svc = next(s for s in listed if s["slug"] == "role-desc-test")
    assert svc["roles"][0]["description"] == "Read-only access."


def test_grants_expose_granted_by_and_names(
    client, db, make_employee, make_user, make_service, make_grant, sign_in
):
    admin_emp = make_employee(employee_code="MMADMIN2", full_name="Admin Person")
    admin = make_user(employee=admin_emp, auth_type="google", is_platform_admin=True)
    sign_in(admin)

    target_emp = make_employee(employee_code="MMTARGET", full_name="Target Person")
    target = make_user(employee=target_emp)
    service, roles = make_service(slug="granted-by-test")
    grant = make_grant(target, service, roles["viewer"], granted_by=admin.id)

    r = client.get("/api/admin/grants", params={"service": "granted-by-test"})
    assert r.status_code == 200
    row = r.json()["grants"][0]
    assert row["id"] == str(grant.id)
    assert row["user"] == {"id": str(target.id), "name": "Target Person", "employee_code": "MMTARGET"}
    assert row["service"] == {"slug": "granted-by-test", "name": service.name}
    assert row["role"]["key"] == "viewer"
    assert row["granted_by"] == {"id": str(admin.id), "name": "Admin Person"}


def test_llm_overview_has_name_and_usage_30d_key(client, db, make_employee, make_user, make_service, sign_in):
    from app import models

    admin_emp = make_employee(employee_code="MMADMIN3")
    admin = make_user(employee=admin_emp, auth_type="google", is_platform_admin=True)
    sign_in(admin)
    service, _ = make_service(slug="llm-shape-test", name="LLM Shape Test")
    db.add(models.LlmRegistration(service_id=service.id, provider="anthropic"))
    db.commit()

    r = client.get("/api/admin/llm")
    assert r.status_code == 200
    row = next(x for x in r.json()["registrations"] if x["slug"] == "llm-shape-test")
    assert row["name"] == "LLM Shape Test"
    assert "usage_30d" in row and "usage" not in row


def test_audit_entries_expose_actor_and_service_names(client, db, make_employee, make_user, sign_in):
    admin_emp = make_employee(employee_code="MMADMIN4", full_name="Audit Admin")
    admin = make_user(employee=admin_emp, auth_type="google", is_platform_admin=True)
    sign_in(admin)

    created = client.post(
        "/api/admin/services",
        json={"slug": "audit-shape-test", "name": "Audit Shape Test", "base_url": "https://audit-shape-test.example.com"},
    )
    assert created.status_code == 201

    r = client.get("/api/admin/audit", params={"action": "service.create"})
    assert r.status_code == 200
    row = next(e for e in r.json()["entries"] if e["target_type"] == "service")
    assert row["actor"] == {"id": str(admin.id), "name": "Audit Admin"}
    assert row["service"] == {"slug": "audit-shape-test", "name": "Audit Shape Test"}
