"""Both state machines, enforced in code — docs/07-service-desk.md's diagrams, transcribed
into transition tables. An illegal transition is a 409, never a UI decision.

## Reading the automation diagram

```
draft
  └▶ submitted ──▶ it_review ──▶ proposal_ready ──▶ manager_review ──┬▶ approved ──▶ in_build ──▶ deployed ──▶ closed
                       │              ▲                             ├▶ changes_requested ──┐
                       │              └─────────────────────────────┘                      │
                       └▶ rejected (IT: not feasible)                └▶ rejected (manager: not funded)
```

Two branch points are genuinely ambiguous as ASCII and are resolved here as a documented
judgement call (`## Assumptions` in the handoff), not a re-specification of docs/07:

- `changes_requested` loops back to `it_review` (so IT can revise the proposal — a new,
  versioned proposal — rather than to `proposal_ready`, which would imply a manager decision
  needs no fresh IT input).
- `manager_review` has exactly three direct outcomes — `approved`, `changes_requested`,
  `rejected` (manager: not funded) — rather than `rejected` hanging off `changes_requested`.

Everything else is drawn unambiguously and transcribed as-is, including which two states can
short-circuit to `rejected` (`it_review`, not `submitted` — the rejection reason
"not feasible" is an IT-review outcome).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Event, Ticket

SUPPORT_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "rejected"},
    "in_progress": {"waiting_on_requester"},
    "waiting_on_requester": {"resolved"},
    "resolved": {"closed"},
    "closed": {"resolved"},  # reopen, gated by the 7-day window below
    "rejected": set(),
}

REOPEN_WINDOW = timedelta(days=7)

AUTOMATION_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted"},
    "submitted": {"it_review"},
    "it_review": {"proposal_ready", "rejected"},
    "proposal_ready": {"manager_review"},
    "manager_review": {"approved", "changes_requested", "rejected"},
    "changes_requested": {"it_review"},
    "approved": {"in_build"},
    "in_build": {"deployed"},
    "deployed": {"closed"},
    "rejected": set(),
    "closed": set(),
}

TRANSITIONS = {"support": SUPPORT_TRANSITIONS, "automation": AUTOMATION_TRANSITIONS}


def invalid_transition(current: str, attempted: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": "invalid_transition", "from": current, "to": attempted},
    )


def apply_transition(
    db: Session,
    ticket: Ticket,
    to_status: str,
    actor_sub: str | None,
    detail: dict | None = None,
    *,
    now: datetime | None = None,
) -> Ticket:
    """Validate `ticket.status -> to_status` against the table for `ticket.kind`, apply it,
    and write the append-only events row. Raises the 409 the acceptance test checks for."""
    now = now or datetime.now(timezone.utc)
    table = TRANSITIONS[ticket.kind]
    allowed = table.get(ticket.status, set())
    if to_status not in allowed:
        raise invalid_transition(ticket.status, to_status)

    if ticket.kind == "support" and ticket.status == "closed" and to_status == "resolved":
        if ticket.closed_at is None or now - _aware(ticket.closed_at) > REOPEN_WINDOW:
            raise HTTPException(
                status_code=409,
                detail={"error": "reopen_window_expired", "from": ticket.status, "to": to_status},
            )

    from_status = ticket.status
    ticket.status = to_status
    ticket.updated_at = now
    if ticket.first_response_at is None:
        # SLA response-time target (see app/sla.py): the first time anyone moves the ticket
        # at all after creation counts as "responded to" — creation itself goes through
        # routers/tickets.py directly, never through apply_transition(), so this is genuinely
        # the first hop, whichever transition it turns out to be for the ticket's kind.
        ticket.first_response_at = now
    if to_status == "closed":
        ticket.closed_at = now
    if from_status == "closed" and to_status == "resolved":
        ticket.closed_at = None  # reopened — no longer closed

    db.add(Event(
        ticket_id=ticket.id, actor_sub=actor_sub, from_status=from_status, to_status=to_status,
        detail=detail or {},
    ))
    db.flush()
    return ticket


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
