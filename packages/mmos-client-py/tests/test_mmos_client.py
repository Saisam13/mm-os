"""Targeted tests for the contract in docs/04-auth-flow.md and docs/05-service-integration.md.

No live MM OS: a local RSA keypair signs tokens shaped exactly like
`backend/app/security.py::mint_service_token`, and an `httpx.MockTransport` stands in for
MM OS's JWKS / revocations / heartbeat endpoints. The deny-list and heartbeat mechanics are
driven by calling `poll_once()` / `beat_once()` directly — this proves the 60-second
revocation SLA is *mechanically* correct without an actual 60-second wait.
"""
from __future__ import annotations

import base64
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from jose import jwt

from mmos_client import MMOS, CurrentUser, TokenError, llm_guard, report_usage, require_role

ISSUER = "https://os.test.local"
KID = "mmos-test-2026-08"
SLUG = "echo"


def _b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    numbers = priv.public_key().public_numbers()
    jwk = {
        "kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256",
        "n": _b64u(numbers.n), "e": _b64u(numbers.e),
    }
    return pem, pub_pem, jwk


def mint(pem, *, aud=SLUG, sub="user:1", roles=None, iat_delta=0, exp_delta=900,
          kid=KID, alg="RS256", extra=None):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "sub": sub, "aud": aud, "jti": f"jti-{now}-{sub}-{aud}",
        "iat": now + iat_delta, "exp": now + exp_delta,
        "emp": "MM32", "email": "demo@m-mines.com", "name": "Demo User",
        "dept": "Purchase", "division": "Finance", "band": "L1S",
        "approval_level": "L1 (Associate)", "roles": roles or ["viewer"],
        "platform_admin": False,
    }
    if extra:
        claims.update(extra)
    return jwt.encode(claims, pem, algorithm=alg, headers={"kid": kid})


class StubMMOS:
    """A local stand-in for MM OS's public surface, wired in via httpx.MockTransport."""

    def __init__(self, jwk):
        self.jwk = jwk
        self.revoked_subs: list[dict] = []
        self.llm_enabled = True
        self.unreachable = False
        self.jwks_calls = 0
        self.revocations_calls = 0
        self.heartbeat_calls = 0
        self.last_heartbeat_body: dict | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("stub: MM OS is down")
        path = request.url.path
        if path == "/.well-known/jwks.json":
            self.jwks_calls += 1
            return httpx.Response(200, json={"keys": [self.jwk]})
        if path == "/api/agent/revocations":
            self.revocations_calls += 1
            return httpx.Response(200, json={
                "now": "2026-08-24T00:00:00Z",
                "poll_after_seconds": 60,
                "revoked_subjects": list(self.revoked_subs),
                "revoked_jti": [],
            })
        if path == "/api/agent/heartbeat":
            self.heartbeat_calls += 1
            self.last_heartbeat_body = json.loads(request.content or b"{}")
            return httpx.Response(200, json={"llm_enabled": self.llm_enabled, "config_version": 7})
        return httpx.Response(404)


@pytest.fixture
def stub(keypair):
    _, _, jwk = keypair
    return StubMMOS(jwk)


def make_mmos(stub, **kwargs) -> MMOS:
    client = httpx.Client(base_url=ISSUER, transport=httpx.MockTransport(stub.handler))
    defaults = dict(
        slug=SLUG, os_url=ISSUER, issuer=ISSUER, service_key="mmk_test",
        public_paths=["/", "/api/public"], http_client=client,
    )
    defaults.update(kwargs)
    return MMOS(**defaults)


# ── the six required rejections, plus the escape hatch ──────────────────────

def test_valid_token_is_accepted(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    claims = mmos._verify(mint(pem))
    assert claims["sub"] == "user:1"
    assert claims["aud"] == SLUG


def test_wrong_audience_is_rejected(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem, aud="some-other-service")
    with pytest.raises(TokenError) as exc:
        mmos._verify(token)
    assert exc.value.reason == "bad_audience"


def test_expired_token_is_rejected(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem, iat_delta=-1000, exp_delta=-100)  # expired well past the 60s skew
    with pytest.raises(TokenError) as exc:
        mmos._verify(token)
    assert exc.value.reason == "expired"


def test_tampered_signature_is_rejected(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem)
    head, payload, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    with pytest.raises(TokenError) as exc:
        mmos._verify(f"{head}.{payload}.{flipped}")
    assert exc.value.reason == "bad_signature"


def _mint_hs256_confusion(pub_pem: str, *, aud=SLUG, sub="user:1") -> str:
    """Hand-builds a token whose header claims HS256, signed with the RSA *public* key
    as the HMAC secret — the classic alg-confusion attack (a real attacker would not go
    through python-jose to build this, since jose itself refuses to sign with a
    PEM-shaped HMAC secret; that refusal is exactly why this is built by hand)."""
    import hashlib
    import hmac as hmac_mod

    now = int(time.time())
    header = {"alg": "HS256", "kid": KID, "typ": "JWT"}
    claims = {
        "iss": ISSUER, "sub": sub, "aud": aud, "jti": f"jti-confusion-{now}",
        "iat": now, "exp": now + 900, "emp": "MM32", "email": "demo@m-mines.com",
        "name": "Demo User", "dept": "Purchase", "division": "Finance", "band": "L1S",
        "approval_level": "L1 (Associate)", "roles": ["admin"], "platform_admin": False,
    }

    def b64u_json(obj: dict) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=")

    h, p = b64u_json(header), b64u_json(claims)
    sig = hmac_mod.new(pub_pem.encode(), h + b"." + p, hashlib.sha256).digest()
    s = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return (h + b"." + p + b"." + s).decode()


def test_alg_confusion_is_rejected(keypair, stub):
    _, pub_pem, _ = keypair
    mmos = make_mmos(stub)
    token = _mint_hs256_confusion(pub_pem)
    with pytest.raises(TokenError) as exc:
        mmos._verify(token)
    assert exc.value.reason == "alg_not_allowed"


def test_revoked_subject_is_rejected(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem, sub="user:revoke-me")
    assert mmos._verify(token)["sub"] == "user:revoke-me"  # good before revocation

    stub.revoked_subs.append({"sub": "user:revoke-me", "reason": "grant_removed", "at": "now"})
    assert mmos.poller.poll_once() is True  # the poll a service does every 60s

    with pytest.raises(TokenError) as exc:
        mmos._verify(token)
    assert exc.value.reason == "revoked"


def test_revocation_blocks_within_a_single_poll(keypair, stub):
    """The acceptance test that matters most: a removed grant must block within one
    poll cycle, driven here without a 60-second wall-clock wait."""
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem, sub="user:sla-check")

    mmos._verify(token)  # fine beforehand
    stub.revoked_subs.append({"sub": "user:sla-check", "reason": "grant_removed", "at": "now"})
    mmos.poller.poll_once()  # exactly what the background thread would have done

    with pytest.raises(TokenError):
        mmos._verify(token)


# ── availability: MM OS down must degrade, never fail closed ────────────────

def test_mm_os_unreachable_keeps_serving_already_verifiable_tokens(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    token = mint(pem, sub="user:offline-ok")

    mmos._verify(token)  # populates the JWKS cache while MM OS is "up"
    assert stub.jwks_calls == 1

    stub.unreachable = True
    # Signature verification still succeeds off the cached key — no new network call needed.
    claims = mmos._verify(token)
    assert claims["sub"] == "user:offline-ok"

    # Polling and heartbeating report failure but never raise, and never wipe state.
    assert mmos.poller.poll_once() is False
    assert mmos.heartbeat.beat_once() is False
    assert mmos.heartbeat.llm_enabled is True  # unchanged, not flipped to disabled


def test_unknown_kid_triggers_refetch_but_is_rate_limited(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)

    with pytest.raises(TokenError):
        mmos._verify(mint(pem, kid="totally-unknown-kid"))
    assert stub.jwks_calls == 1  # empty cache + unknown kid -> immediate fetch

    with pytest.raises(TokenError):
        mmos._verify(mint(pem, kid="another-unknown-kid"))
    assert stub.jwks_calls == 1  # rate-limited: no second refetch inside the same minute

    mmos._jwks._last_fetch = 0.0  # simulate the minute having elapsed (no real sleep)
    with pytest.raises(TokenError):
        mmos._verify(mint(pem, kid="yet-another-unknown-kid"))
    assert stub.jwks_calls == 2  # allowed again once the rate-limit window passes


# ── LLM control plane ─────────────────────────────────────────────────────

def test_llm_guard_open_by_default_then_closes_after_heartbeat(stub):
    mmos = make_mmos(stub)
    llm_guard()  # no exception: assumed enabled until told otherwise (see handoff)

    stub.llm_enabled = False
    assert mmos.heartbeat.beat_once() is True
    with pytest.raises(HTTPException) as exc:
        llm_guard()
    assert exc.value.status_code == 503
    assert exc.value.detail == {"error": "llm_disabled"}


def test_report_usage_accumulates_and_ships_then_clears(stub):
    mmos = make_mmos(stub)
    report_usage(requests=2, input_tokens=100, output_tokens=40)
    report_usage(requests=1, input_tokens=10, output_tokens=5)

    assert mmos.heartbeat.beat_once() is True
    sent = stub.last_heartbeat_body["usage"]
    assert sent["requests"] == 3
    assert sent["input_tokens"] == 110
    assert sent["output_tokens"] == 45

    # A failed heartbeat must not have cleared usage; a successful one does.
    assert mmos._usage.snapshot()["requests"] == 0


# ── FastAPI wiring: require_role, the allowlist, the accept/session flow ────

def _build_app(mmos: MMOS) -> FastAPI:
    app = FastAPI()
    mmos.install(app, start_background=False)

    @app.get("/api/public/ping")
    def ping():
        return {"pong": True}

    @app.get("/api/whoami")
    def whoami(user: CurrentUser = Depends(mmos.user)):
        return {"sub": user.sub, "roles": user.roles}

    @app.get("/api/private-forgotten")
    def forgotten():
        # Deliberately no Depends() — proves the allowlist middleware fails closed.
        return {"reached": True}

    @app.post("/api/admin/write")
    def write(user: CurrentUser = Depends(require_role("admin"))):
        return {"ok": True}

    return app


def test_require_role_403_shape(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    app = _build_app(mmos)
    client = TestClient(app)

    token = mint(pem, roles=["viewer"])
    resp = client.post("/api/admin/write", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json() == {"error": "role_required", "need": "admin", "have": ["viewer"]}

    admin_token = mint(pem, roles=["admin"])
    resp = client.post("/api/admin/write", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


def test_public_paths_allowlist_fails_closed(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    app = _build_app(mmos)
    client = TestClient(app)

    assert client.get("/api/public/ping").status_code == 200  # allowlisted, no token needed

    # Not allowlisted and no Depends() at all — the forgotten route must still 401.
    resp = client.get("/api/private-forgotten")
    assert resp.status_code == 401

    token = mint(pem)
    resp = client.get("/api/private-forgotten", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_accept_and_session_cookie_flow(keypair, stub):
    pem, _, _ = keypair
    mmos = make_mmos(stub)
    app = _build_app(mmos)
    # https scheme: the cookie is Set-Cookie'd with Secure, exactly as it is against a real
    # MM OS deployment, so the client jar must see an https request to send it back.
    client = TestClient(app, base_url="https://testserver")

    accept = client.get("/_mmos/accept")
    assert accept.status_code == 200
    assert "/_mmos/session" in accept.text  # the fragment-reading script posts here

    token = mint(pem, sub="user:cookie-flow")
    resp = client.post("/_mmos/session", json={"token": token})
    assert resp.status_code == 200
    assert mmos.cookie_name in resp.cookies

    # The cookie alone (no Authorization header) now authenticates the service's own routes.
    who = client.get("/api/whoami")
    assert who.status_code == 200
    assert who.json()["sub"] == "user:cookie-flow"

    # A bad token must not get a cookie at all.
    bad = client.post("/_mmos/session", json={"token": "garbage"})
    assert bad.status_code == 401


def test_health_endpoint(stub):
    mmos = make_mmos(stub, version="9.9.9")
    app = _build_app(mmos)
    client = TestClient(app)
    resp = client.get("/_mmos/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "slug": SLUG, "version": "9.9.9"}
