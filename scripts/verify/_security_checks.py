"""Standalone mechanical security assertions for scripts/verify/verify-security.sh (B3
hardening). Not a pytest suite and not owned by A1/A2 (backend/tests/*.py) -- this is a
separate, B3-owned script under scripts/verify/**, run directly with the shared venv's
python.

Runs against a scratch SQLite database using the same JSONB/UTC-datetime bridge
backend/tests/conftest.py (orchestrator-owned) already applies for the real suite --
imported only for its compiler shims, exactly the pattern scripts/verify/_seed_dry_run.py
already established. Provable on a machine with no Docker and no Postgres.

Each check prints exactly one line:
    PASS  <label>
    FAIL  <label> -- <why>
    WARN  <label> -- <why>

FAIL means a security property this script can mechanically prove has regressed --
the script exits non-zero if any check FAILs. WARN documents something that is true and
already written up as a finding in docs/11-security-review.md (a frozen-file gap, or an
accepted trust boundary) -- it is not a new regression and does not fail the run.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

_scratch = Path(tempfile.gettempdir()) / f"mmos-security-check-{uuid.uuid4().hex[:8]}.db"
_key = Path(tempfile.gettempdir()) / f"mmos-security-check-{uuid.uuid4().hex[:8]}.pem"
os.environ["MMOS_DATABASE_URL"] = f"sqlite+pysqlite:///{_scratch.as_posix()}"
os.environ["MMOS_SIGNING_KEY_PATH"] = str(_key)
os.environ.setdefault("MMOS_ENVIRONMENT", "test")
os.environ.setdefault("MMOS_NETWORK_MODE", "public")  # the app-under-test's own gate is off;
                                                        # the gate logic itself is exercised
                                                        # directly, in isolation, below
os.environ.setdefault("MMOS_COOKIE_SECURE", "true")    # production default -- checked below
os.environ.setdefault("MMOS_COOKIE_DOMAIN", ".m-mines.com")
os.environ.setdefault("MMOS_GOOGLE_CLIENT_ID", "verify-security")
os.environ.setdefault("MMOS_GOOGLE_CLIENT_SECRET", "verify-security")

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))
import conftest  # noqa: E402,F401 -- orchestrator-owned; imported only for its SQLite shims,
                  # exactly as scripts/verify/_seed_dry_run.py already does. No test or
                  # fixture from it is run.

from fastapi.testclient import TestClient  # noqa: E402
from jose import jwt as _jose_jwt  # noqa: E402

from app import models  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_pin, jwks, mint_service_token, new_service_key  # noqa: E402

models.Base.metadata.create_all(engine)

_FAILED = False


def check(label: str, ok: bool, detail: str = "") -> None:
    global _FAILED
    if ok:
        print(f"PASS  {label}")
    else:
        _FAILED = True
        print(f"FAIL  {label} -- {detail}")


def warn(label: str, detail: str) -> None:
    print(f"WARN  {label} -- {detail}")


db = SessionLocal()


def make_employee(**kw) -> models.Employee:
    n = uuid.uuid4().hex[:6]
    emp = models.Employee(
        employee_code=kw.pop("employee_code", f"MM{n[:4]}"),
        full_name=kw.pop("full_name", "Security Check Person"),
        work_email=kw.pop("work_email", f"secchk-{n}@m-mines.com"),
        hr_department=kw.pop("hr_department", "Information Technology"),
        division=kw.pop("division", "Corporate"),
        job_title=kw.pop("job_title", "Engineer"),
        band=kw.pop("band", "L3"),
        **kw,
    )
    db.add(emp)
    db.commit()
    return emp


def make_user(employee=None, **kw) -> models.User:
    employee = employee or make_employee()
    auth_type = kw.pop("auth_type", "google")
    if auth_type == "google":
        kw.setdefault("login_email", employee.work_email)
    else:
        kw.setdefault("pin_hash", hash_pin(kw.pop("pin", "1234")))
    user = models.User(employee_id=employee.id, auth_type=auth_type, **kw)
    db.add(user)
    db.commit()
    return user


def sign_in(client: TestClient, user: models.User) -> None:
    from app.security import new_session_token, session_expiry

    raw, token_hash = new_session_token()
    db.add(models.Session(user_id=user.id, token_hash=token_hash, expires_at=session_expiry()))
    db.commit()
    from app.config import settings

    client.cookies.set(settings().cookie_name, raw)


app.dependency_overrides.clear()
from app.db import get_db  # noqa: E402

app.dependency_overrides[get_db] = lambda: db

print("== MM OS mechanical security assertions (B3) ==\n")

# ── 1. Admin surface refuses a non-admin, in both directions ────────────────────────────
with TestClient(app) as client:
    r = client.get("/api/admin/services")
    check("GET /api/admin/services with no session -> 401", r.status_code == 401, f"got {r.status_code}")

    non_admin = make_user(auth_type="google", is_platform_admin=False)
    sign_in(client, non_admin)
    r = client.get("/api/admin/services")
    check(
        "GET /api/admin/services signed in as a non-admin -> 403",
        r.status_code == 403,
        f"got {r.status_code}: {r.text}",
    )
    client.cookies.clear()

# ── 2. A placeholder pin_hash (every seeded user, per app/seed.py) cannot authenticate ──
with TestClient(app) as client:
    placeholder_user = make_user(auth_type="local_pin", pin=f"{uuid.uuid4().int % 1_000_000:06d}")
    # pin_set_at is left NULL -- the real "no PIN issued" signal (see app/seed.py, and
    # handoff/a1-identity.md ## Contract objections #1). The value above is never revealed
    # to this check on purpose: we only try guesses a real attacker could think of.
    code = db.get(models.Employee, placeholder_user.employee_id).employee_code
    guesses_rejected = True
    for guess in ("0000", "1234", "0001", "9999", code[-4:] if len(code) >= 4 else "0000"):
        r = client.post("/api/auth/pin", json={"employee_code": code, "pin": guess})
        if r.status_code != 401:
            guesses_rejected = False
            break
    check(
        "an unissued placeholder pin_hash rejects every common guess",
        guesses_rejected,
        "a guess against a placeholder PIN was accepted",
    )
    # confirm the lockout itself fires (5 wrong attempts / 15 min, MMOS_PIN_MAX_ATTEMPTS)
    db.refresh(placeholder_user)
    check(
        "5 wrong PIN attempts locks the account (failed_pin_attempts/locked_until)",
        placeholder_user.locked_until is not None,
        f"failed_pin_attempts={placeholder_user.failed_pin_attempts} locked_until={placeholder_user.locked_until}",
    )

# ── 3. Session cookie flags match docs/06 (HttpOnly, Secure, SameSite=Lax) ──────────────
with TestClient(app) as client:
    emp = make_employee()
    real_pin = "4242"
    user = make_user(employee=emp, auth_type="local_pin", pin=real_pin)
    user.pin_set_at = datetime.now(timezone.utc)  # a real PIN IT actually issued
    db.commit()
    r = client.post("/api/auth/pin", json={"employee_code": emp.employee_code, "pin": real_pin})
    set_cookie = r.headers.get("set-cookie", "")
    check("PIN login succeeds with the real, issued PIN", r.status_code == 200, r.text)
    check("session cookie is HttpOnly", "httponly" in set_cookie.lower(), set_cookie)
    check("session cookie is Secure", "secure" in set_cookie.lower(), set_cookie)
    check("session cookie is SameSite=Lax", "samesite=lax" in set_cookie.lower(), set_cookie)

# ── 4. Deny-list end to end: grant delete -> appears on GET /api/agent/revocations ──────
with TestClient(app) as client:
    admin_emp = make_employee(employee_code="MMADM1")
    admin = make_user(employee=admin_emp, auth_type="google", is_platform_admin=True)
    sign_in(client, admin)

    svc_key_raw, svc_key_hash = new_service_key()
    service = models.Service(
        slug=f"chk-{uuid.uuid4().hex[:6]}", name="Check Service",
        base_url="https://chk.m-mines.com", service_key_hash=svc_key_hash,
    )
    db.add(service)
    db.flush()
    role = models.ServiceRole(service_id=service.id, key="viewer", name="Viewer")
    db.add(role)
    db.commit()

    target_emp = make_employee()
    target = make_user(employee=target_emp, auth_type="google")
    grant = models.Grant(user_id=target.id, service_id=service.id, service_role_id=role.id)
    db.add(grant)
    db.commit()

    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = client.delete(f"/api/admin/grants/{grant.id}")
    check("DELETE /api/admin/grants/{id} as admin -> 200", r.status_code == 200, r.text)

    r = client.get(
        "/api/agent/revocations",
        params={"since": since},
        headers={"Authorization": f"Bearer {svc_key_raw}"},
    )
    body = r.json() if r.status_code == 200 else {}
    subs = [row.get("sub") for row in body.get("revoked_subjects", [])]
    check(
        "removed grant's subject appears on GET /api/agent/revocations for its own service",
        target.subject in subs,
        f"status={r.status_code} body={body}",
    )

    # cross-service isolation: a second service must NOT see a revocation scoped to the first
    svc2_key_raw, svc2_key_hash = new_service_key()
    service2 = models.Service(
        slug=f"chk2-{uuid.uuid4().hex[:6]}", name="Other Service",
        base_url="https://chk2.m-mines.com", service_key_hash=svc2_key_hash,
    )
    db.add(service2)
    db.commit()
    r2 = client.get(
        "/api/agent/revocations",
        params={"since": since},
        headers={"Authorization": f"Bearer {svc2_key_raw}"},
    )
    body2 = r2.json() if r2.status_code == 200 else {}
    subs2 = [row.get("sub") for row in body2.get("revoked_subjects", [])]
    check(
        "a service-scoped revocation is NOT visible to a different service's poll",
        target.subject not in subs2,
        f"status={r2.status_code} body={body2}",
    )
    client.cookies.clear()

# ── 5. Token verification: alg confusion, wrong aud, expiry, deny-list (mmos-client-py) ──
sys.path.insert(0, str(ROOT / "packages" / "mmos-client-py"))
from mmos_client._denylist import DenyList  # noqa: E402
from mmos_client._verify import TokenError, verify_token  # noqa: E402

_jwk = jwks()["keys"][0]


class _StaticJWKS:
    def get_key(self, kid):
        return _jwk if kid == _jwk["kid"] else None


empty_denylist = DenyList()


def _try_verify(token, denylist=None):
    try:
        verify_token(
            token,
            jwks_cache=_StaticJWKS(),
            issuer="https://os.m-mines.com",
            audience="chk-service",
            skew_seconds=60,
            denylist=denylist or empty_denylist,
        )
        return None
    except TokenError as exc:
        return exc.reason


class _FakeEmployee:
    employee_code, work_email, full_name, hr_department, division, band, approval_level = (
        "MM0001", "chk@m-mines.com", "Check Person", "IT", "Corporate", "L3", None,
    )


class _FakeUser:
    id = uuid.uuid4()
    is_platform_admin = False


os.environ["MMOS_ISSUER"] = "https://os.m-mines.com"
from app.config import settings as _app_settings  # noqa: E402

_app_settings.cache_clear()
good_token, jti, _ttl = mint_service_token(
    user=_FakeUser(), employee=_FakeEmployee(), service_slug="chk-service", roles=["viewer"]
)
check("a correctly minted token verifies", _try_verify(good_token) is None, str(_try_verify(good_token)))

wrong_aud_token, _, _ = mint_service_token(
    user=_FakeUser(), employee=_FakeEmployee(), service_slug="a-different-service", roles=["viewer"]
)
check(
    "a token minted for a different service (aud) is rejected",
    _try_verify(wrong_aud_token) == "bad_audience",
    str(_try_verify(wrong_aud_token)),
)

import base64  # noqa: E402
import json  # noqa: E402


def _b64u_json(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


# python-jose refuses to even *encode* alg=none (defence at the library level, not just
# ours) -- hand-build the token the way a real attacker would: strip the signature entirely
# and claim it needs none. Same technique backend/tests/test_security.py uses.
none_alg_token = (
    f"{_b64u_json({'alg': 'none', 'typ': 'JWT', 'kid': _jwk['kid']})}."
    f"{_b64u_json({'iss': 'https://os.m-mines.com', 'sub': 'user:x', 'aud': 'chk-service', 'exp': int(datetime.now(timezone.utc).timestamp()) + 900})}."
)
check(
    '"alg": "none" token is rejected before any key material is touched',
    _try_verify(none_alg_token) == "alg_not_allowed",
    str(_try_verify(none_alg_token)),
)

# RS256 -> HS256 confusion: sign with the PUBLIC key's PEM bytes as an HMAC secret.
# python-jose itself refuses to *encode* this (it guards against using an asymmetric key
# as an HMAC secret) -- hand-rolled here exactly like backend/tests/test_security.py's
# _forge_hs256, since a real attacker would not go through that library guard either.
import hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402
from app.security import _private_key  # noqa: E402

pub_pem = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
_h = _b64u_json({"alg": "HS256", "typ": "JWT", "kid": _jwk["kid"]})
_p = _b64u_json({"iss": "https://os.m-mines.com", "sub": "user:x", "aud": "chk-service",
                  "exp": int(datetime.now(timezone.utc).timestamp()) + 900})
_sig = _hmac.new(pub_pem, f"{_h}.{_p}".encode(), hashlib.sha256).digest()
hs256_token = f"{_h}.{_p}.{base64.urlsafe_b64encode(_sig).rstrip(b'=').decode()}"
check(
    "RS256->HS256 alg-confusion (public key as HMAC secret) is rejected",
    _try_verify(hs256_token) == "alg_not_allowed",
    str(_try_verify(hs256_token)),
)

dl = DenyList()
dl.merge(revoked_subjects=[{"sub": "user:x"}], revoked_jti=[], now=datetime.now(timezone.utc).isoformat())
revoked_probe, _, _ = mint_service_token(
    user=_FakeUser(), employee=_FakeEmployee(), service_slug="chk-service", roles=["viewer"]
)
# mint_service_token always uses the real user id as sub; patch by re-verifying with a
# denylist keyed to that exact sub instead of the literal "user:x" placeholder above.
real_sub = f"user:{_FakeUser.id}"
dl2 = DenyList()
dl2.merge(revoked_subjects=[{"sub": real_sub}], revoked_jti=[], now=datetime.now(timezone.utc).isoformat())
check(
    "a revoked subject is rejected even with an otherwise-valid signature",
    _try_verify(revoked_probe, denylist=dl2) == "revoked",
    str(_try_verify(revoked_probe, denylist=dl2)),
)

# ── 6. Network gate: the Nth-from-right X-Forwarded-For trust boundary ──────────────────
import app.deps as _deps  # noqa: E402
from app.config import Settings as _Settings  # noqa: E402


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, headers, client_host):
        self.headers = headers
        self.client = _FakeClient(client_host)


_orig_settings = _deps.settings
_gate_cfg = _Settings(network_mode="private", allowed_cidrs="10.8.0.0/24,127.0.0.1/32", trusted_proxy_count=1)
_deps.settings = lambda: _gate_cfg
try:
    legit = _deps.client_ip(_FakeRequest({"x-forwarded-for": "10.8.0.5"}, "172.19.0.3"))
    check(
        "client_ip() reads the proxy-appended entry when trusted_proxy_count=1",
        legit == "10.8.0.5",
        f"got {legit!r}",
    )

    no_header = _deps.client_ip(_FakeRequest({}, "172.19.0.3"))
    check(
        "client_ip() falls back to the direct TCP peer when no X-Forwarded-For is present",
        no_header == "172.19.0.3",
        f"got {no_header!r}",
    )

    # This is the trust-boundary fact docs/06 and the hardening brief both call out: the
    # code cannot distinguish "a trusted proxy appended this" from "the direct caller typed
    # this themselves" -- it just trusts whichever value sits N-from-the-right. Demonstrated
    # here, not asserted as a pass/fail, because whether this is exploitable depends on
    # infrastructure this script cannot see (whether the app is reachable at all except
    # through exactly one trusted hop) -- see docs/11-security-review.md finding #1.
    spoofed = _deps.client_ip(_FakeRequest({"x-forwarded-for": "10.8.0.1"}, "203.0.113.50"))
    if spoofed == "10.8.0.1":
        warn(
            "client_ip() cannot tell a real proxy hop from a self-supplied header",
            "a caller at 203.0.113.50 sending its own 'X-Forwarded-For: 10.8.0.1' is trusted "
            "exactly as if a real proxy had added that entry -- safe ONLY if the app is "
            "provably unreachable except through exactly one real trusted hop (docs/11 #1)",
        )
finally:
    _deps.settings = _orig_settings

# ── 7. CSP header -- docs/06 requires one; middleware.py (frozen) does not set it ───────
with TestClient(app) as client:
    r = client.get("/healthz")
    if "content-security-policy" not in {k.lower() for k in r.headers.keys()}:
        warn(
            "no Content-Security-Policy header on any response",
            "docs/06-network-security.md 'Baseline hardening' asks for one; "
            "backend/app/middleware.py (frozen) does not set it -- see docs/11 finding",
        )
    else:
        check("Content-Security-Policy header present", True)

print()
if _FAILED:
    print("== FAIL: one or more mechanical security assertions did not hold ==")
else:
    print("== PASS: all mechanical security assertions held ==")

db.close()
engine.dispose()
for p in (_scratch, _key):
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass

raise SystemExit(1 if _FAILED else 0)
