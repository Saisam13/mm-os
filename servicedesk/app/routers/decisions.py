"""The manager decision — docs/07: "approved writes an immutable snapshot of exactly what
was approved ... so later scope growth is visible rather than assumed." `snapshot` is a
plain dict copy of the current proposal row, not a reference, so a later proposal revision
(a new version, `app/routers/proposals.py`) can never change what an already-decided
`decisions` row says was approved.

Only the computed approver (`ticket.approver_sub`, set at submit time — `app/org_chart.py`)
may decide. The requester-can-never-approve-themselves rule is already enforced when the
approver is computed, but this endpoint checks it again defensively: `approver_sub` is
data on the ticket, and a bug or a manually-edited row must not turn into a live
self-approval hole.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..mmos_seam import CurrentUser, get_current_user, require_permission
from ..models import Decision, Proposal, Ticket
from ..notifications import notify
from ..org_chart import get_person
from ..schemas import DecisionCreate, DecisionOut
from ..state_machine import apply_transition
from ..privacy import can_see_full

router = APIRouter(tags=["decisions"])


@router.post("/tickets/{ticket_id}/decisions", response_model=DecisionOut, status_code=201)
def decide(
    ticket_id: UUID, body: DecisionCreate, db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_permission("ticket.approve")),
):
    ticket = db.scalar(select(Ticket).where(Ticket.id == ticket_id).with_for_update().execution_options(populate_existing=True))
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if ticket.status != "manager_review":
        from ..state_machine import invalid_transition
        raise invalid_transition(ticket.status, body.decision)
    policy = ticket.approval_policy or {"mode": "sequence", "approvers": [{"sub": ticket.approver_sub}]}
    eligible = [a["sub"] for a in policy["approvers"] if a.get("sub") and a["sub"] != ticket.requester_sub]
    prior = list(ticket.approved_by or [])
    authorized = user.sub in eligible if policy["mode"] == "any_of" else ticket.approver_sub == user.sub
    if not authorized or user.sub in prior:
        raise HTTPException(status_code=403, detail={"error": "not_the_approver"})
    if user.sub == ticket.requester_sub:
        # Defensive — see module docstring. compute_approver() should never have produced
        # this, but a decision endpoint is exactly where a self-approval bug would surface.
        raise HTTPException(status_code=403, detail={"error": "cannot_approve_own_request"})

    proposal = db.scalars(
        select(Proposal).where(Proposal.ticket_id == ticket.id).order_by(Proposal.version.desc())
    ).first()

    snapshot = {
        "proposal_id": str(proposal.id) if proposal else None,
        "version": proposal.version if proposal else None,
        "scope_summary": proposal.scope_summary if proposal else None,
        "effort_days": float(proposal.effort_days) if proposal and proposal.effort_days is not None else None,
        "resources": dict(proposal.resources) if proposal else {},
        "risks": proposal.risks if proposal else None,
        "alternatives": proposal.alternatives if proposal else None,
    }

    decision = Decision(
        ticket_id=ticket.id,
        proposal_id=proposal.id if proposal else None,
        approver_sub=user.sub,
        approver_code=user.employee_code,
        decision=body.decision,
        comment=body.comment,
        snapshot=snapshot,
    )
    db.add(decision)

    if body.decision == "approved" and policy["mode"] == "sequence":
        prior.append(user.sub)
        ticket.approved_by = prior
        remaining = [sub for sub in eligible if sub not in prior]
        if remaining:
            from ..models import Event
            ticket.approver_sub = remaining[0]
            db.add(Event(ticket_id=ticket.id, actor_sub=user.sub, from_status=ticket.status,
                         to_status=ticket.status, detail={"approval_step": len(prior), "next_approver": remaining[0]}))
        else:
            apply_transition(db, ticket, body.decision, actor_sub=user.sub, detail={"decision": body.decision})
    else:
        if body.decision == "changes_requested":
            ticket.approved_by = []
            ticket.approver_sub = eligible[0] if eligible else None
        apply_transition(db, ticket, body.decision, actor_sub=user.sub, detail={"decision": body.decision})

    db.commit()
    db.refresh(decision)
    requester = get_person(ticket.requester_sub)
    notify(
        "decision", requester.email if requester else None, ref=ticket.ref, title=ticket.title,
        decision=body.decision, approver_code=user.employee_code, comment=body.comment,
    )
    return decision


@router.get("/tickets/{ticket_id}/decisions", response_model=list[DecisionOut])
def list_decisions(ticket_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(404, {"error": "not_found"})
    if not can_see_full(ticket, user):
        raise HTTPException(403, {"error": "private_ticket"})
    return db.scalars(select(Decision).where(Decision.ticket_id == ticket_id)).all()
