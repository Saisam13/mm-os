"""SLA breach calculation — ported model, `sla_configs(department_id, priority,
response_time_minutes, resolution_time_minutes)`, from MiniHelp's `server/api/sla.php`
(unique on department+priority, upsert on save — see app/routers/admin.py).

A ticket's SLA target is looked up by joining its denormalised `requester_dept` text
against `Department.name` (Service Desk's own local department list, editable on the
Departments tab) and its `priority` column directly against `SlaConfig.priority`. There is
no config row until an admin sets one for that department/priority — `sla_status_for` then
returns `None`, and the ticket shows no SLA badge at all rather than a fabricated target.

Breach is "exceeds", read literally: elapsed strictly greater than the target minutes is a
breach; elapsed exactly equal to the target is not (see tests/test_sla.py's boundary case).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Department, SlaConfig, Ticket


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_target(db: Session, department: str, priority: str) -> SlaConfig | None:
    return db.scalar(
        select(SlaConfig)
        .join(Department, SlaConfig.department_id == Department.id)
        .where(Department.name == department, SlaConfig.priority == priority)
    )


def sla_status_for(db: Session, ticket: Ticket, now: datetime | None = None) -> dict | None:
    """`None` when no SLA target is configured for this ticket's department+priority —
    the caller (routers/tickets.py) omits the `sla` field entirely in that case rather than
    showing a breach flag that means nothing."""
    cfg = get_target(db, ticket.requester_dept, ticket.priority)
    if cfg is None:
        return None
    return sla_status(cfg, ticket.created_at, ticket.first_response_at, ticket.closed_at, now)


def sla_status(
    cfg: SlaConfig,
    created_at: datetime,
    first_response_at: datetime | None,
    closed_at: datetime | None,
    now: datetime | None = None,
) -> dict:
    """The pure calculation, split out from `sla_status_for` so the boundary case can be
    tested against contrived timestamps without a database round trip."""
    now = _aware(now or datetime.now(timezone.utc))
    created = _aware(created_at)

    response_pending = first_response_at is None
    response_elapsed = ((now if response_pending else _aware(first_response_at)) - created).total_seconds() / 60

    resolution_pending = closed_at is None
    resolution_elapsed = ((now if resolution_pending else _aware(closed_at)) - created).total_seconds() / 60

    response_breached = response_elapsed > cfg.response_time_minutes
    resolution_breached = resolution_elapsed > cfg.resolution_time_minutes

    return {
        "response_target_minutes": cfg.response_time_minutes,
        "resolution_target_minutes": cfg.resolution_time_minutes,
        "response_elapsed_minutes": round(response_elapsed, 1),
        "resolution_elapsed_minutes": round(resolution_elapsed, 1),
        "response_pending": response_pending,
        "resolution_pending": resolution_pending,
        "response_breached": response_breached,
        "resolution_breached": resolution_breached,
        "breached": response_breached or resolution_breached,
    }
