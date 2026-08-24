"""SLA breach calculation (app/sla.py) — the boundary case, and the upsert-not-duplicate
behaviour of the ported `sla_configs(department_id, priority, ...)` model."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Department, SlaConfig
from app.sla import sla_status
from .conftest import auth, token_for


def _cfg(response_minutes=60, resolution_minutes=240):
    return SlaConfig(response_time_minutes=response_minutes, resolution_time_minutes=resolution_minutes)


def test_boundary_exact_target_is_not_breached():
    cfg = _cfg(response_minutes=60, resolution_minutes=240)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_response = created + timedelta(minutes=60)  # exactly the target
    closed = created + timedelta(minutes=240)  # exactly the target
    status = sla_status(cfg, created, first_response, closed, now=closed)
    assert status["response_breached"] is False
    assert status["resolution_breached"] is False
    assert status["breached"] is False


def test_boundary_one_minute_over_is_breached():
    cfg = _cfg(response_minutes=60, resolution_minutes=240)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_response = created + timedelta(minutes=61)
    closed = created + timedelta(minutes=241)
    status = sla_status(cfg, created, first_response, closed, now=closed)
    assert status["response_breached"] is True
    assert status["resolution_breached"] is True
    assert status["breached"] is True


def test_pending_ticket_breaches_on_elapsed_time_alone():
    """No response yet, no resolution yet — still breached once elapsed time alone exceeds
    the target, using `now` in place of the missing timestamp."""
    cfg = _cfg(response_minutes=30, resolution_minutes=120)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = created + timedelta(minutes=31)
    status = sla_status(cfg, created, None, None, now=now)
    assert status["response_pending"] is True
    assert status["response_breached"] is True
    assert status["resolution_pending"] is True
    assert status["resolution_breached"] is False  # 31 min elapsed, 120 min target


def test_upsert_replaces_rather_than_duplicates(client, db):
    dept = Department(name="P-Spoke")
    db.add(dept)
    db.commit()
    admin_tok = token_for("MM-ITADMIN", roles=["admin"])

    r1 = client.put("/api/admin/sla", json={
        "department_id": str(dept.id), "priority": "high",
        "response_time_minutes": 60, "resolution_time_minutes": 480,
    }, headers=auth(admin_tok))
    assert r1.status_code == 200, r1.text

    r2 = client.put("/api/admin/sla", json={
        "department_id": str(dept.id), "priority": "high",
        "response_time_minutes": 30, "resolution_time_minutes": 240,
    }, headers=auth(admin_tok))
    assert r2.status_code == 200, r2.text
    assert r2.json()["response_time_minutes"] == 30

    rows = client.get("/api/admin/sla", headers=auth(admin_tok)).json()
    matching = [row for row in rows if row["department_id"] == str(dept.id) and row["priority"] == "high"]
    assert len(matching) == 1, "upsert must replace the existing row, not add a second one"
    assert matching[0]["response_time_minutes"] == 30


def test_seed_populates_real_departments_with_every_real_priority(db):
    """The SLA tab used to render an empty table on a fresh install — nothing seeded any
    `Department` or `SlaConfig` rows. `ensure_default_sla_config` (app/seed.py) fixes that,
    and must use ticket priorities a ticket can actually have (`low`/`normal`/`high`/
    `urgent` — `models.TICKET_PRIORITIES`), not MiniHelp's original `low/medium/high/
    critical`, which would never match a real ticket's `priority` column."""
    from app.models import TICKET_PRIORITIES
    from app.seed import REAL_DEPARTMENTS, ensure_default_sla_config

    assert db.query(Department).count() == 0
    assert db.query(SlaConfig).count() == 0

    ensure_default_sla_config()

    depts = {d.name: d for d in db.query(Department).all()}
    assert set(REAL_DEPARTMENTS) <= set(depts)

    configs = db.query(SlaConfig).all()
    assert len(configs) == len(REAL_DEPARTMENTS) * len(TICKET_PRIORITIES)
    seen_priorities = {c.priority for c in configs}
    assert seen_priorities == set(TICKET_PRIORITIES)
    for cfg in configs:
        assert cfg.response_time_minutes > 0
        assert cfg.resolution_time_minutes > 0

    # Idempotent: calling it again (e.g. every app startup) must not duplicate rows, and
    # must not clobber an admin's later edit to one of them.
    one = db.query(SlaConfig).filter(SlaConfig.priority == "urgent").first()
    one.response_time_minutes = 999
    db.commit()

    ensure_default_sla_config()
    assert db.query(Department).count() == len(REAL_DEPARTMENTS)
    assert db.query(SlaConfig).count() == len(REAL_DEPARTMENTS) * len(TICKET_PRIORITIES)
    refreshed = db.get(SlaConfig, one.id)
    assert refreshed.response_time_minutes == 999
