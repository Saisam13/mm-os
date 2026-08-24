"""Proves the SQLite harness in conftest.py works. ORCHESTRATOR-OWNED — do not edit.

If this fails, the harness is broken, not your feature.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app import models


def test_schema_creates_on_sqlite(db):
    names = set(models.Base.metadata.tables)
    assert {"employees", "users", "services", "grants", "sessions", "audit_log"} <= names


def test_uuid_primary_keys_round_trip(db, make_employee):
    emp = make_employee(full_name="Round Trip")
    found = db.scalar(select(models.Employee).where(models.Employee.id == emp.id))
    assert found is not None and found.full_name == "Round Trip"


def test_timestamps_come_back_utc_aware(db, make_employee):
    emp = make_employee()
    db.refresh(emp)
    assert emp.created_at.tzinfo is not None
    assert (datetime.now(timezone.utc) - emp.created_at).total_seconds() < 300


def test_jsonb_column_round_trips(db):
    row = models.AuditLog(action="harness.smoke", metadata_={"k": ["v", 1]})
    db.add(row)
    db.commit()
    back = db.scalar(select(models.AuditLog))
    assert back.metadata_ == {"k": ["v", 1]}


def test_healthz_reports_db_up(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["db"] == "up"


def test_signed_in_client_reaches_a_guarded_route(client, make_user, sign_in):
    user = make_user()
    sign_in(user)
    r = client.get("/api/me")
    # A1 has not written /api/me yet; 404 is fine, 401 would mean the cookie did not stick.
    assert r.status_code != 401, r.text


def test_grant_factory_and_user_grants_relationship(db, make_user, make_service, make_grant):
    user = make_user()
    service, roles = make_service()
    make_grant(user, service, roles["admin"])
    db.refresh(user)
    assert len(user.grants) == 1
    assert user.grants[0].role.key == "admin"


def test_isolation_between_tests(db):
    assert db.scalar(select(models.Employee)) is None
