"""The auth verification seam over `packages/mmos-client-py` — copied faithfully from
servicedesk/app/mmos_seam.py (the reference implementation for this pattern across MM OS
services). See docs/05-service-integration.md for the intended shape:

    from mmos_client import MMOS, require_role, CurrentUser
    mmos = MMOS(slug=..., os_url=..., service_key=..., public_paths=[...])
    mmos.install(app)                 # /_mmos/accept, /_mmos/health, deny-list poller, heartbeat

This module is a same-shaped local stand-in: `CurrentUser`, `require_role(role)`, and
`get_current_user` behave like the documented ones, verifying the same claim set
(docs/03-api-contract.md's token claims) so swapping in the real package later is a router
import change, not a rewrite.

Two verification modes, switched by `Settings.auth_mode`:

- `"http"`  — production. Verifies a real RS256 token against MM OS's published JWKS,
  exactly per docs/04-auth-flow.md's ordered checklist.
- `"stub"`  — what every test in this repo runs against. A token is
  `base64url(json_claims).hex_hmac_sha256(claims, dev_secret)`, verified the same way. Not a
  real JWT; good enough to prove the seam, the role guard, and the deny-list mechanics.
  Local dev/tests only — see app/main.py's boot guard, which refuses to start in "stub"
  mode when environment=production.

Password Manager holds no secrets of any kind yet (see SECURITY.md) — this seam only ever
answers "who is this MM OS user", nothing more.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field

import httpx
from fastapi import Depends, HTTPException, Request

from .config import settings

# The cookie every service-local session lives in. A4's convention (`{slug}_mmos_at`) --
# matches `packages/mmos-client-py/mmos_client/core.py`'s default `cookie_name`, so "stub"
# and "http" mode use the same cookie and nothing in the browser needs to know which mode
# the server is running in.
COOKIE_NAME = f"{settings().mmos_service_slug}_mmos_at"

_real_mmos = None  # lazily constructed; only touches the network in "http" mode


def get_real_mmos():
    """The shared `mmos_client.core.MMOS` instance for `auth_mode="http"` -- built once per
    process. Never constructed by any test in this repo (every test runs `auth_mode="stub"`,
    which never calls this), so it never opens a socket during `pytest`."""
    global _real_mmos
    if _real_mmos is None:
        from mmos_client.core import MMOS  # packages/mmos-client-py -- first-party, not external

        cfg = settings()
        _real_mmos = MMOS(
            slug=cfg.mmos_service_slug,
            os_url=cfg.mmos_os_url,
            service_key=cfg.mmos_service_key,
            issuer=cfg.mmos_issuer,
            version=cfg.version,
            cookie_name=COOKIE_NAME,
        )
    return _real_mmos


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    employee_code: str
    name: str
    email: str | None
    department: str
    division: str
    band: str
    approval_level: str | None
    roles: list[str] = field(default_factory=list)
    platform_admin: bool = False


class AuthError(HTTPException):
    def __init__(self, reason: str):
        super().__init__(status_code=401, detail={"error": reason})


# ── the deny-list (docs/04-auth-flow.md "Revocation, end to end") ──────────
# A real poller (GET /api/revocations every ~60s) is B1/assembly's wiring once MM OS is
# live; this is the in-memory set the client library merges into, and what verify_token
# checks.
_revoked_subs: set[str] = set()
_revoked_jti: set[str] = set()


def revoke_subject(sub: str) -> None:
    _revoked_subs.add(sub)


def revoke_jti(jti: str) -> None:
    _revoked_jti.add(jti)


def clear_revocations() -> None:
    """Test seam."""
    _revoked_subs.clear()
    _revoked_jti.clear()


def poll_revocations_once(os_url: str, service_key: str, since: str | None = None) -> None:  # pragma: no cover
    """Best-effort single poll of GET /api/revocations. Not exercised by any test — there is
    no live MM OS to poll in this sandbox. Wired for when there is one."""
    try:
        resp = httpx.get(
            f"{os_url.rstrip('/')}/api/revocations",
            params={"since": since} if since else None,
            headers={"Authorization": f"Bearer {service_key}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        for row in data.get("revoked_subjects", []):
            _revoked_subs.add(row["sub"])
        for jti in data.get("revoked_jti", []):
            _revoked_jti.add(jti)
    except Exception:
        pass  # availability beats freshness — docs/04-auth-flow.md


# ── stub token codec (test/dev only) ────────────────────────────────────
def make_dev_token(claims: dict, dev_secret: str | None = None, ttl_seconds: int = 900) -> str:
    dev_secret = dev_secret or settings().dev_secret
    payload = dict(claims)
    payload.setdefault("iat", int(time.time()))
    payload.setdefault("exp", int(time.time()) + ttl_seconds)
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(dev_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _decode_dev_token(token: str, dev_secret: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise AuthError("malformed_token")
    expected = hmac.new(dev_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise AuthError("bad_signature")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode()))
    except Exception:
        raise AuthError("malformed_token")
    if payload.get("exp", 0) < time.time():
        raise AuthError("expired")
    return payload


def _decode_http_token(token: str) -> dict:  # pragma: no cover
    """Real RS256/JWKS verification plus the live deny-list, via `packages/mmos-client-py`
    -- the shared client every other service uses. Not exercised by any test — no live MM
    OS instance to mint a real token against in this sandbox; `get_real_mmos()` is only
    ever called when `auth_mode == "http"`."""
    from mmos_client._verify import TokenError

    try:
        return get_real_mmos()._verify(token)
    except TokenError as exc:
        raise AuthError(exc.reason)


def _claims_to_user(payload: dict) -> CurrentUser:
    if payload.get("sub") in _revoked_subs or payload.get("jti") in _revoked_jti:
        raise AuthError("revoked")
    return CurrentUser(
        sub=payload["sub"],
        employee_code=payload.get("emp", ""),
        name=payload.get("name", ""),
        email=payload.get("email"),
        department=payload.get("dept", ""),
        division=payload.get("division", ""),
        band=payload.get("band", ""),
        approval_level=payload.get("approval_level"),
        roles=list(payload.get("roles", [])),
        platform_admin=bool(payload.get("platform_admin", False)),
    )


def verify_token(token: str) -> CurrentUser:
    cfg = settings()
    if cfg.auth_mode == "http":
        payload = _decode_http_token(token)
    else:
        payload = _decode_dev_token(token, cfg.dev_secret)
    return _claims_to_user(payload)


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie
    raise AuthError("missing_token")


def get_current_user(request: Request) -> CurrentUser:
    token = _extract_token(request)
    return verify_token(token)


def require_role(role: str):
    """No `platform_admin` bypass -- matches `mmos_client.core.require_role` and
    servicedesk/app/mmos_seam.py exactly. A service's roles are its own vocabulary; MM OS's
    platform_admin flag does not carry into it."""

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if role not in user.roles:
            raise HTTPException(
                status_code=403,
                detail={"error": "role_required", "need": role, "have": user.roles},
            )
        return user
    return _dep
