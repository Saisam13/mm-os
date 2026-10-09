"""The auth seam (app/mmos_seam.py) — stub sign-in, the protected route, and the deny-list
mechanic. Mirrors servicedesk/tests/test_auth_seam.py's coverage for this shell's smaller
surface.
"""
from tests.conftest import auth, token_for
from app.mmos_seam import revoke_subject


def test_missing_token_is_401(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["detail"] == {"error": "missing_token"}


def test_valid_token_reaches_protected_route(client):
    token = token_for(roles=["employee"])
    r = client.get("/api/me", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "user:dev-local"
    assert body["name"] == "Local Dev User"
    # No secret storage of any kind exists yet -- confirm the shape says so.
    assert body["vault"]["status"] == "not_implemented"


def test_malformed_token_is_401(client):
    r = client.get("/api/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_revoked_subject_is_rejected(client):
    token = token_for()
    ok = client.get("/api/me", headers=auth(token))
    assert ok.status_code == 200

    revoke_subject("user:dev-local")
    r = client.get("/api/me", headers=auth(token))
    assert r.status_code == 401
    assert r.json()["detail"] == {"error": "revoked"}


def test_health_needs_no_auth(client):
    assert client.get("/_mmos/health").json()["ok"] is True
    assert client.get("/healthz").json()["ok"] is True


def test_dev_token_endpoint_mints_a_usable_token(client):
    r = client.post("/_dev/token", json={"roles": ["employee"]})
    assert r.status_code == 200
    token = r.json()["token"]
    me = client.get("/api/me", headers=auth(token))
    assert me.status_code == 200


def test_mmos_accept_sets_session_cookie(client):
    token = token_for()
    r = client.post("/_mmos/accept", json={"token": token})
    assert r.status_code == 200
    assert r.json()["sub"] == "user:dev-local"
    assert "passwordmanager_mmos_at" in r.cookies


def test_index_page_shows_signed_in_name(client):
    token = token_for()
    r = client.get("/", headers=auth(token))
    assert r.status_code == 200
    assert "Local Dev User" in r.text
    assert "Your vault will live here" in r.text


def test_index_page_when_signed_out(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Not signed in" in r.text
