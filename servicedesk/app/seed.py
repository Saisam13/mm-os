"""Dev convenience: create the schema if it does not exist yet. Not a data seed — Service
Desk starts empty (docs/07 has no fixture data of its own; org-chart people are MM OS's, not
this service's). Run migrations with Alembic for anything beyond local dev/test — see
README.md.

The one deliberate exception, added in the scope change of 25 Aug 2026: Approval Routing
must never be empty, because a demo (or a real launch) with zero rules and zero default
approver is exactly the "no approver" failure mode the whole tab exists to fix. See
`ensure_default_approval_routing` below.

A second exception, added 25 Aug 2026 for the demo: the SLA tab must not render an empty
table either. See `ensure_default_sla_config` below.
"""
from __future__ import annotations

from .config import settings
from .db import SessionLocal, engine
from .models import ApprovalDefault, ApprovalRule, Base, Department, SlaConfig
from .org_chart import SEED_PERSONAS

DEFAULT_RULE_NAME = "Default — every automation request"

# The real MiniMines HR departments — the distinct `hr_department` values from
# backend/app/demo_seed.py's 23-person fixture (copied by hand, the same way
# app/org_chart.SEED_PERSONAS copies specific people from that file — Service Desk has no
# import path into MM OS's backend package, so this list is not derived at runtime).
REAL_DEPARTMENTS = (
    "N-Hub", "P-Hub", "Projects", "QA/QC", "Material Management",
    "Business Development", "P-Spoke", "StratOps", "Second Life",
)

# Sensible generic support-desk targets by ticket priority (minutes). Not MiniHelp's
# low/medium/high/critical — see models.SLA_PRIORITIES — these are Service Desk's own
# low/normal/high/urgent, the only values a ticket's `priority` column can actually hold.
DEFAULT_SLA_TARGETS = {
    "low": dict(response_time_minutes=480, resolution_time_minutes=2880),      # 8h / 48h
    "normal": dict(response_time_minutes=240, resolution_time_minutes=1440),   # 4h / 24h
    "high": dict(response_time_minutes=60, resolution_time_minutes=480),       # 1h / 8h
    "urgent": dict(response_time_minutes=15, resolution_time_minutes=120),     # 15m / 2h
}


def ensure_default_approval_routing() -> None:
    """Guarantees one catch-all `ApprovalRule` (department/category/priority all `NULL`, so
    it matches every automation request) and one `ApprovalDefault` row exist, seeded to the
    org-chart fixture's top-of-chain persona (Apex) — only in `ORG_CHART_MODE=seed`, which is
    what every demo and every test in this repo runs. In `http` mode there is no seed
    fixture to point a default at, so this is a no-op there and the admin sets the real one
    on the Approval Routing tab, same as every other piece of config on this page.

    Scope decision, 25 Aug 2026: "seed it with a single default approver rule that catches
    every automation request, and make sure the default can never be empty ... one working
    default plus the ability to add rules is exactly right for today." The owner is
    supplying the real approver list the next day — this is a placeholder to be replaced on
    the Approval Routing tab, not a permanent policy, and it is named accordingly so nobody
    mistakes it for one.

    Points at `MM-ITADMIN` (Service Desk's admin persona), not the old "apex" stub: it is
    the one seeded persona guaranteed to have no manager to escalate to and to always
    qualify (`is_approver` override), so it is the right last-resort backstop for every
    other persona's manager-chain walk — see app/org_chart.py.
    """
    if settings().org_chart_mode != "seed":
        return
    fallback = SEED_PERSONAS["MM-ITADMIN"]
    db = SessionLocal()
    try:
        has_catchall = (
            db.query(ApprovalRule)
            .filter(ApprovalRule.department.is_(None), ApprovalRule.category.is_(None), ApprovalRule.priority.is_(None))
            .first()
        )
        if has_catchall is None:
            db.add(ApprovalRule(
                name=DEFAULT_RULE_NAME, department=None, category=None, priority=None,
                approvers=[{"sub": fallback["sub"], "employee_code": fallback["employee_code"]}],
                mode="any_of", is_active=True,
            ))
        if db.query(ApprovalDefault).first() is None:
            db.add(ApprovalDefault(sub=fallback["sub"], employee_code=fallback["employee_code"]))
        db.commit()
    finally:
        db.close()


def ensure_default_sla_config() -> None:
    """Guarantees a `Department` row for each real MiniMines department and one `SlaConfig`
    row per department per ticket priority, so the Administration page's SLA tab shows a
    populated table on first load instead of an empty one — same demo-readiness rationale as
    `ensure_default_approval_routing` above. Idempotent: only inserts rows that do not exist
    yet, so re-running (or the admin editing a row afterwards) never clobbers a real edit.
    Runs regardless of `ORG_CHART_MODE` — these rows carry no seeded-persona `sub`, so there
    is nothing http-mode-unsafe about seeding them in production too.
    """
    db = SessionLocal()
    try:
        by_name = {d.name: d for d in db.query(Department).all()}
        for name in REAL_DEPARTMENTS:
            if name not in by_name:
                dept = Department(name=name)
                db.add(dept)
                db.flush()
                by_name[name] = dept
        db.commit()

        existing = {(c.department_id, c.priority) for c in db.query(SlaConfig).all()}
        for name in REAL_DEPARTMENTS:
            dept = by_name[name]
            for priority, targets in DEFAULT_SLA_TARGETS.items():
                if (dept.id, priority) not in existing:
                    db.add(SlaConfig(department_id=dept.id, priority=priority, **targets))
        db.commit()
    finally:
        db.close()


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_default_approval_routing()
    ensure_default_sla_config()
    print("servicedesk: schema ensured, default approval routing and SLA targets seeded")


if __name__ == "__main__":
    main()
