"""A minimal stand-in for MM OS's public surface — JWKS, revocations, heartbeat — used only
by the echo-service demo so it can run standalone with no other MM OS process required.

Not a security review target: it exists purely so `examples/echo-service` proves the
mmos-client-py contract end to end with one command. See README.md.
"""
from __future__ import annotations

import base64
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from jose import jwt

ISSUER = "https://stub-mmos.local"
KID = "stub-mmos-2026-08"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


def _b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwks() -> dict:
    numbers = _private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256",
                "n": _b64u(numbers.n), "e": _b64u(numbers.e),
            }
        ]
    }


def mint(
    *,
    slug: str,
    sub: str = "user:demo-1",
    roles: list[str] | None = None,
    ttl: int = 900,
    emp: str = "MM32",
    email: str = "demo@m-mines.com",
    name: str = "Demo User",
) -> str:
    """Mints a token with exactly the claim shape `backend/app/security.py::mint_service_token`
    produces (see docs/03-api-contract.md)."""
    now = int(time.time())
    claims = {
        "iss": ISSUER, "sub": sub, "aud": slug, "jti": f"jti-{now}-{sub}",
        "iat": now, "exp": now + ttl,
        "emp": emp, "email": email, "name": name,
        "dept": "Purchase", "division": "Finance", "band": "L1S",
        "approval_level": "L1 (Associate)",
        "roles": roles or ["viewer"], "platform_admin": False,
    }
    return jwt.encode(claims, _private_pem, algorithm="RS256", headers={"kid": KID})


REVOKED_SUBS: list[dict] = []
_LLM_ENABLED = {"value": True}
LAST_HEARTBEAT: dict | None = None

app = FastAPI(title="stub-mmos", docs_url=None, redoc_url=None)


@app.get("/.well-known/jwks.json")
def _jwks():
    return jwks()


@app.get("/api/agent/revocations")
def _revocations(since: str = ""):
    return {
        "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "poll_after_seconds": 60,
        "revoked_subjects": REVOKED_SUBS,
        "revoked_jti": [],
    }


@app.post("/api/agent/heartbeat")
async def _heartbeat(request: Request):
    global LAST_HEARTBEAT
    LAST_HEARTBEAT = await request.json()
    return {"llm_enabled": _LLM_ENABLED["value"], "config_version": 1}


# ── demo-only control surface: an admin acting on MM OS, faked locally ──────────────────
@app.post("/_demo/revoke")
def _demo_revoke(sub: str):
    REVOKED_SUBS.append(
        {"sub": sub, "reason": "grant_removed", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    )
    return {"ok": True, "revoked_subjects": REVOKED_SUBS}


@app.post("/_demo/llm")
def _demo_llm(enabled: bool):
    _LLM_ENABLED["value"] = enabled
    return {"ok": True, "llm_enabled": enabled}


@app.get("/_demo/mint")
def _demo_mint(roles: str = "viewer", sub: str = "user:demo-1"):
    token = mint(slug="echo", roles=[r.strip() for r in roles.split(",") if r.strip()], sub=sub)
    return {"token": token, "accept_fragment": f"/_mmos/accept#token={token}"}
