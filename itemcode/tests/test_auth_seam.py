"""The auth seam (app/mmos_seam.py) and the one protected route (/api/me) — proving
stub-mode sign-in works, a protected route requires a valid token, and the deny-list
mechanic rejects a revoked subject. Mirrors servicedesk/tests/test_auth_seam.py.
"""
from tests.conftest import auth, token_for
from app.mmos_seam import revoke_subject


def test_healthz_needs_no_auth(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_me_requires_a_token(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "missing_token"


def test_me_returns_signed_in_identity_with_a_valid_token(client):
    token = token_for(name="Test Person", roles=["viewer"])
    r = client.get("/api/me", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Test Person"
    assert body["roles"] == ["viewer"]
    assert body["sub"] == "user:dev-local"


def test_bad_signature_is_rejected(client):
    r = client.get("/api/me", headers=auth("not-a-real-token.deadbeef"))
    assert r.status_code == 401


def test_revoked_subject_is_rejected(client):
    token = token_for(sub="user:revoke-me")
    ok = client.get("/api/me", headers=auth(token))
    assert ok.status_code == 200

    revoke_subject("user:revoke-me")
    r = client.get("/api/me", headers=auth(token))
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "revoked"


def test_mmos_health_and_accept_stub_routes(client):
    assert client.get("/_mmos/health").json()["ok"] is True

    token = token_for()
    r = client.post("/_mmos/accept", json={"token": token})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_dev_token_endpoint_mints_a_usable_token(client):
    r = client.post("/_dev/token", json={"name": "Someone", "roles": ["viewer"]})
    assert r.status_code == 200
    token = r.json()["token"]
    me = client.get("/api/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["name"] == "Someone"
