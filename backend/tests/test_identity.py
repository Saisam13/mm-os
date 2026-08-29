"""Acceptance tests for A1 · Identity and People (agents/A1-identity.md).

Runs on the shared SQLite harness (tests/conftest.py) — there is no Postgres on this
machine. `alembic upgrade head` / `downgrade base` against a real server is therefore
smoke-tested offline (`--sql` mode, no connection needed) and, when a real Postgres is
reachable, by test_alembic_migration_head_and_downgrade_against_real_postgres below (skipped
here — see handoff/a1-identity.md ## Not done).

No live Google calls happen anywhere in this file: both HTTP calls the callback route makes
(token exchange, JWKS fetch) go through `app.routers.auth.httpx`, monkeypatched here.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt
from sqlalchemy import select

import app.routers.auth as auth_module
from app import models
from app.config import settings
from app.security import new_session_token, session_expiry, verify_pin

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_pin_rate_limiter():
    """The PIN limiter is now a shared DB table (app.ratelimit / models.RateLimit), not the
    old in-process _pin_hits dict. The conftest `db` fixture already wipes every table
    between tests, so limiter state cannot leak; this clears the RateLimit rows defensively
    before and after in case a test drives requests through its own session."""
    from app.db import SessionLocal
    from app.models import RateLimit

    def _clear():
        s = SessionLocal()
        try:
            s.query(RateLimit).delete()
            s.commit()
        finally:
            s.close()

    _clear()
    yield
    _clear()


# ── Google id_token signing helper (test-only keypair, never touches security.py) ──────
def _b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def google_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    numbers = key.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": "test-kid", "use": "sig", "alg": "RS256", "n": _b64u(numbers.n), "e": _b64u(numbers.e)}
    return pem, jwk


def _id_token(pem: str, kid: str, **claims) -> str:
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


def _default_claims(**overrides) -> dict:
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": settings().google_client_id,
        "sub": "111122223333",
        "email": "someone@m-mines.com",
        "email_verified": True,
        "hd": settings().google_hosted_domain,
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return claims


def _patch_google(monkeypatch, jwk: dict, id_token: str):
    def fake_post(url, data=None, timeout=None):
        assert url == auth_module.GOOGLE_TOKEN_URL
        return httpx.Response(200, json={"id_token": id_token, "access_token": "unused"})

    def fake_get(url, timeout=None):
        assert url == auth_module.GOOGLE_JWKS_URL
        return httpx.Response(200, json={"keys": [jwk]})

    monkeypatch.setattr(auth_module.httpx, "post", fake_post)
    monkeypatch.setattr(auth_module.httpx, "get", fake_get)


def _start_google_login(client) -> str:
    """Hits /google/start, returns the `state` value Google would echo back. The oauth
    cookie it sets rides along on `client` automatically for the callback request."""
    resp = client.get("/api/auth/google/start?next=/", follow_redirects=False)
    assert resp.status_code == 302
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert qs["hd"][0] == settings().google_hosted_domain  # the hint; not what decides
    return qs["state"][0]


def _start_google_link(client) -> str:
    """Hits /google/link/start (requires an already-authenticated `client`). No `hd` hint
    is sent — linking accepts any verified Google account, personal ones included."""
    resp = client.get("/api/auth/google/link/start?next=/", follow_redirects=False)
    assert resp.status_code == 302
    qs = parse_qs(urlparse(resp.headers["location"]).query)
    assert "hd" not in qs
    return qs["state"][0]


# ── Google login ─────────────────────────────────────────────────────────────
def test_google_callback_rejects_wrong_hd(client, monkeypatch, google_key, db):
    pem, jwk = google_key
    state = _start_google_login(client)
    token = _id_token(pem, jwk["kid"], **_default_claims(hd="not-m-mines.com"))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)

    assert resp.status_code == 401
    assert resp.json()["error"] == "hd_mismatch"
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "login.google.denied")) is not None


def test_google_callback_unknown_email_rejected(client, monkeypatch, google_key, db):
    pem, jwk = google_key
    state = _start_google_login(client)
    token = _id_token(pem, jwk["kid"], **_default_claims(email="nobody@m-mines.com"))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)

    assert resp.status_code == 401
    assert resp.json()["error"] == "unknown_user"


def test_google_callback_inactive_user_rejected(client, monkeypatch, google_key, db, make_employee, make_user):
    employee = make_employee()
    make_user(employee=employee, auth_type="google", login_email=employee.work_email, is_active=False)

    pem, jwk = google_key
    state = _start_google_login(client)
    token = _id_token(pem, jwk["kid"], **_default_claims(email=employee.work_email))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)

    assert resp.status_code == 401
    assert resp.json()["error"] == "unknown_user"  # same signal as truly unknown


def test_google_callback_success_sets_session_and_audits(client, monkeypatch, google_key, db, make_employee, make_user):
    employee = make_employee()
    user = make_user(employee=employee, auth_type="google", login_email=employee.work_email)

    pem, jwk = google_key
    state = _start_google_login(client)
    token = _id_token(pem, jwk["kid"], **_default_claims(email=employee.work_email))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    assert settings().cookie_name in resp.cookies
    row = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "login.google"))
    assert row is not None and row.actor_user_id == user.id

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["user"]["employee_code"] == employee.employee_code


# ── Google account linking (owner ruling: PIN-first + self-service linking) ────────────
def test_google_link_attaches_verified_email_and_keeps_pin_working(client, monkeypatch, google_key, db, make_employee, make_user):
    employee = make_employee()
    user = make_user(employee=employee, auth_type="local_pin", pin="4242")
    login = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "4242"})
    assert login.status_code == 200

    pem, jwk = google_key
    state = _start_google_link(client)
    # A personal gmail address links successfully — no hd restriction on this flow.
    token = _id_token(pem, jwk["kid"], **_default_claims(email="personal.address@gmail.com", hd=None))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert resp.status_code == 302

    db.refresh(user)
    assert user.login_email == "personal.address@gmail.com"
    assert user.auth_type == "google"
    assert user.pin_hash is not None  # kept — PIN login must keep working

    row = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "login.google.linked"))
    assert row is not None and row.actor_user_id == user.id

    still_works = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "4242"})
    assert still_works.status_code == 200


def test_google_link_rejects_email_already_linked_to_another_user(client, monkeypatch, google_key, db, make_employee, make_user):
    other_employee = make_employee()
    make_user(employee=other_employee, auth_type="google", login_email="claimed@gmail.com")

    employee = make_employee()
    make_user(employee=employee, auth_type="local_pin", pin="1111")
    client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "1111"})

    pem, jwk = google_key
    state = _start_google_link(client)
    token = _id_token(pem, jwk["kid"], **_default_claims(email="claimed@gmail.com", hd=None))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert resp.status_code == 409
    assert resp.json()["error"] == "google_account_already_linked"
    # Generic message — does not name or otherwise identify the other account.
    assert "claimed@gmail.com" not in resp.json()["message"]


def test_google_link_requires_an_authenticated_session(client, monkeypatch, google_key):
    resp = client.get("/api/auth/google/link/start", follow_redirects=False)
    assert resp.status_code == 401


def test_google_login_allows_linked_personal_gmail_regardless_of_hd(client, monkeypatch, google_key, db, make_employee, make_user):
    employee = make_employee()
    user = make_user(employee=employee, auth_type="google", login_email="linked.person@gmail.com")

    pem, jwk = google_key
    state = _start_google_login(client)
    token = _id_token(pem, jwk["kid"], **_default_claims(email="linked.person@gmail.com", hd=None))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert resp.status_code == 302
    assert settings().cookie_name in resp.cookies
    row = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "login.google"))
    assert row is not None and row.actor_user_id == user.id


def test_google_login_rejects_unknown_gmail_address_via_hd_mismatch(client, monkeypatch, google_key, db):
    pem, jwk = google_key
    state = _start_google_login(client)
    token = _id_token(pem, jwk["kid"], **_default_claims(email="total.stranger@gmail.com", hd=None))
    _patch_google(monkeypatch, jwk, token)

    resp = client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert resp.status_code == 401
    assert resp.json()["error"] == "hd_mismatch"


# ── PIN login ────────────────────────────────────────────────────────────────
def test_pin_lockout_then_correct_pin_still_fails(client, db, make_employee, make_user):
    employee = make_employee()
    user = make_user(employee=employee, auth_type="local_pin", pin="1234")

    for _ in range(6):
        resp = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "0000"})
        assert resp.status_code == 401

    db.refresh(user)
    assert user.locked_until is not None and user.locked_until > datetime.now(timezone.utc)

    resp = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "1234"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_credentials"


def test_pin_login_success_and_generic_error_for_wrong_code(client, db, make_employee, make_user):
    employee = make_employee()
    make_user(employee=employee, auth_type="local_pin", pin="4242")

    wrong_code = client.post("/api/auth/pin", json={"employee_code": "MM-NOPE", "pin": "4242"})
    wrong_pin = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "0000"})
    assert wrong_code.status_code == wrong_pin.status_code == 401
    assert wrong_code.json()["error"] == wrong_pin.json()["error"] and wrong_code.json()["message"] == wrong_pin.json()["message"]  # same generic message

    ok = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "4242"})
    assert ok.status_code == 200
    assert settings().cookie_name in ok.cookies


# ── PIN route: per-IP throttle (B3 security review, HIGH finding) ──────────────────────
# Employee codes are guessable and the per-user lockout above only protects one account at
# a time — without a per-IP limit, a single caller could walk every employee code with
# junk PINs and lock all 73 accounts out within seconds. See routers/auth.py's
# _pin_rate_limited, which mirrors routers/tokens.py's in-process limiter (60/min).
def test_pin_route_throttles_a_burst_from_one_ip(client, make_employee, make_user):
    employee = make_employee()
    make_user(employee=employee, auth_type="local_pin", pin="1234")
    headers = {"X-Forwarded-For": "203.0.113.5"}

    for _ in range(auth_module._PIN_RATE_LIMIT):
        resp = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "0000"}, headers=headers)
        assert resp.status_code in (401, 429)

    throttled = client.post("/api/auth/pin", json={"employee_code": employee.employee_code, "pin": "0000"}, headers=headers)
    assert throttled.status_code == 429
    assert throttled.json()["error"] == "rate_limited"


def test_throttled_pin_attempt_does_not_count_toward_lockout(client, db, make_employee, make_user):
    # Exhaust the per-IP budget against an unrelated code first, so the account under test
    # (`victim`) never has a single real attempt processed against it — proving a
    # throttled request truly never reaches (and never increments) failed_pin_attempts.
    decoy_employee = make_employee()
    make_user(employee=decoy_employee, auth_type="local_pin", pin="9999")

    victim_employee = make_employee()
    victim = make_user(employee=victim_employee, auth_type="local_pin", pin="1234")

    headers = {"X-Forwarded-For": "203.0.113.6"}
    for _ in range(auth_module._PIN_RATE_LIMIT):
        client.post("/api/auth/pin", json={"employee_code": decoy_employee.employee_code, "pin": "0000"}, headers=headers)

    resp = client.post("/api/auth/pin", json={"employee_code": victim_employee.employee_code, "pin": "0000"}, headers=headers)
    assert resp.status_code == 429

    db.refresh(victim)
    assert victim.failed_pin_attempts == 0
    assert victim.locked_until is None


def test_pin_throttle_is_scoped_per_ip_not_global(client, make_employee, make_user):
    attacker_employee = make_employee()
    make_user(employee=attacker_employee, auth_type="local_pin", pin="9999")

    legit_employee = make_employee()
    make_user(employee=legit_employee, auth_type="local_pin", pin="4242")

    attacker_headers = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(auth_module._PIN_RATE_LIMIT):
        client.post("/api/auth/pin", json={"employee_code": attacker_employee.employee_code, "pin": "0000"}, headers=attacker_headers)
    throttled = client.post("/api/auth/pin", json={"employee_code": attacker_employee.employee_code, "pin": "0000"}, headers=attacker_headers)
    assert throttled.status_code == 429

    legit_headers = {"X-Forwarded-For": "203.0.113.99"}
    ok = client.post("/api/auth/pin", json={"employee_code": legit_employee.employee_code, "pin": "4242"}, headers=legit_headers)
    assert ok.status_code == 200


def test_logout_revokes_session(client, db, make_user, sign_in):
    user = make_user()
    session_row = sign_in(user)

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200

    db.refresh(session_row)
    assert session_row.revoked_at is not None
    assert client.get("/api/me").status_code == 401


# ── /api/me ──────────────────────────────────────────────────────────────────
def test_me_returns_exactly_the_grants_a_user_holds(client, db, make_employee, make_user, make_service, make_grant, sign_in):
    employee = make_employee(full_name="Grantee Person", band="L2")
    user = make_user(employee=employee)
    svc_a, roles_a = make_service(slug="svc-a")
    svc_b, roles_b = make_service(slug="svc-b")
    make_service(slug="svc-c")  # no grant on this one — must not appear
    make_grant(user, svc_a, roles_a["viewer"])
    make_grant(user, svc_b, roles_b["admin"])
    sign_in(user)

    resp = client.get("/api/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["employee_code"] == employee.employee_code
    assert body["user"]["name"] == "Grantee Person"
    slugs = {s["slug"] for s in body["services"]}
    assert slugs == {"svc-a", "svc-b"}
    assert len(body["services"]) == 2


def test_me_returns_no_services_for_a_user_with_no_grants(client, make_user, sign_in):
    user = make_user()
    sign_in(user)

    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["services"] == []


def test_me_excludes_expired_grants(client, make_user, make_service, make_grant, sign_in):
    user = make_user()
    svc, roles = make_service(slug="svc-expired")
    make_grant(user, svc, roles["viewer"], expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    sign_in(user)

    resp = client.get("/api/me")
    assert resp.json()["services"] == []


# ── admin: deactivating a user ────────────────────────────────────────────────
def test_deactivate_user_revokes_sessions_and_writes_revocation_in_one_transaction(
    db, client, make_employee, make_user, sign_in
):
    target = make_user()
    raw, token_hash = new_session_token()
    live_session = models.Session(user_id=target.id, token_hash=token_hash, expires_at=session_expiry())
    db.add(live_session)
    db.commit()

    admin_employee = make_employee()
    admin = make_user(employee=admin_employee, is_platform_admin=True)
    sign_in(admin)

    resp = client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    db.refresh(target)
    db.refresh(live_session)
    assert target.is_active is False
    assert live_session.revoked_at is not None

    revocation = db.scalar(select(models.Revocation).where(models.Revocation.subject == target.subject))
    assert revocation is not None
    assert revocation.reason == "user_deactivated"

    audit_row = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "user.deactivate"))
    assert audit_row is not None and audit_row.target_id == str(target.id)


def test_deactivated_user_session_is_rejected(db, client, make_user, sign_in, make_employee):
    target = make_user()
    sign_in(target)  # cookie now belongs to target

    admin_employee = make_employee()
    admin = make_user(employee=admin_employee, is_platform_admin=True)

    # Deactivate directly via the model layer (equivalent to another admin session doing it)
    # so we can keep using `target`'s cookie on `client` to prove it stops working.
    target.is_active = False
    db.add(
        models.Revocation(subject=target.subject, reason="user_deactivated", revoked_by=admin.id, purge_after=datetime.now(timezone.utc) + timedelta(hours=2))
    )
    db.commit()

    resp = client.get("/api/me")
    assert resp.status_code == 403


def test_non_admin_cannot_reach_admin_routes(client, make_user, sign_in):
    user = make_user()
    sign_in(user)
    resp = client.get("/api/admin/users")
    assert resp.status_code == 403


def test_set_and_clear_pin_shows_once(db, client, make_employee, make_user, sign_in):
    admin_employee = make_employee()
    admin = make_user(employee=admin_employee, is_platform_admin=True)
    sign_in(admin)

    target_employee = make_employee()
    target = make_user(employee=target_employee, auth_type="local_pin", pin="9999")

    resp = client.post(f"/api/admin/users/{target.id}/pin", json={})
    assert resp.status_code == 200
    new_pin = resp.json()["pin"]
    assert new_pin and new_pin != "9999"

    db.refresh(target)
    assert verify_pin(new_pin, target.pin_hash)

    cleared = client.post(f"/api/admin/users/{target.id}/pin", json={"clear": True})
    assert cleared.status_code == 200
    assert cleared.json()["pin"] is None
    db.refresh(target)
    assert target.pin_set_at is None
    # pin_required CHECK still holds — pin_hash is never NULL for a local_pin user.
    assert target.pin_hash is not None


# ── seed importer (synthetic rows only — never the real spreadsheet in tests) ──────────
def _write_sheet(tmp_path, rows):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employee Role & Access Map"
    ws.append([
        "Employee Code", "Full Name", "Work Email", "HR Department",
        "Division (Approval Matrix)", "Job Title (New Org Structure)", "Band",
        "Matched Approval-Matrix Role", "Match Status", "Approval Level",
        "ERP-Based System Access (assigned role)", "Extra / Cross-Dept Report Access",
        "Special Approver Override", "Category Overlay Notes", "Action Needed",
    ])
    for r in rows:
        ws.append([
            r["code"], r["name"], r.get("email"), r.get("dept", "IT"), r.get("division", "Corporate"),
            r.get("title", "Engineer"), r.get("band", "L3"), None, None, r.get("approval"),
            r.get("erp_access"), r.get("extra_access"), r.get("override"), None, None,
        ])
    path = tmp_path / "synthetic.xlsx"
    wb.save(path)
    return path


def test_seed_dry_run_reports_new_and_writes_nothing(db, tmp_path):
    from app.seed import compute_diff, load_sheet_rows

    path = _write_sheet(tmp_path, [
        {"code": "ZZ01", "name": "Test One", "email": "zz01@m-mines.com"},
        {"code": "ZZ02", "name": "Test Two", "email": None},  # no work email -> local_pin
    ])
    rows = load_sheet_rows(path)
    diff = compute_diff(db, rows)

    assert len(diff.new) == 2
    assert diff.changed == []
    assert db.scalar(select(models.Employee)) is None  # dry run: nothing written


def test_seed_commit_is_idempotent(db, tmp_path):
    from app.seed import apply_diff, compute_diff, load_sheet_rows

    path = _write_sheet(tmp_path, [
        {"code": "ZZ10", "name": "Idempotent Employee", "email": "zz10@m-mines.com", "override": "Special approver: yes"},
        {"code": "ZZ11", "name": "No Mailbox Employee", "email": None},
    ])
    rows = load_sheet_rows(path)

    diff1 = compute_diff(db, rows)
    apply_diff(db, diff1)
    db.commit()
    assert len(diff1.new) == 2

    diff2 = compute_diff(db, rows)
    assert len(diff2.new) == 0
    assert len(diff2.changed) == 0

    no_email_user = db.scalar(
        select(models.User).join(models.Employee, models.User.employee_id == models.Employee.id)
        .where(models.Employee.employee_code == "ZZ11")
    )
    assert no_email_user.auth_type == "local_pin"
    assert no_email_user.pin_set_at is None  # "PIN not set" — see ## Contract objections
    assert no_email_user.pin_hash is not None  # CHECK pin_required is still satisfied

    approver = db.scalar(select(models.Employee).where(models.Employee.employee_code == "ZZ10"))
    assert approver.is_approver is True


def test_seed_every_new_employee_becomes_local_pin_first(db, tmp_path):
    """Owner ruling (handoff/ORCHESTRATOR.md): ALL employees get a local PIN account on
    import, corporate work email included -- not just the ones without one. Google
    sign-in is added later, only through the self-service link flow in routers/auth.py."""
    from app.seed import apply_diff, compute_diff, load_sheet_rows

    path = _write_sheet(tmp_path, [
        {"code": "ZZ60", "name": "Corporate Email", "email": "zz60@m-mines.com"},
        {"code": "ZZ61", "name": "Personal Gmail", "email": "zz61.personal@gmail.com"},
        {"code": "ZZ62", "name": "No Email At All", "email": None},
    ])
    rows = load_sheet_rows(path)
    diff = compute_diff(db, rows)
    apply_diff(db, diff)
    db.commit()

    def _user_for(code):
        return db.scalar(
            select(models.User).join(models.Employee, models.User.employee_id == models.Employee.id)
            .where(models.Employee.employee_code == code)
        )

    for code in ("ZZ60", "ZZ61", "ZZ62"):
        user = _user_for(code)
        assert user.auth_type == "local_pin"
        assert user.login_email is None
        assert user.pin_set_at is None  # "PIN not yet issued by IT"
        assert user.pin_hash is not None  # pin_required CHECK is still satisfied

    # The corporate and personal addresses are both still kept on the Employee record for
    # HR/contact purposes -- they just aren't treated as login credentials yet.
    corp_employee = db.scalar(select(models.Employee).where(models.Employee.employee_code == "ZZ60"))
    gmail_employee = db.scalar(select(models.Employee).where(models.Employee.employee_code == "ZZ61"))
    assert corp_employee.work_email == "zz60@m-mines.com"
    assert gmail_employee.work_email == "zz61.personal@gmail.com"


def test_seed_reports_conflict_without_writing_the_conflicting_row(db, tmp_path, make_employee):
    from app.seed import compute_diff, load_sheet_rows

    existing = make_employee(employee_code="ZZ20", work_email="shared@m-mines.com")
    path = _write_sheet(tmp_path, [
        {"code": "ZZ21", "name": "Email Collides", "email": "shared@m-mines.com"},
    ])
    rows = load_sheet_rows(path)
    diff = compute_diff(db, rows)

    assert diff.new == []
    assert len(diff.conflicts) == 1
    assert db.scalar(select(models.Employee).where(models.Employee.employee_code == "ZZ21")) is None


def test_seed_proposed_grants_report_is_not_applied_as_grants(db, tmp_path):
    from app.seed import apply_diff, compute_diff, load_sheet_rows

    path = _write_sheet(tmp_path, [
        {"code": "ZZ30", "name": "Prose Access", "email": "zz30@m-mines.com", "erp_access": "Approve Purchase Orders"},
    ])
    rows = load_sheet_rows(path)
    diff = compute_diff(db, rows)
    assert len(diff.proposed_grants) == 1
    apply_diff(db, diff)
    db.commit()
    assert db.scalar(select(models.Grant)) is None  # never machine-translated into a grant


def test_resolve_managers_leaves_ties_unresolved(db):
    from app.seed import resolve_managers

    emp1 = models.Employee(employee_code="ZZ40", full_name="Junior", work_email="zz40@m-mines.com", hr_department="IT", division="Corporate", job_title="Eng", band="L2")
    emp2 = models.Employee(employee_code="ZZ41", full_name="Senior A", work_email="zz41@m-mines.com", hr_department="IT", division="Corporate", job_title="Lead", band="L3")
    emp3 = models.Employee(employee_code="ZZ42", full_name="Senior B", work_email="zz42@m-mines.com", hr_department="IT", division="Corporate", job_title="Lead", band="L3")
    db.add_all([emp1, emp2, emp3])
    db.commit()

    resolved, unresolved = resolve_managers(db)
    assert not any(line.startswith("ZZ40") for line in resolved)
    assert any(line.startswith("ZZ40") for line in unresolved)


def test_resolve_managers_picks_the_single_next_band_up(db):
    from app.seed import resolve_managers

    emp1 = models.Employee(employee_code="ZZ50", full_name="Junior", work_email="zz50@m-mines.com", hr_department="IT", division="Corporate", job_title="Eng", band="L2")
    emp2 = models.Employee(employee_code="ZZ51", full_name="Lead", work_email="zz51@m-mines.com", hr_department="IT", division="Corporate", job_title="Lead", band="L3")
    db.add_all([emp1, emp2])
    db.commit()

    resolved, _ = resolve_managers(db)
    db.commit()
    assert "ZZ50 -> ZZ51" in resolved
    db.refresh(emp1)
    assert emp1.manager_id == emp2.id


# ── alembic (genuinely Postgres-only) ─────────────────────────────────────────
@pytest.mark.needs_postgres
def test_alembic_migration_head_and_downgrade_against_real_postgres():
    """Not runnable here — no Postgres on the build machine (see ## Not done). Set
    MMOS_TEST_POSTGRES_URL to a real, empty Postgres database to exercise this for real."""
    pg_url = os.environ.get("MMOS_TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("MMOS_TEST_POSTGRES_URL not set — no Postgres available on this machine")

    env = {**os.environ, "MMOS_DATABASE_URL": pg_url}
    up = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert up.returncode == 0, up.stderr
    down = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert down.returncode == 0, down.stderr


def test_alembic_migration_renders_offline_without_error():
    """Runnable everywhere: `--sql` mode renders the migration's SQL for the postgresql
    dialect without opening a connection, catching syntax/API mistakes even with no
    Postgres available. This is not a substitute for actually running it — see ## Not done.
    """
    env = {
        **os.environ,
        "MMOS_DATABASE_URL": "postgresql+psycopg://x:x@localhost/x",
        "MMOS_SIGNING_KEY_PATH": os.environ["MMOS_SIGNING_KEY_PATH"],
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE employees" in result.stdout
    assert "CREATE TABLE audit_log" in result.stdout
