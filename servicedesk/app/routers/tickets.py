"""Ticket lifecycle: create, the four views' list queries, detail, transition, assign.

Proposal, decision and comment endpoints live in their own router modules — each is the one
place that writes to its table, and each is where the corresponding piece of docs/07's rules
(required `alternatives`, immutable `snapshot`, `is_internal`) is enforced.
"""
from __future__ import annotations

from uuid import UUID

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..mmos_seam import CurrentUser, get_current_user, require_role
from ..models import Event, Ticket
from ..notifications import notify
from ..org_chart import get_person
from ..privacy import can_see_full
from ..refs import next_ref
from ..routing import resolve_approver
from ..schemas import AssignIn, EventOut, TicketCreate, TicketHiddenOut, TicketOut, TransitionIn
from ..sla import sla_status_for
from ..state_machine import apply_transition, invalid_transition

router = APIRouter(tags=["tickets"])

# (kind, from_status, to_status) -> who may call it through the generic /transition endpoint.
# `it_review -> proposal_ready` and every `manager_review -> *` decision are deliberately
# absent: those are only reachable through POST /proposals and POST /decisions, which apply
# docs/07's rules (a proposal gates it, a decision snapshots it) that this endpoint must not
# be able to bypass. apply_transition() still re-checks the full table regardless.
AGENT_ONLY = {
    ("automation", "submitted", "it_review"),
    ("automation", "proposal_ready", "manager_review"),
    ("automation", "it_review", "rejected"),
    ("automation", "approved", "in_build"),
    ("automation", "in_build", "deployed"),
    ("automation", "changes_requested", "it_review"),
    ("support", "open", "in_progress"),
    ("support", "in_progress", "waiting_on_requester"),
    ("support", "waiting_on_requester", "resolved"),
    ("support", "open", "rejected"),
}
REQUESTER_OR_AGENT = {
    ("automation", "deployed", "closed"),
    ("support", "resolved", "closed"),
    ("support", "closed", "resolved"),  # reopen, within the 7-day window
}
GENERIC_ALLOWED = AGENT_ONLY | REQUESTER_OR_AGENT


def _is_agent(user: CurrentUser) -> bool:
    # No `platform_admin` bypass -- see app/privacy.py's can_see_full() and
    # handoff/b1-assembly.md "A4-A5 auth seam" for why: access to the agent console is
    # granted through Service Desk's own roles, the same as private-ticket visibility.
    return "agent" in user.roles or "admin" in user.roles


def _serialize(ticket: Ticket, viewer: CurrentUser, db: Session | None = None):
    if can_see_full(ticket, viewer):
        out = TicketOut.model_validate(ticket)
        if db is not None:
            out = out.model_copy(update={"sla": sla_status_for(db, ticket)})
        return out
    return TicketHiddenOut.model_validate(ticket)


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(
    body: TicketCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    now = datetime.now(timezone.utc)
    initial_status = "submitted" if body.kind == "automation" else "open"
    ticket = Ticket(
        ref=next_ref(db, body.kind, now),
        kind=body.kind,
        title=body.title,
        body=body.body,
        requester_sub=user.sub,
        requester_code=user.employee_code,
        requester_dept=user.department,
        service_slug=body.service_slug,
        priority=body.priority,
        is_private=body.is_private,
        status=initial_status,
        created_at=now,
        updated_at=now,
    )
    if body.kind == "automation":
        # Approval Routing (app/routing.py): an explicit rule for this department/category/
        # priority overrides the manager-chain walk; no match falls back to the chain, and a
        # chain that raises NoApproverFound falls back to the single configured default
        # approver. Only returns no approver at all if none of the three is available yet.
        routing = resolve_approver(db, user.department, body.service_slug, body.priority, user.sub)
        if routing.approver_sub is None:
            raise HTTPException(status_code=422, detail={"error": "no_approver_available"})
        ticket.approver_sub = routing.approver_sub

    db.add(ticket)
    db.flush()
    # Not a transition through apply_transition() — there is no prior persisted state to
    # transition from (docs/07's diagram starts automation requests at `submitted`
    # directly; v1 never persists a `draft` row). Recorded as its own events row so "an
    # events row for each hop" still holds for the very first hop.
    db.add(Event(ticket_id=ticket.id, actor_sub=user.sub, from_status=None, to_status=initial_status, detail={"created": True}))
    db.commit()
    db.refresh(ticket)
    notify("submitted", user.email, ref=ticket.ref, title=ticket.title)
    return ticket


@router.get("/tickets/mine", response_model=list[TicketOut])
def list_mine(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    rows = db.scalars(
        select(Ticket).where(Ticket.requester_sub == user.sub).order_by(Ticket.created_at.desc())
    ).all()
    return rows


@router.get("/tickets/department")
def list_department(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    rows = db.scalars(
        select(Ticket).where(Ticket.requester_dept == user.department).order_by(Ticket.created_at.desc())
    ).all()
    return [_serialize(t, user, db) for t in rows]


@router.get("/tickets/queue", response_model=list[TicketOut])
def list_queue(db: Session = Depends(get_db), user: CurrentUser = Depends(require_role("agent"))):
    """Unassigned tickets (anyone on IT can pick these up) plus whatever this agent already
    holds. Always full detail: an unclaimed private ticket must still be triageable, and a
    ticket already claimed by this agent has them as the assignee — see app/privacy.py."""
    rows = db.scalars(
        select(Ticket)
        .where(Ticket.status.notin_(("closed", "rejected")))
        .where((Ticket.assignee_sub.is_(None)) | (Ticket.assignee_sub == user.sub))
        .order_by(Ticket.created_at.asc())
    ).all()
    return rows


@router.get("/tickets/approvals", response_model=list[TicketOut])
def list_approvals(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    rows = db.scalars(
        select(Ticket)
        .where(Ticket.approver_sub == user.sub, Ticket.status == "manager_review")
        .order_by(Ticket.created_at.desc())
    ).all()
    return rows


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _serialize(ticket, user, db)


@router.post("/tickets/{ticket_id}/assign", response_model=TicketOut)
def assign_ticket(
    ticket_id: UUID, body: AssignIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("agent")),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    ticket.assignee_sub = body.assignee_sub or user.sub
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/tickets/{ticket_id}/transition", response_model=TicketOut)
def transition_ticket(
    ticket_id: UUID, body: TransitionIn, db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    key = (ticket.kind, ticket.status, body.to_status)
    if key not in GENERIC_ALLOWED:
        raise invalid_transition(ticket.status, body.to_status)

    if key in AGENT_ONLY and not _is_agent(user):
        raise HTTPException(status_code=403, detail={"error": "role_required", "need": "agent", "have": user.roles})
    if key in REQUESTER_OR_AGENT and not (_is_agent(user) or user.sub == ticket.requester_sub):
        raise HTTPException(status_code=403, detail={"error": "requester_or_agent_required"})

    apply_transition(db, ticket, body.to_status, actor_sub=user.sub, detail=body.detail)
    db.commit()
    db.refresh(ticket)

    if body.to_status == "resolved":
        requester = get_person(ticket.requester_sub)
        notify("resolved", requester.email if requester else None, ref=ticket.ref, title=ticket.title)
    return ticket


@router.get("/tickets/{ticket_id}/events", response_model=list[EventOut])
def list_events(ticket_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Event history as a timeline (deliverable: ticket detail page). Gated the same way the
    ticket itself is — the append-only audit trail of a private ticket is not an exception to
    docs/07's three-person rule."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if not can_see_full(ticket, user):
        return []
    return db.scalars(
        select(Event).where(Event.ticket_id == ticket_id).order_by(Event.created_at.asc())
    ).all()
