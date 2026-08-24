"""Comment thread, with `is_internal` for IT-only notes (docs/07). Reading a private
ticket's thread is gated the same way the ticket detail is — docs/07: "restricts title, body
and comments to the requester, the assignee and the computed approver."
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..mmos_seam import CurrentUser, get_current_user
from ..models import Comment, Ticket
from ..privacy import can_see_full
from ..schemas import CommentCreate, CommentOut

router = APIRouter(tags=["comments"])


def _is_agent(user: CurrentUser) -> bool:
    # No `platform_admin` bypass -- see app/routers/tickets.py's twin of this function.
    return "agent" in user.roles or "admin" in user.roles


@router.post("/tickets/{ticket_id}/comments", response_model=CommentOut, status_code=201)
def create_comment(
    ticket_id: UUID, body: CommentCreate, db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if not can_see_full(ticket, user):
        raise HTTPException(status_code=403, detail={"error": "private_ticket"})
    if body.is_internal and not _is_agent(user):
        raise HTTPException(status_code=403, detail={"error": "role_required", "need": "agent"})

    comment = Comment(ticket_id=ticket.id, author_sub=user.sub, body=body.body, is_internal=body.is_internal)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/tickets/{ticket_id}/comments", response_model=list[CommentOut])
def list_comments(
    ticket_id: UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if not can_see_full(ticket, user):
        # A hidden row shows no comments at all — not even a count. docs/07: "restricts
        # title, body and comments" together.
        return []

    rows = db.scalars(
        select(Comment).where(Comment.ticket_id == ticket_id).order_by(Comment.created_at.asc())
    ).all()
    if _is_agent(user):
        return rows
    return [c for c in rows if not c.is_internal]
