"""Human-facing ticket references: SD-2026-0142 (support), AR-2026-0031 (automation).

Sequential per kind per calendar year, counted from existing rows. Good enough for a ~74
person company; not race-proof under concurrent writes (no DB sequence/advisory lock — out of
scope for v1, see `## Not done`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Ticket

_PREFIX = {"support": "SD", "automation": "AR"}


def next_ref(db: Session, kind: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    year = now.year
    prefix = _PREFIX[kind]
    like = f"{prefix}-{year}-%"
    count = db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.ref.like(like))
    ).scalar_one()
    return f"{prefix}-{year}-{count + 1:04d}"
