"""The one place the department-queue privacy rule (docs/07 "Who can see what") is decided.

Enforced here, in the query/serialization layer that every router calls through — never in
the frontend. A hidden row is built from a Pydantic model (`TicketHiddenOut`) that has no
`title`/`body` field at all, so there is nothing for a network-tab inspection to find.
"""
from __future__ import annotations

from .mmos_seam import CurrentUser
from .models import Ticket

THREE_PERSON = ("requester_sub", "assignee_sub", "approver_sub")


def can_see_full(ticket: Ticket, viewer: CurrentUser) -> bool:
    if not ticket.is_private:
        return True
    # Service Desk admins act as oversight for reassignment etc. (docs/07 roles table) — not
    # one of the literal three names but a deliberate carve-out. See `## Assumptions`.
    # `viewer.platform_admin` deliberately does NOT bypass this (B1, seam inventory section
    # A.3): the locked decision is that a platform admin must not silently gain private
    # ticket bodies just by being MM OS's platform admin -- Service Desk's own "admin" role,
    # granted like any other grant, is what carries oversight here.
    if "admin" in viewer.roles:
        return True
    if viewer.sub in {getattr(ticket, f) for f in THREE_PERSON if getattr(ticket, f)}:
        return True
    # Before anyone has claimed it, IT-wide triage needs to read it to triage it at all — a
    # private ticket with no assignee cannot otherwise ever reach it_review. Once claimed,
    # the strict three-person rule applies even to other agents. See `## Assumptions`.
    if ticket.assignee_sub is None and "agent" in viewer.roles:
        return True
    return False
