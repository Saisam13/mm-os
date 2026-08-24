"""Owned by A2 — Tokens and Control Plane.

Covers the three routers this agent owns: `routers/tokens.py` (the handoff),
`routers/agent.py` (service heartbeat/config/revocations) and `routers/platform.py`
(admin: services, grants, LLM control plane, audit, kill).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select

from app import models
from app.security import new_service_key


def _service_with_key(db, make_service, **kw):
    """make_service() plus a real key + hash, the way `rotate-key` would set one up."""
    service, roles = make_service(**kw)
    raw, digest = new_service_key()
    service.service_key_hash = digest
    db.commit()
    return service, roles, raw


def _since(minutes=1) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


# ── token handoff (routers/tokens.py) ─────────────────────────────────────────────────
def test_token_service_denied_without_grant(client, make_user, make_service, sign_in):
    user = make_user()
    sign_in(user)
    make_service(slug="noaccess")

    r = client.post("/api/token/service", json={"slug": "noaccess"})
    assert r.status_code == 403
    assert r.json()["error"] == "grant_not_found"


def test_token_service_denied_for_unknown_slug(client, make_user, sign_in):
    user = make_user()
    sign_in(user)

    r = client.post("/api/token/service", json={"slug": "does-not-exist"})
    assert r.status_code == 403
    assert r.json()["error"] == "grant_not_found"


def test_token_service_issues_token_scoped_to_that_service(
    db, client, make_user, make_service, make_grant, sign_in
):
    user = make_user()
    sign_in(user)
    service, roles = make_service(slug="itemcode")
    make_grant(user, service, roles["viewer"])

    r = client.post("/api/token/service", json={"slug": "itemcode"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["token_type"] == "Bearer"
    assert body["launch_url"] == f"{service.base_url}/_mmos/accept#token={body['access_token']}"

    claims = jwt.get_unverified_claims(body["access_token"])
    assert claims["aud"] == "itemcode"
    assert claims["roles"] == ["viewer"]
    assert claims["sub"] == user.subject

    issued = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "token.issue"))
    assert issued is not None and issued.service_id == service.id


def test_token_service_denied_on_expired_grant(db, client, make_user, make_service, make_grant, sign_in):
    user = make_user()
    sign_in(user)
    service, roles = make_service(slug="stale")
    make_grant(user, service, roles["viewer"], expires_at=datetime.now(timezone.utc) - timedelta(days=1))

    r = client.post("/api/token/service", json={"slug": "stale"})
    assert r.status_code == 403
    assert r.json()["error"] == "grant_not_found"

    denied = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "token.denied"))
    assert denied is not None


# ── revocations and the deny-list (routers/agent.py + platform.py) ───────────────────
def test_grant_deletion_writes_revocation_and_appears_immediately(
    db, client, make_user, make_service, make_grant, sign_in
):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    target = make_user()
    service, roles, key = _service_with_key(db, make_service, slug="itemcode")
    grant = make_grant(target, service, roles["viewer"])

    r = client.delete(f"/api/admin/grants/{grant.id}")
    assert r.status_code == 200, r.text
    assert db.get(models.Grant, grant.id) is None  # the delete half of the transaction

    poll = client.get(
        "/api/agent/revocations", params={"since": _since()}, headers={"Authorization": f"Bearer {key}"}
    )
    assert poll.status_code == 200, poll.text
    subs = [s["sub"] for s in poll.json()["revoked_subjects"]]
    assert target.subject in subs


def test_revocations_scoped_per_service_never_leak(
    db, client, make_user, make_service, make_grant, sign_in
):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    target = make_user()
    svc_a, roles_a, key_a = _service_with_key(db, make_service, slug="svc-a")
    svc_b, _roles_b, key_b = _service_with_key(db, make_service, slug="svc-b")
    grant = make_grant(target, svc_a, roles_a["viewer"])

    client.delete(f"/api/admin/grants/{grant.id}")

    poll_b = client.get(
        "/api/agent/revocations", params={"since": _since()}, headers={"Authorization": f"Bearer {key_b}"}
    )
    assert target.subject not in [s["sub"] for s in poll_b.json()["revoked_subjects"]]

    poll_a = client.get(
        "/api/agent/revocations", params={"since": _since()}, headers={"Authorization": f"Bearer {key_a}"}
    )
    assert target.subject in [s["sub"] for s in poll_a.json()["revoked_subjects"]]


def test_kill_writes_subject_revocation_and_drops_poll_interval(
    db, client, make_user, make_service, sign_in
):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    target = make_user()
    service, _roles, key = _service_with_key(db, make_service, slug="kill-svc")

    r = client.post(f"/api/admin/users/{target.id}/kill")
    assert r.status_code == 200, r.text

    poll = client.get(
        "/api/agent/revocations", params={"since": _since()}, headers={"Authorization": f"Bearer {key}"}
    )
    body = poll.json()
    assert target.subject in [s["sub"] for s in body["revoked_subjects"]]
    assert body["poll_after_seconds"] == 5


# ── service registry admin ────────────────────────────────────────────────────────────
def test_rotate_key_invalidates_old_key_immediately(db, client, make_user, make_service, sign_in):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    service, _roles, old_key = _service_with_key(db, make_service, slug="rotator")

    still_good = client.get("/api/agent/config", headers={"Authorization": f"Bearer {old_key}"})
    assert still_good.status_code == 200

    r = client.post(f"/api/admin/services/{service.slug}/rotate-key")
    assert r.status_code == 200, r.text
    new_key = r.json()["service_key"]
    assert new_key and new_key != old_key

    old_after = client.get("/api/agent/config", headers={"Authorization": f"Bearer {old_key}"})
    assert old_after.status_code == 401

    new_after = client.get("/api/agent/config", headers={"Authorization": f"Bearer {new_key}"})
    assert new_after.status_code == 200


# ── non-admin lockout on every /api/admin/* route this agent owns ────────────────────
def _admin_routes():
    grant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    return [
        ("GET", "/api/admin/services", None),
        ("POST", "/api/admin/services", {"slug": "x", "name": "X", "base_url": "https://x.example"}),
        ("PATCH", "/api/admin/services/x", {"name": "Y"}),
        ("POST", "/api/admin/services/x/roles", {"key": "viewer", "name": "Viewer"}),
        ("POST", "/api/admin/services/x/rotate-key", None),
        ("GET", "/api/admin/grants", None),
        ("POST", "/api/admin/grants", {"user_id": str(user_id), "slug": "x", "role": "viewer"}),
        ("DELETE", f"/api/admin/grants/{grant_id}", None),
        ("POST", "/api/admin/grants/bulk", {"slug": "x", "role": "viewer"}),
        ("GET", "/api/admin/llm", None),
        ("POST", "/api/admin/llm/x/toggle", {"enabled": False}),
        ("GET", "/api/admin/audit", None),
        ("POST", f"/api/admin/users/{user_id}/kill", None),
    ]


def test_every_owned_admin_route_returns_403_without_platform_admin(client, make_user, sign_in):
    non_admin = make_user()
    sign_in(non_admin)

    for method, path, body in _admin_routes():
        r = client.request(method, path, json=body)
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}: {r.text}"


def test_admin_routes_require_a_session_at_all(client):
    for method, path, body in _admin_routes():
        r = client.request(method, path, json=body)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}: {r.text}"


# ── LLM control plane ──────────────────────────────────────────────────────────────────
def test_llm_toggle_bumps_config_version(db, client, make_user, make_service, sign_in):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    service, _roles, key = _service_with_key(db, make_service, slug="llm-versioned")

    before = client.get("/api/agent/config", headers={"Authorization": f"Bearer {key}"}).json()

    r1 = client.post(
        f"/api/admin/llm/{service.slug}/toggle", json={"enabled": False, "reason": "cost spike"}
    )
    assert r1.status_code == 200, r1.text
    v1 = r1.json()["config_version"]
    assert v1 > before["config_version"]

    r2 = client.post(
        f"/api/admin/llm/{service.slug}/toggle", json={"enabled": True, "reason": "resolved"}
    )
    v2 = r2.json()["config_version"]
    assert v2 > v1


def test_llm_toggle_off_then_agent_config_reports_disabled(db, client, make_user, make_service, sign_in):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    service, _roles, key = _service_with_key(db, make_service, slug="killswitch")

    toggled = client.post(
        f"/api/admin/llm/{service.slug}/toggle", json={"enabled": False, "reason": "test"}
    )
    assert toggled.status_code == 200

    r = client.get("/api/agent/config", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    assert r.json()["llm_enabled"] is False


# ── heartbeat: never a key, usage accumulates ────────────────────────────────────────
def test_heartbeat_rejects_key_shaped_field_without_storing(db, client, make_service):
    service, _roles, key = _service_with_key(db, make_service, slug="heartbeat-svc")
    body = {
        "version": "1.0.0",
        "llm": {
            "provider": "anthropic",
            "model": "claude-opus-5",
            "key_present": True,
            "api_key": "sk-should-never-be-sent",
        },
    }

    r = client.post("/api/agent/heartbeat", json=body, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text

    reg = db.scalar(
        select(models.LlmRegistration).where(models.LlmRegistration.service_id == service.id)
    )
    assert reg.provider == "anthropic"
    assert reg.model == "claude-opus-5"
    assert reg.key_present is True

    stored = json.dumps(
        {"provider": reg.provider, "model": reg.model, "key_present": reg.key_present}
    )
    assert "sk-should-never-be-sent" not in stored

    rejected = db.scalar(
        select(models.AuditLog).where(models.AuditLog.action == "heartbeat.key_rejected")
    )
    assert rejected is not None
    assert "llm.api_key" in rejected.metadata_["fields"]


def test_heartbeat_without_llm_block_shows_as_unreported(db, client, make_service):
    service, _roles, key = _service_with_key(db, make_service, slug="quiet-svc")

    r = client.post("/api/agent/heartbeat", json={"version": "1.0.0"}, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text

    reg = db.scalar(
        select(models.LlmRegistration).where(models.LlmRegistration.service_id == service.id)
    )
    assert reg.provider == "unreported"


def test_heartbeat_usage_accumulates_rather_than_overwrites(db, client, make_service):
    service, _roles, key = _service_with_key(db, make_service, slug="usage-svc")
    day = date.today().isoformat()

    client.post(
        "/api/agent/heartbeat",
        json={"usage": {"day": day, "requests": 5, "input_tokens": 100, "output_tokens": 10}},
        headers={"Authorization": f"Bearer {key}"},
    )
    client.post(
        "/api/agent/heartbeat",
        json={"usage": {"day": day, "requests": 3, "input_tokens": 50, "output_tokens": 5}},
        headers={"Authorization": f"Bearer {key}"},
    )

    row = db.scalar(
        select(models.LlmUsageDaily).where(models.LlmUsageDaily.service_id == service.id)
    )
    assert row.requests == 8
    assert int(row.input_tokens) == 150
    assert int(row.output_tokens) == 15


# ── grants bulk ──────────────────────────────────────────────────────────────────────
def test_grants_bulk_creates_for_matching_band_and_skips_existing(
    db, client, make_user, make_employee, make_service, make_grant, sign_in
):
    # band L5 keeps the admin's own (default-band-L3) employee out of the L3 filter below.
    admin = make_user(is_platform_admin=True, employee=make_employee(band="L5"))
    sign_in(admin)
    service, roles = make_service(slug="bulk-target")

    already_granted = make_user(employee=make_employee(band="L3"))
    make_grant(already_granted, service, roles["viewer"])
    fresh = make_user(employee=make_employee(band="L3"))
    other_band = make_user(employee=make_employee(band="L5"))

    r = client.post(
        "/api/admin/grants/bulk", json={"slug": "bulk-target", "role": "viewer", "band": ["L3"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1  # only `fresh`; `already_granted` was skipped

    grant_user_ids = {
        g.user_id
        for g in db.scalars(select(models.Grant).where(models.Grant.service_id == service.id)).all()
    }
    assert fresh.id in grant_user_ids
    assert other_band.id not in grant_user_ids
