"""Pydantic request/response shapes for the `/api` surface. Two response shapes for a ticket
row are deliberate, not an oversight: `TicketOut` (full) and `TicketHiddenOut` (private-row
stand-in) do not share a base class that carries `title`/`body`, so a hidden row cannot leak
them by a serialization accident — see docs/07's "filter in the query, not in the browser."
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TicketCreate(BaseModel):
    kind: Literal["support", "automation"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    is_private: bool = False
    service_slug: str | None = None

    @field_validator("title", "body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class TicketOut(BaseModel):
    id: UUID
    ref: str
    kind: str
    title: str
    body: str
    requester_sub: str
    requester_code: str
    requester_dept: str
    service_slug: str | None
    priority: str
    is_private: bool
    status: str
    assignee_sub: str | None
    approver_sub: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    sla: dict | None = None  # app/sla.py — attached by routers/tickets.py, not a Ticket column

    model_config = {"from_attributes": True}


class TicketHiddenOut(BaseModel):
    """What a department-queue viewer who is not the requester/assignee/approver receives
    for a private ticket: enough to keep the count and the wait time honest, nothing else."""

    id: UUID
    ref: str
    kind: str
    status: str
    assignee_sub: str | None
    created_at: datetime
    is_private: Literal[True] = True
    hidden: Literal[True] = True

    model_config = {"from_attributes": True}


class TransitionIn(BaseModel):
    to_status: str
    detail: dict = Field(default_factory=dict)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)
    is_internal: bool = False


class CommentOut(BaseModel):
    id: UUID
    ticket_id: UUID
    author_sub: str
    body: str
    is_internal: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ProposalCreate(BaseModel):
    scope_summary: str = Field(min_length=1)
    effort_days: float | None = None
    resources: dict = Field(default_factory=dict)
    risks: str | None = None
    alternatives: str = Field(min_length=1)  # required — docs/07: the cheapest stop-gap

    @field_validator("alternatives")
    @classmethod
    def _alternatives_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("alternatives is required")
        return v


class ProposalOut(BaseModel):
    id: UUID
    ticket_id: UUID
    author_sub: str
    scope_summary: str
    effort_days: float | None
    resources: dict
    risks: str | None
    alternatives: str
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionCreate(BaseModel):
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: str | None = None


class DecisionOut(BaseModel):
    id: UUID
    ticket_id: UUID
    proposal_id: UUID | None
    approver_sub: str
    approver_code: str
    decision: str
    comment: str | None
    snapshot: dict
    decided_at: datetime

    model_config = {"from_attributes": True}


class EventOut(BaseModel):
    id: UUID
    ticket_id: UUID
    actor_sub: str | None
    from_status: str | None
    to_status: str | None
    detail: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class AssignIn(BaseModel):
    assignee_sub: str | None = None  # None = claim it for the calling agent


class BadgeOut(BaseModel):
    open: int
    approvals_waiting: int


# ── Administration page ─────────────────────────────────────────────────────

class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str | None = Field(default=None, max_length=16)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = None
    is_active: bool | None = None


class DepartmentOut(BaseModel):
    id: UUID
    name: str
    code: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonOut(BaseModel):
    """A row from the org-chart directory (`app.org_chart.list_known_people`) — read-only
    identity, never persisted by this page."""
    sub: str
    employee_code: str
    full_name: str
    department: str


class LocalRoleIn(BaseModel):
    employee_code: str = Field(min_length=1, max_length=16)
    full_name: str | None = None
    department: str | None = None
    is_agent: bool = False
    is_department_manager: bool = False
    is_approver: bool = False


class LocalRoleOut(BaseModel):
    id: UUID
    sub: str
    employee_code: str
    full_name: str | None
    department: str | None
    is_agent: bool
    is_department_manager: bool
    is_approver: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SlaConfigIn(BaseModel):
    department_id: UUID
    priority: Literal["low", "normal", "high", "urgent"]
    response_time_minutes: int = Field(gt=0)
    resolution_time_minutes: int = Field(gt=0)


class SlaConfigOut(BaseModel):
    id: UUID
    department_id: UUID
    department_name: str
    priority: str
    response_time_minutes: int
    resolution_time_minutes: int
    updated_at: datetime


class ApproverRef(BaseModel):
    sub: str
    employee_code: str


class ApprovalRuleIn(BaseModel):
    name: str = Field(min_length=1)
    department: str | None = None
    category: str | None = None
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    approvers: list[ApproverRef] = Field(min_length=1)
    mode: Literal["sequence", "any_of"] = "any_of"
    is_active: bool = True


class ApprovalRuleOut(BaseModel):
    id: UUID
    name: str
    department: str | None
    category: str | None
    priority: str | None
    approvers: list[dict]
    mode: str
    is_active: bool
    specificity: int
    created_at: datetime
    updated_at: datetime


class ApprovalDefaultIn(BaseModel):
    sub: str = Field(min_length=1)
    employee_code: str = Field(min_length=1, max_length=16)


class ApprovalDefaultOut(BaseModel):
    sub: str
    employee_code: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoutingPreviewIn(BaseModel):
    department: str
    category: str | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    requester_sub: str | None = None
