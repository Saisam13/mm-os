"""Owned by A2 — Tokens and Control Plane.

Written first, per the brief: this is the module where a subtle bug is a silent security
hole rather than a visible failure. Every test here exercises `app/security.py` (frozen)
the way a real service's client library would, using only what `/.well-known/jwks.json`
publishes — never reaching into MM OS internals to cheat.

`verify_as_service` below is the reference verifier: it implements the exact order from
docs/04-auth-flow.md ("Verification, in the exact order the client library does it").
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from jose import jwt
from jose.exceptions import JWTError

from app import security
from app.config import settings


def verify_as_service(
    token: str,
    *,
    aud: str,
    jwks_doc: dict,
    issuer: str,
    denylist_subjects: frozenset = frozenset(),
    denylist_jtis: frozenset = frozenset(),
) -> dict:
    """What a service's client library does before trusting a token.

    Steps mirror docs/04-auth-flow.md exactly: resolve `kid` against cached JWKS, verify
    the RS256 signature, check `iss`/`aud`/`exp`, then consult the deny-list. Pinning
    `algorithms=["RS256"]` is what defeats the alg=none / HS256 confusion attack — a
    verifier that instead trusted whatever `alg` the token claimed would not.
    """
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    key = next((k for k in jwks_doc["keys"] if k.get("kid") == kid), None)
    if key is None:
        raise JWTError(f"unknown kid: {kid!r}")

    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=aud,
        issuer=issuer,
        options={"require_iat": True, "require_exp": True},
    )

    if claims.get("sub") in denylist_subjects:
        raise JWTError("subject is on the deny-list")
    if claims.get("jti") in denylist_jtis:
        raise JWTError("jti is on the deny-list")
    return claims


def _mint(make_employee, make_user, slug="itemcode", roles=("viewer",)):
    employee = make_employee()
    user = make_user(employee=employee)
    token, jti, ttl = security.mint_service_token(
        user=user, employee=employee, service_slug=slug, roles=list(roles)
    )
    return token, jti, user, employee


def _b64u_json(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def _forge_hs256(header: dict, payload: dict, secret: bytes) -> str:
    """Hand-rolled HS256 signing, bypassing python-jose's own guard against using an
    asymmetric key as an HMAC secret — a real attacker would not go through that guard
    either. This is what a verifier's `algorithms=["RS256"]` pin has to defend against."""
    h = _b64u_json(header)
    p = _b64u_json(payload)
    sig = hmac.new(secret, f"{h}.{p}".encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{h}.{p}.{sig_b64}"


def _public_pem_from_jwks(jwks_doc: dict) -> bytes:
    """Rebuild the RSA public key from the JWK — exactly what an attacker can also do,
    since /.well-known/jwks.json is public by design."""

    def _b64u_decode(s: str) -> bytes:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad)

    key = jwks_doc["keys"][0]
    n = int.from_bytes(_b64u_decode(key["n"]), "big")
    e = int.from_bytes(_b64u_decode(key["e"]), "big")
    public_key = RSAPublicNumbers(e, n).public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


# ── acceptance: a token minted for one service is worthless at another ───────────────
def test_token_minted_for_itemcode_fails_verification_as_att(make_employee, make_user):
    token, *_ = _mint(make_employee, make_user, slug="itemcode")
    jwks_doc = security.jwks()

    with pytest.raises(JWTError):
        verify_as_service(token, aud="att", jwks_doc=jwks_doc, issuer=settings().issuer)

    # and it is perfectly valid for the service it was actually minted for
    claims = verify_as_service(token, aud="itemcode", jwks_doc=jwks_doc, issuer=settings().issuer)
    assert claims["aud"] == "itemcode"


def test_expired_token_rejected(make_employee, make_user, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "service_token_ttl_seconds", -10)
    token, *_ = _mint(make_employee, make_user)
    jwks_doc = security.jwks()

    with pytest.raises(JWTError):
        verify_as_service(token, aud="itemcode", jwks_doc=jwks_doc, issuer=cfg.issuer)


def test_tampered_signature_rejected(make_employee, make_user):
    token, *_ = _mint(make_employee, make_user)
    head, payload, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    tampered = f"{head}.{payload}.{flipped}"
    jwks_doc = security.jwks()

    with pytest.raises(JWTError):
        verify_as_service(tampered, aud="itemcode", jwks_doc=jwks_doc, issuer=settings().issuer)


def test_unknown_kid_rejected(make_employee, make_user):
    """A client library must refuse a `kid` it does not have cached, before it ever
    attempts a signature check — otherwise an attacker just needs any RSA key."""
    token, *_ = _mint(make_employee, make_user)
    claims = jwt.get_unverified_claims(token)

    throwaway = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    throwaway_pem = throwaway.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    forged = jwt.encode(claims, throwaway_pem, algorithm="RS256", headers={"kid": "unknown-2099"})

    jwks_doc = security.jwks()
    with pytest.raises(JWTError):
        verify_as_service(forged, aud=claims["aud"], jwks_doc=jwks_doc, issuer=settings().issuer)


def test_alg_none_rejected(make_employee, make_user):
    """The classic `alg: none` attack: an attacker strips the signature entirely and
    claims the token needs none. Hand-built so the test does not depend on whether the
    JWT library even lets you *encode* with alg=none."""
    token, *_ = _mint(make_employee, make_user)
    claims = jwt.get_unverified_claims(token)
    header = jwt.get_unverified_header(token)

    none_token = f"{_b64u_json({'alg': 'none', 'typ': 'JWT', 'kid': header['kid']})}.{_b64u_json(claims)}."

    jwks_doc = security.jwks()
    with pytest.raises(JWTError):
        verify_as_service(none_token, aud=claims["aud"], jwks_doc=jwks_doc, issuer=settings().issuer)


def test_hs256_confusion_rejected(make_employee, make_user):
    """The classic RS256->HS256 confusion attack: sign with the *public* key bytes as an
    HMAC secret. A verifier that pins `algorithms=["RS256"]` refuses this outright; one
    that trusts the token's own `alg` header would be fooled."""
    token, *_ = _mint(make_employee, make_user)
    claims = jwt.get_unverified_claims(token)
    header = jwt.get_unverified_header(token)
    jwks_doc = security.jwks()

    public_pem = _public_pem_from_jwks(jwks_doc)
    forged = _forge_hs256({"alg": "HS256", "typ": "JWT", "kid": header["kid"]}, claims, public_pem)

    with pytest.raises(JWTError):
        verify_as_service(forged, aud=claims["aud"], jwks_doc=jwks_doc, issuer=settings().issuer)


def test_denylisted_subject_rejected(make_employee, make_user):
    token, jti, user, employee = _mint(make_employee, make_user)
    jwks_doc = security.jwks()

    # valid until the subject lands on the deny-list
    verify_as_service(token, aud="itemcode", jwks_doc=jwks_doc, issuer=settings().issuer)
    with pytest.raises(JWTError):
        verify_as_service(
            token,
            aud="itemcode",
            jwks_doc=jwks_doc,
            issuer=settings().issuer,
            denylist_subjects=frozenset({user.subject}),
        )


def test_denylisted_jti_rejected(make_employee, make_user):
    token, jti, user, employee = _mint(make_employee, make_user)
    jwks_doc = security.jwks()

    with pytest.raises(JWTError):
        verify_as_service(
            token,
            aud="itemcode",
            jwks_doc=jwks_doc,
            issuer=settings().issuer,
            denylist_jtis=frozenset({jti}),
        )


def test_jwks_publishes_exactly_one_rsa_signing_key():
    doc = security.jwks()
    assert len(doc["keys"]) == 1
    key = doc["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["kid"] == settings().signing_key_id
