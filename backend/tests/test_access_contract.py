"""The access contract `mmos-access/1` (docs/17-access-contract.md), MM OS's side.

The manifest fetch is mocked at the httpx boundary: `access_contract.httpx.AsyncClient` is
swapped for one whose transport answers from a routing table keyed on the URL.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import jwt
from sqlalchemy import select

from app import access_contract, models
from app.security import permissions_version

PERMS = {"view": "See purchase orders", "edit": "Change purchase orders", "setup": "Settings"}


def _hash(keys, n):
    return hashlib.sha256(json.dumps(sorted(keys), separators=(",", ":")).encode()).hexdigest()[:n]


def manifest(slug, perms=PERMS, roles=None, **over):
    roles = roles if roles is not None else [
        {"key": "viewer", "name": "Viewer", "permissions": ["view"]},
        {"key": "editor", "name": "Editor", "permissions": ["view", "edit"]},
        {"key": "admin", "name": "Admin", "permissions": ["view", "edit", "setup"]},
    ]
    body = {"contract": "mmos-access/1", "service": slug, "permissions": perms,
            "suggested_roles": roles, "catalog_hash": _hash(perms, 16)}
    body.update(over)
    return httpx.Response(200, json=body)


@pytest.fixture()
def fake_web(monkeypatch):
    routes: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        resp = routes.get(str(request.url))
        if resp is None:
            raise httpx.ConnectError("Name or service not known", request=request)
        return resp

    real = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs.get("timeout") == 5.0 and kwargs.get("follow_redirects") is True
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(access_contract.httpx, "AsyncClient", factory)
    return routes


@pytest.fixture()
def admin(make_user, sign_in):
    user = make_user(is_platform_admin=True)
    sign_in(user)
    return user


def _svc(make_service, slug, catalog=None, roles=("viewer", "admin")):
    service, made = make_service(slug=slug, base_url=f"https://{slug}.example", roles=roles,
                                 permission_catalog=catalog or {})
    return service, made


# ── catalog_hash / pv ─────────────────────────────────────────────────────────
def test_hash_serialisation_matches_the_spec():
    # JS JSON.stringify(["edit","setup","view"]) == '["edit","setup","view"]'
    expected = hashlib.sha256(b'["edit","setup","view"]').hexdigest()
    assert access_contract.catalog_hash(["view", "setup", "edit"]) == expected[:16]
    assert access_contract.catalog_hash({"view": "", "edit": "", "setup": ""}) == expected[:16]
    assert permissions_version(["view", "edit", "setup"]) == expected[:12]
    assert permissions_version([]) == hashlib.sha256(b"[]").hexdigest()[:12]


# ── 1. contract status ────────────────────────────────────────────────────────
def test_enforces_when_keys_match(client, admin, make_service, fake_web):
    _svc(make_service, "po-ok", catalog=PERMS)
    fake_web["https://po-ok.example/_mmos/manifest"] = manifest("po-ok")
    body = client.get("/api/admin/services/po-ok/contract").json()
    assert body["status"] == "enforces"
    assert body["added"] == [] and body["removed"] == []
    assert body["catalog_hash"] == _hash(PERMS, 16)


def test_drift_lists_added_and_removed(client, admin, make_service, fake_web):
    _svc(make_service, "po-drift", catalog={"view": "x", "approve": "y"})
    fake_web["https://po-drift.example/_mmos/manifest"] = manifest("po-drift")
    body = client.get("/api/admin/services/po-drift/contract").json()
    assert body["status"] == "drift"
    assert body["added"] == ["edit", "setup"]
    assert body["removed"] == ["approve"]


@pytest.mark.parametrize("response,needle", [
    (httpx.Response(404, text="nope"), "HTTP 404"),
    (httpx.Response(200, text="<html>parked</html>", headers={"content-type": "text/html"}), "not JSON"),
    (None, "catalog_hash"),
    ("wrong-contract", "contract"),
    ("wrong-service", "not"),
])
def test_no_manifest(client, admin, make_service, fake_web, response, needle):
    _svc(make_service, "po-none", catalog=PERMS)
    if response is None:
        response = manifest("po-none", catalog_hash="0" * 16)
    elif response == "wrong-contract":
        response = manifest("po-none", contract="mmos-access/0")
    elif response == "wrong-service":
        response = manifest("po-none", service="someone-else")
    fake_web["https://po-none.example/_mmos/manifest"] = response
    body = client.get("/api/admin/services/po-none/contract").json()
    assert body["status"] == "no_manifest"
    assert needle in body["detail"]


def test_undeclared_permission_in_a_suggested_role_is_invalid(client, admin, make_service, fake_web):
    _svc(make_service, "po-bad", catalog=PERMS)
    fake_web["https://po-bad.example/_mmos/manifest"] = manifest(
        "po-bad", roles=[{"key": "viewer", "name": "Viewer", "permissions": ["view", "ghost"]}])
    body = client.get("/api/admin/services/po-bad/contract").json()
    assert body["status"] == "no_manifest" and "ghost" in body["detail"]


def test_unreachable(client, admin, make_service, fake_web):
    _svc(make_service, "po-dead")
    _svc(make_service, "po-500")
    fake_web["https://po-500.example/_mmos/manifest"] = httpx.Response(503)
    assert client.get("/api/admin/services/po-dead/contract").json()["status"] == "unreachable"
    assert client.get("/api/admin/services/po-500/contract").json()["status"] == "unreachable"


def test_redirects_are_followed(client, admin, make_service, fake_web):
    _svc(make_service, "po-moved", catalog=PERMS)
    fake_web["https://po-moved.example/_mmos/manifest"] = httpx.Response(
        301, headers={"location": "https://po-new.example/_mmos/manifest"})
    fake_web["https://po-new.example/_mmos/manifest"] = manifest("po-moved")
    assert client.get("/api/admin/services/po-moved/contract").json()["status"] == "enforces"


def test_bulk_check_and_admin_only(client, db, make_user, make_service, sign_in, fake_web):
    _svc(make_service, "bulk-a", catalog=PERMS)
    _svc(make_service, "bulk-b")
    fake_web["https://bulk-a.example/_mmos/manifest"] = manifest("bulk-a")
    fake_web["https://bulk-b.example/_mmos/manifest"] = httpx.Response(404)

    sign_in(make_user())
    assert client.get("/api/admin/services/contract").status_code == 403
    assert client.get("/api/admin/services/bulk-a/contract").status_code == 403

    sign_in(make_user(is_platform_admin=True))
    body = client.get("/api/admin/services/contract").json()
    status = {s["slug"]: s["status"] for s in body["services"]}
    assert status == {"bulk-a": "enforces", "bulk-b": "no_manifest"}
    assert client.get("/api/admin/services/nope/contract").status_code == 404


# ── 2. import from service ────────────────────────────────────────────────────
def test_import_from_service_builds_a_draft_for_the_dry_run(
    client, db, admin, make_service, make_user, make_grant, fake_web
):
    service, roles = _svc(make_service, "po-imp", roles=("viewer", "auditor", "admin"))
    db.expire_all()
    viewer_role = db.scalar(select(models.ServiceRole).where(
        models.ServiceRole.service_id == service.id, models.ServiceRole.key == "viewer"))
    viewer_role.name, viewer_role.description, viewer_role.is_default = "Reader", "Reads things", True
    for order, key in enumerate(("viewer", "auditor", "admin")):
        roles[key].sort_order = (order + 1) * 10
    db.commit()
    holder = make_user()
    make_grant(holder, service, roles["auditor"])
    fake_web["https://po-imp.example/_mmos/manifest"] = manifest("po-imp")

    r = client.get("/api/admin/services/po-imp/roles/from-service")
    assert r.status_code == 200, r.text
    body = r.json()
    file = body["file"]
    assert body["contract"]["status"] == "drift"
    assert file["permissions"] == PERMS
    assert file["remove_unlisted"] is False and "assign" not in file
    # suggested roles in order, MM OS's own role kept where it was (after viewer)
    assert [x["key"] for x in file["roles"]] == ["viewer", "auditor", "editor", "admin"]
    viewer = file["roles"][0]
    assert (viewer["name"], viewer["description"], viewer["default"]) == ("Reader", "Reads things", True)
    assert file["roles"][2]["permissions"] == ["view", "edit"]
    auditor = file["roles"][1]
    assert auditor["permissions"] == []
    assert any("auditor" in n for n in body["notes"])

    # The kept role has nothing it can do yet, so the dry run refuses the draft as it stands.
    r = client.post("/api/admin/services/po-imp/roles/import", json=file)
    assert r.status_code == 422
    assert any("auditor" in p and "no permissions" in p for p in r.json()["problems"])

    # Once the admin fixes it, the draft goes through the ordinary dry run, then applies.
    auditor["permissions"] = ["view"]
    preview = client.post("/api/admin/services/po-imp/roles/import", json=file).json()
    assert preview["dry_run"] is True and preview["catalog_changed"] is True
    assert preview["roles_created"] == ["editor"] and preview["roles_removed"] == []
    assert preview["grants_created"] == []
    applied = client.post("/api/admin/services/po-imp/roles/import?dry_run=false", json=file)
    assert applied.status_code == 200
    db.expire_all()
    assert set(db.get(models.Service, service.id).permission_catalog) == set(PERMS)
    assert client.get("/api/admin/services/po-imp/contract").json()["status"] == "enforces"


def test_import_from_service_without_manifest_says_so(client, admin, make_service, fake_web):
    _svc(make_service, "po-noimp")
    fake_web["https://po-noimp.example/_mmos/manifest"] = httpx.Response(404)
    r = client.get("/api/admin/services/po-noimp/roles/from-service")
    assert r.status_code == 422
    assert "does not publish a permission list" in r.json()["message"]
    r = client.get("/api/admin/services/po-noimp-x/roles/from-service")
    assert r.status_code == 404
    _svc(make_service, "po-gone")
    assert client.get("/api/admin/services/po-gone/roles/from-service").status_code == 502


# ── 3. pv claim ───────────────────────────────────────────────────────────────
def test_service_token_carries_pv(client, db, make_user, sign_in, make_service, make_grant):
    service, made = _svc(make_service, "po-pv", catalog=PERMS, roles=("viewer", "editor"))
    db.expire_all()
    for key, perms in (("viewer", ["view"]), ("editor", ["edit", "view"])):
        role = db.scalar(select(models.ServiceRole).where(
            models.ServiceRole.service_id == service.id, models.ServiceRole.key == key))
        role.permissions = perms
    db.commit()
    user = make_user()
    make_grant(user, service, made["viewer"])
    make_grant(user, service, made["editor"])
    sign_in(user)
    r = client.post("/api/token/service", json={"slug": "po-pv"})
    assert r.status_code == 200, r.text
    claims = jwt.decode(r.json()["access_token"], options={'verify_signature': False})
    assert claims["permissions"] == ["edit", "view"]
    assert claims["pv"] == hashlib.sha256(b'["edit","view"]').hexdigest()[:12]


def test_pv_for_a_role_without_permissions(client, make_user, sign_in, make_service, make_grant):
    service, made = _svc(make_service, "po-pv0")
    user = make_user()
    make_grant(user, service, made["viewer"])
    sign_in(user)
    claims = jwt.decode(client.post("/api/token/service", json={"slug": "po-pv0"}).json()["access_token"], options={'verify_signature': False})
    assert claims["permissions"] == [] and claims["pv"] == permissions_version([])


# ── 4. no empty permission lists ──────────────────────────────────────────────
def test_empty_permissions_refused_when_service_declares_some(client, admin, make_service):
    _svc(make_service, "po-empty", catalog=PERMS)
    r = client.post("/api/admin/services/po-empty/roles", json={"key": "idle", "name": "Idle"})
    assert r.status_code == 422 and r.json()["error"] == "empty_permissions"
    r = client.post("/api/admin/services/po-empty/roles", json={"key": "idle", "name": "Idle", "permissions": []})
    assert r.status_code == 422
    ok = client.post("/api/admin/services/po-empty/roles", json={"key": "reader", "name": "Reader", "permissions": ["view"]})
    assert ok.status_code == 201
    r = client.patch("/api/admin/services/po-empty/roles/reader", json={"permissions": []})
    assert r.status_code == 422 and "at least one" in r.json()["message"]
    r = client.patch("/api/admin/services/po-empty/roles/reader", json={"permissions": None})
    assert r.status_code == 422
    # renaming does not touch permissions and is fine
    assert client.patch("/api/admin/services/po-empty/roles/reader", json={"name": "Reader 2"}).status_code == 200


def test_empty_permissions_still_fine_without_a_catalog(client, admin, make_service):
    _svc(make_service, "po-legacy")
    r = client.post("/api/admin/services/po-legacy/roles", json={"key": "idle", "name": "Idle"})
    assert r.status_code == 201


def test_role_file_rejects_a_role_with_no_permissions(client, admin, make_service):
    _svc(make_service, "po-rf")
    doc = {"service": "po-rf", "permissions": PERMS,
           "roles": [{"key": "viewer", "name": "Viewer", "permissions": []},
                     {"key": "admin", "name": "Admin", "permissions": ["view", "edit", "setup"]}]}
    r = client.post("/api/admin/services/po-rf/roles/import", json=doc)
    assert r.status_code == 422
    assert r.json()["problems"] == ["role 'viewer' has no permissions; give it at least one from the catalog"]


# ── 5. view as ────────────────────────────────────────────────────────────────
def test_view_as_matches_the_token(client, db, make_user, sign_in, make_service, make_grant, fake_web):
    service, made = _svc(make_service, "po-va", catalog=PERMS, roles=("viewer", "editor"))
    other, other_roles = _svc(make_service, "po-va2")
    expired, expired_roles = _svc(make_service, "po-va3")
    db.expire_all()
    for key, perms in (("viewer", ["view"]), ("editor", ["view", "edit"])):
        role = db.scalar(select(models.ServiceRole).where(
            models.ServiceRole.service_id == service.id, models.ServiceRole.key == key))
        role.permissions = perms
    db.commit()
    person = make_user()
    make_grant(person, service, made["viewer"])
    make_grant(person, service, made["editor"])
    make_grant(person, other, other_roles["admin"])
    make_grant(person, expired, expired_roles["viewer"],
               expires_at=datetime.now(timezone.utc) - timedelta(days=1))

    sign_in(make_user())
    assert client.get(f"/api/admin/people/{person.id}/access").status_code == 403

    sign_in(make_user(is_platform_admin=True))
    fake_web["https://po-va.example/_mmos/manifest"] = manifest("po-va")
    client.get("/api/admin/services/po-va/contract")  # fills the cache for po-va only
    r = client.get(f"/api/admin/people/{person.id}/access")
    assert r.status_code == 200, r.text
    rows = {x["slug"]: x for x in r.json()["services"]}
    assert set(rows) == {"po-va", "po-va2"}  # expired grant is not access
    assert rows["po-va"]["roles"] == ["editor", "viewer"]
    assert rows["po-va"]["permissions"] == ["edit", "view"]
    assert rows["po-va"]["contract"]["status"] == "enforces"
    assert rows["po-va2"]["permissions"] == [] and rows["po-va2"]["contract"] is None
    assert r.json()["can_sign_in"] is True

    # ... and it is exactly what the service would receive.
    sign_in(person)
    claims = jwt.decode(client.post("/api/token/service", json={"slug": "po-va"}).json()["access_token"], options={'verify_signature': False})
    assert (claims["roles"], claims["permissions"], claims["pv"]) == (
        rows["po-va"]["roles"], rows["po-va"]["permissions"], rows["po-va"]["pv"])
    # view-as minted nothing: the only token.issue is the one just above
    assert len(list(db.scalars(select(models.AuditLog).where(models.AuditLog.action == "token.issue")))) == 1


def test_view_as_unknown_person(client, admin):
    import uuid
    assert client.get(f"/api/admin/people/{uuid.uuid4()}/access").status_code == 404
