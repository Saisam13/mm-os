"""Dev convenience: create the schema if it does not exist yet. Not a data seed — Service
Desk starts empty (docs/07 has no fixture data of its own; org-chart people are MM OS's, not
this service's). Run migrations with Alembic for anything beyond local dev/test — see
README.md.

The one deliberate exception, added in the scope change of 25 Aug 2026: Approval Routing
must never be empty, because a demo (or a real launch) with zero rules and zero default
approver is exactly the "no approver" failure mode the whole tab exists to fix. See
`ensure_default_approval_routing` below.
"""
from __future__ import annotations

from .config import settings
from .db import SessionLocal, engine
from .models import ApprovalDefault, ApprovalRule, Base
from .org_chart import SEED_PERSONAS

DEFAULT_RULE_NAME = "Default — every automation request"


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
    """
    if settings().org_chart_mode != "seed":
        return
    apex = SEED_PERSONAS["apex"]
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
                approvers=[{"sub": apex["sub"], "employee_code": apex["employee_code"]}],
                mode="any_of", is_active=True,
            ))
        if db.query(ApprovalDefault).first() is None:
            db.add(ApprovalDefault(sub=apex["sub"], employee_code=apex["employee_code"]))
        db.commit()
    finally:
        db.close()


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_default_approval_routing()
    print("servicedesk: schema ensured, default approval routing seeded")


if __name__ == "__main__":
    main()
