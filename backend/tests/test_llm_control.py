"""The LLM control plane (app/llm_control.py + admin routes in routers/platform.py +
service-facing routes in routers/agent.py).

MM OS governs policy, enablement and usage for every AI feature across every service, and
NEVER holds a provider API key. These tests cover the admin surface (list/toggle/policy),
the service-facing policy fetch reflecting both the service kill switch and a per-feature
kill switch, usage metering, and the hard boundary that no key ever enters the control plane.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select

from app import models
from app.llm_control import LlmFeature, LlmFeatureUsageDaily
from app.security import new_service_key

_KEY_RE = re.compile(r"(api[_-]?key|secret|password|access[_-]?token)", re.I)


def _service_with_key(db, make_service, **kw):
    service, roles = make_service(**kw)
    raw, digest = new_service_key()
    service.service_key_hash = digest
    db.commit()
    return service, roles, raw


def _register_feature(client, key, feature_key="lead_enrichment", **spec):
    body = {"features": [{"feature_key": feature_key, "name": feature_key, **spec}]}
    r = client.post("/api/agent/llm/register", json=body, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    return r.json()


# ── admin: list, toggle, set per-feature policy ──────────────────────────────────────
def test_admin_lists_features_toggles_and_sets_policy(db, client, make_user, make_service, sign_in):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    service, _roles, key = _service_with_key(db, make_service, slug="saleshub")
    _register_feature(client, key, "lead_enrichment", provider="anthropic", model="claude-opus")

    # Admin sees the feature it declared, across the central per-service view.
    listing = client.get(f"/api/admin/llm/{service.slug}/features")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    keys = [f["feature_key"] for f in body["features"]]
    assert "lead_enrichment" in keys

    # Set a provider/model allowlist policy on the feature.
    pol = client.post(
        f"/api/admin/llm/{service.slug}/features/lead_enrichment/policy",
        json={"allowed_providers": ["anthropic"], "allowed_models": ["claude-opus"]},
    )
    assert pol.status_code == 200, pol.text
    assert pol.json()["allowed_providers"] == ["anthropic"]

    # The all-services view also carries it.
    all_feats = client.get("/api/admin/llm/features").json()["features"]
    assert any(f["feature_key"] == "lead_enrichment" and f["slug"] == service.slug for f in all_feats)


def test_service_policy_reflects_service_toggle_and_feature_kill_switch(
    db, client, make_user, make_service, sign_in
):
    admin = make_user(is_platform_admin=True)
    sign_in(admin)
    service, _roles, key = _service_with_key(db, make_service, slug="matcher")
    _register_feature(client, key, "code_match")

    def policy():
        r = client.get("/api/agent/llm/policy", headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200, r.text
        return r.json()

    # Baseline: service on, feature on -> effective on.
    p = policy()
    assert p["llm_enabled"] is True
    assert p["features"][0]["enabled"] is True

    # Service-level kill switch turns the whole thing off for the service.
    off = client.post(f"/api/admin/llm/{service.slug}/toggle", json={"enabled": False, "reason": "cost"})
    assert off.status_code == 200
    p = policy()
    assert p["llm_enabled"] is False
    assert p["features"][0]["enabled"] is False  # effective = service AND feature

    # Re-enable the service, but kill just the one feature: effective enablement is the AND.
    client.post(f"/api/admin/llm/{service.slug}/toggle", json={"enabled": True})
    client.post(
        f"/api/admin/llm/{service.slug}/features/code_match/toggle",
        json={"enabled": False, "reason": "bad output"},
    )
    p = policy()
    assert p["llm_enabled"] is True
    assert p["features"][0]["feature_enabled"] is False
    assert p["features"][0]["enabled"] is False


def test_usage_reporting_increments_the_daily_counter(db, client, make_service):
    service, _roles, key = _service_with_key(db, make_service, slug="usage-feat-svc")
    day = date.today().isoformat()

    for reqs, in_tok, out_tok in ((2, 100, 10), (3, 50, 5)):
        r = client.post(
            "/api/agent/llm/usage",
            json={
                "feature_key": "summarize",
                "requests": reqs,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "day": day,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert r.status_code == 200, r.text

    feature = db.scalar(
        select(LlmFeature).where(
            LlmFeature.service_id == service.id, LlmFeature.feature_key == "summarize"
        )
    )
    row = db.scalar(
        select(LlmFeatureUsageDaily).where(LlmFeatureUsageDaily.feature_id == feature.id)
    )
    assert row.requests == 5  # accumulated, not overwritten
    assert int(row.input_tokens) == 150
    assert int(row.output_tokens) == 15


# ── the boundary: provider API keys NEVER enter MM OS ────────────────────────────────
def test_control_plane_models_carry_no_key_field():
    """MM OS holds policy/usage, never a secret. None of the LLM tables may have a column that
    stores a provider API key (only `key_present`, a boolean signal, is allowed)."""
    for model in (LlmFeature, LlmFeatureUsageDaily, models.LlmRegistration, models.LlmUsageDaily):
        for col in model.__table__.columns:
            if col.name == "key_present":
                continue  # a boolean flag, not a secret
            assert not _KEY_RE.search(col.name), f"{model.__name__}.{col.name} looks like a secret field"


def test_service_facing_endpoints_strip_key_shaped_fields(db, client, make_service):
    service, _roles, key = _service_with_key(db, make_service, slug="nokey-svc")

    # A service that mistakenly sends an api_key on register/usage must have it dropped, never
    # stored, and the drop is audited.
    client.post(
        "/api/agent/llm/register",
        json={"features": [{"feature_key": "enrich", "provider": "anthropic", "api_key": "sk-leak"}]},
        headers={"Authorization": f"Bearer {key}"},
    )
    client.post(
        "/api/agent/llm/usage",
        json={"feature_key": "enrich", "requests": 1, "secret": "sk-also-leak"},
        headers={"Authorization": f"Bearer {key}"},
    )

    feature = db.scalar(
        select(LlmFeature).where(
            LlmFeature.service_id == service.id, LlmFeature.feature_key == "enrich"
        )
    )
    assert feature is not None
    # Nothing on the row (or any of its string columns) holds the leaked secret.
    stored = " ".join(str(getattr(feature, c.name)) for c in feature.__table__.columns)
    assert "sk-leak" not in stored and "sk-also-leak" not in stored

    rejected = db.scalars(
        select(models.AuditLog).where(models.AuditLog.action == "heartbeat.key_rejected")
    ).all()
    dropped_fields = {f for r in rejected for f in (r.metadata_ or {}).get("fields", [])}
    assert any("api_key" in f for f in dropped_fields)
    assert any("secret" in f for f in dropped_fields)
