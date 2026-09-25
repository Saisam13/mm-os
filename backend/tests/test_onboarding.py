"""First Google sign-in: confirm the employee code, set a PIN (app/onboarding.py,
routers/auth.py /onboard). Fake people only."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import models
from app.config import settings
from app.departments import UNASSIGNED
from app.onboarding import PersonalEmail
from tests.test_identity import _default_claims, _id_token, _patch_google, _start_google_login, google_key  # noqa: F401


def _google_login(client, monkeypatch, google_key, **claims):
    pem, jwk = google_key
    state = _start_google_login(client)
    _patch_google(monkeypatch, jwk, _id_token(pem, jwk["kid"], **_default_claims(**claims)))
    return client.get("/api/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)


@pytest.fixture()
def lowest(db, make_service):
    """Two services: one with a default (lowest) role, one without."""
    svc, roles = make_service(slug="desk", roles=("requester", "agent"))
    roles["requester"].is_default = True
    make_service(slug="sales", roles=("viewer", "admin"))
    db.commit()
    return svc


# ── official email: signed in, then asked once for code + PIN ──────────────────
def test_official_email_signs_in_then_needs_onboarding(client, monkeypatch, google_key, db, make_employee, make_user):
    emp = make_employee(employee_code="MM115", work_email="fake.person@m-mines.com")
    user = make_user(employee=emp, login_email="fake.person@m-mines.com")

    resp = _google_login(client, monkeypatch, google_key, email="fake.person@m-mines.com")
    assert resp.status_code == 302 and settings().cookie_name in resp.cookies
    me = client.get("/api/me").json()
    assert me["user"]["needs_onboarding"] is True
    assert client.get("/api/auth/onboard").json()["mode"] == "session"

    wrong = client.post("/api/auth/onboard", json={"employee_code": "MM116", "pin": "4321"})
    assert wrong.status_code == 422 and wrong.json()["error"] == "code_mismatch"

    ok = client.post("/api/auth/onboard", json={"employee_code": "mm-00115", "pin": "4321"})
    assert ok.status_code == 200
    db.refresh(user)
    assert user.pin_set_at is not None
    assert client.get("/api/me").json()["user"]["needs_onboarding"] is False
    assert client.get("/api/me").json()["services"] == []  # no default roles exist in this test
    assert client.post("/api/auth/pin", json={"employee_code": "MM115", "pin": "4321"}).status_code == 200


def test_non_mm_code_still_matches_as_typed(client, monkeypatch, google_key, db, make_employee, make_user):
    emp = make_employee(employee_code="MM-ITADMIN", work_email="it.person@m-mines.com")
    make_user(employee=emp, login_email="it.person@m-mines.com")
    _google_login(client, monkeypatch, google_key, email="it.person@m-mines.com")
    assert client.post("/api/auth/onboard", json={"employee_code": "mm-itadmin", "pin": "5555"}).status_code == 200


# ── personal Gmail listed by the sheet ─────────────────────────────────────────
def test_listed_personal_gmail_needs_the_right_code_then_signs_in_directly(
    client, monkeypatch, google_key, db, make_employee, make_user
):
    emp = make_employee(employee_code="MM77", work_email="own.name@m-mines.com")
    user = make_user(employee=emp, login_email="own.name@m-mines.com")
    db.add(PersonalEmail(email="own.name@gmail.com", user_id=user.id))
    db.commit()

    resp = _google_login(client, monkeypatch, google_key, email="Own.Name@gmail.com", hd=None)
    assert resp.status_code == 302 and resp.headers["location"] == "/welcome"
    assert settings().cookie_name not in resp.cookies  # no session before the code check
    status = client.get("/api/auth/onboard").json()
    assert status["mode"] == "personal" and status["has_pin"] is False

    wrong = client.post("/api/auth/onboard", json={"employee_code": "MM78", "pin": "2468"})
    assert wrong.status_code == 422
    assert db.get(PersonalEmail, "own.name@gmail.com").verified_at is None

    ok = client.post("/api/auth/onboard", json={"employee_code": "MM77", "pin": "2468"})
    assert ok.status_code == 200 and ok.json()["next"] == "/services"
    assert client.get("/api/me").json()["user"]["employee_code"] == "MM77"
    db.expire_all()
    assert db.get(PersonalEmail, "own.name@gmail.com").verified_at is not None

    client.cookies.clear()
    again = _google_login(client, monkeypatch, google_key, email="own.name@gmail.com", hd=None)
    assert again.status_code == 302 and again.headers["location"] == "/"
    assert settings().cookie_name in again.cookies


def test_personal_gmail_cannot_overwrite_an_existing_pin(client, monkeypatch, google_key, db, make_employee, make_user):
    emp = make_employee(employee_code="MM78", work_email="pin.holder@m-mines.com")
    user = make_user(employee=emp, login_email="pin.holder@m-mines.com")
    from app.security import hash_pin
    user.pin_hash, user.pin_set_at = hash_pin("1357"), datetime.now(timezone.utc)
    db.add(PersonalEmail(email="pin.holder@gmail.com", user_id=user.id))
    db.commit()

    _google_login(client, monkeypatch, google_key, email="pin.holder@gmail.com", hd=None)
    assert client.get("/api/auth/onboard").json()["has_pin"] is True
    bad = client.post("/api/auth/onboard", json={"employee_code": "MM78", "pin": "9999"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/onboard", json={"employee_code": "MM78", "pin": "1357"})
    assert ok.status_code == 200


def test_unlisted_gmail_is_always_refused(client, monkeypatch, google_key, db):
    resp = _google_login(client, monkeypatch, google_key, email="stranger@gmail.com", hd=None)
    assert resp.status_code == 401 and resp.json()["error"] == "hd_mismatch"


# ── company address not in the sheet ───────────────────────────────────────────
def test_unknown_company_address_gets_unassigned_account_with_lowest_roles(
    client, monkeypatch, google_key, db, lowest
):
    resp = _google_login(client, monkeypatch, google_key, email="new.joiner@m-mines.com", name="New Joiner")
    assert resp.headers["location"] == "/welcome"
    assert client.get("/api/auth/onboard").json()["mode"] == "new"

    ok = client.post("/api/auth/onboard", json={"employee_code": "MM-0901", "pin": "8642"})
    assert ok.status_code == 200
    emp = db.scalar(select(models.Employee).where(models.Employee.employee_code == "MM901"))
    assert emp is not None and emp.hr_department == UNASSIGNED and emp.full_name == "New Joiner"
    me = client.get("/api/me").json()
    assert {s["slug"]: s["role"] for s in me["services"]} == {"desk": "requester"}  # no default on "sales"


def test_unknown_company_address_cannot_claim_someone_elses_code(
    client, monkeypatch, google_key, db, make_employee, make_user, lowest
):
    taken = make_employee(employee_code="MM55", work_email="real.owner@m-mines.com")
    make_user(employee=taken, login_email="real.owner@m-mines.com")
    _google_login(client, monkeypatch, google_key, email="imposter@m-mines.com")
    resp = client.post("/api/auth/onboard", json={"employee_code": "MM55", "pin": "1111"})
    assert resp.status_code == 409 and resp.json()["error"] == "code_taken"
    assert "real.owner" not in resp.json()["message"]
    assert db.scalar(select(models.User).where(models.User.login_email == "imposter@m-mines.com")) is None


def test_onboard_without_google_or_session_is_refused(client):
    resp = client.post("/api/auth/onboard", json={"employee_code": "MM1", "pin": "1234"})
    assert resp.status_code == 401


# ── mail tiles ─────────────────────────────────────────────────────────────────
def test_me_lists_own_and_department_mailboxes(client, db, make_employee, make_user, sign_in):
    from app.provision import FUNCTIONAL_JOB_TITLE
    emp = make_employee(hr_department="Purchase", work_email="a.buyer@m-mines.com")
    user = make_user(employee=emp)
    box = make_employee(hr_department="Purchase", work_email="purchase.c9@m-mines.com", job_title=FUNCTIONAL_JOB_TITLE)
    make_user(employee=box)
    other = make_employee(hr_department="Finance", work_email="finance.box@m-mines.com", job_title=FUNCTIONAL_JOB_TITLE)
    make_user(employee=other)
    sign_in(user)
    mail = client.get("/api/me").json()["mail"]
    assert [(m["kind"], m["email"]) for m in mail] == [("own", "a.buyer@m-mines.com"), ("department", "purchase.c9@m-mines.com")]
    assert mail[0]["url"].startswith("https://mail.google.com/")
