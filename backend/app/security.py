"""Keys, tokens, sessions, PINs.

This is the one module where a subtle bug is a silent security hole rather than a visible
failure, so it is small, has no framework dependencies, and its tests are written first.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from .config import settings

_ph = PasswordHasher()


# ── keys ──────────────────────────────────────────────────────────────────
def _load_or_create_key() -> rsa.RSAPrivateKey:
    path = settings().signing_key_path
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    # Dev convenience only. In production the key is mounted by Coolify as a secret file.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return key


_private_key = _load_or_create_key()
_private_pem = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()


def _b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwks() -> dict:
    """Public key set. Services fetch this once an hour and verify tokens offline."""
    numbers = _private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": settings().signing_key_id,
                "use": "sig",
                "alg": "RS256",
                "n": _b64u(numbers.n),
                "e": _b64u(numbers.e),
            }
        ]
    }


# ── service tokens ────────────────────────────────────────────────────────
def mint_service_token(*, user, employee, service_slug: str, roles: list[str]) -> tuple[str, str, int]:
    """Return (token, jti, ttl_seconds).

    `aud` is exactly one service, so a token minted for itemcode is worthless at att.
    """
    cfg = settings()
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    claims = {
        "iss": cfg.issuer,
        "sub": f"user:{user.id}",
        "aud": service_slug,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=cfg.service_token_ttl_seconds)).timestamp()),
        "emp": employee.employee_code,
        "email": employee.work_email,
        "name": employee.full_name,
        "dept": employee.hr_department,
        "division": employee.division,
        "band": employee.band,
        "approval_level": employee.approval_level,
        "roles": roles,
        "platform_admin": user.is_platform_admin,
    }
    token = jwt.encode(
        claims, _private_pem, algorithm="RS256", headers={"kid": cfg.signing_key_id}
    )
    return token, jti, cfg.service_token_ttl_seconds


# ── shell sessions ────────────────────────────────────────────────────────
def new_session_token() -> tuple[str, str]:
    """Opaque random token plus its hash.

    Deliberately not a JWT: the shell session must be revocable the instant an admin
    deactivates someone, and only a server-side lookup gives that.
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=settings().session_ttl_hours)


# ── PINs and service keys ─────────────────────────────────────────────────
def hash_pin(pin: str) -> str:
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise ValueError("PIN must be 4 to 8 digits")
    return _ph.hash(pin)


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return _ph.verify(pin_hash, pin)
    except VerifyMismatchError:
        return False


def new_service_key() -> tuple[str, str]:
    """Server-to-server key for one service. Shown once, stored only as a hash."""
    raw = "mmk_" + secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def constant_time_equal(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)
