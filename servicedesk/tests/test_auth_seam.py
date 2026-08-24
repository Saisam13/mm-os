"""The auth seam (app/mmos_seam.py) — role guard shape and the deny-list mechanic, both
part of docs/05-service-integration.md's contract even though there is no live MM OS to
verify a real token against in this sandbox (see `## Assumptions`).
"""
from tests.conftest import auth, token_for
from app.mmos_seam import revoke_subject


def test_missing_token_is_401(client):
    r = client.get("/api/tickets/mine")
    assert r.status_code == 401


def test_role_required_403_shape(client):
    r = client.get("/api/tickets/queue", headers=auth(token_for("operator")))  # default role: requester
    assert r.status_code == 403
    body = r.json()["detail"]
    assert body == {"error": "role_required", "need": "agent", "have": ["requester"]}


def test_revoked_subject_is_rejected(client):
    token = token_for("operator")
    ok = client.get("/api/tickets/mine", headers=auth(token))
    assert ok.status_code == 200

    revoke_subject("user:op-1")
    r = client.get("/api/tickets/mine", headers=auth(token))
    assert r.status_code == 401


def test_health_and_badge_need_no_auth(client):
    assert client.get("/_mmos/health").json()["ok"] is True
    assert client.get("/api/badge", params={"sub": "user:nobody"}).status_code == 200


def test_dev_token_endpoint_mints_a_usable_token(client):
    r = client.post("/_dev/token", json={"persona": "hod", "roles": ["agent"]})
    assert r.status_code == 200
    token = r.json()["token"]
    me = client.get("/api/tickets/mine", headers=auth(token))
    assert me.status_code == 200


def test_dev_token_endpoint_rejects_unknown_persona(client):
    r = client.post("/_dev/token", json={"persona": "ceo"})
    assert r.status_code == 404
