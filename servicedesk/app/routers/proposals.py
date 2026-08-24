"""IT's proposal — docs/07 "where resource allocation becomes real". Versioned: creating one
always adds a new version and never edits a prior row (decisions.snapshot depends on that
immutability). Creating the *first* proposal on a ticket still in `it_review` is also what
carries the ticket to `proposal_ready` — the only door from `it_review` to `manager_review`.

A proposal only makes sense once a ticket has actually entered `it_review` (an agent has
picked it up out of the raw `submitted` queue) — creating one against a `submitted` ticket
used to be silently accepted and stored with no state change at all, leaving the requester's
ticket stuck at `submitted` and the agent seeing nothing happen. Fixed by rejecting with a
409 naming the required state, rather than silently advancing past the triage step or
leaving a proposal attached to a ticket nobody agreed was ready for one: a ticket can also be
in `it_review` after a `changes_requested` loop-back, so this same check also covers a
revised (v2+) proposal, not just the first.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..mmos_seam import CurrentUser, get_current_user, require_role
from ..models import Proposal, Ticket
from ..notifications import notify
from ..org_chart import get_person
from ..privacy import can_see_full
from ..schemas import ProposalCreate, ProposalOut
from ..state_machine import apply_transition

router = APIRouter(tags=["proposals"])


@router.post("/tickets/{ticket_id}/proposals", response_model=ProposalOut, status_code=201)
def create_proposal(
    ticket_id: UUID, body: ProposalCreate, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("agent")),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if ticket.kind != "automation":
        raise HTTPException(status_code=409, detail={"error": "not_an_automation_request"})
    if ticket.status != "it_review":
        raise HTTPException(
            status_code=409,
            detail={"error": "wrong_status", "required": "it_review", "current": ticket.status},
        )

    next_version = (
        db.execute(select(func.max(Proposal.version)).where(Proposal.ticket_id == ticket.id)).scalar_one()
        or 0
    ) + 1
    proposal = Proposal(
        ticket_id=ticket.id,
        author_sub=user.sub,
        scope_summary=body.scope_summary,
        effort_days=body.effort_days,
        resources=body.resources,
        risks=body.risks,
        alternatives=body.alternatives,
        version=next_version,
    )
    db.add(proposal)

    # Guarded above: ticket.status is always "it_review" here, so this always carries the
    # ticket forward to proposal_ready — first proposal or a revision after
    # changes_requested looped back to it_review, either way.
    apply_transition(db, ticket, "proposal_ready", actor_sub=user.sub, detail={"proposal_version": next_version})

    db.commit()
    db.refresh(proposal)

    requester = get_person(ticket.requester_sub)
    notify("proposal_ready", requester.email if requester else None, ref=ticket.ref, title=ticket.title)

    return proposal


@router.get("/tickets/{ticket_id}/proposals", response_model=list[ProposalOut])
def list_proposals(
    ticket_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if not can_see_full(ticket, user):
        raise HTTPException(status_code=403, detail={"error": "private_ticket"})
    return db.scalars(
        select(Proposal).where(Proposal.ticket_id == ticket_id).order_by(Proposal.version.asc())
    ).all()
