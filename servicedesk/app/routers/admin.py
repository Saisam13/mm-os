"""The Administration page: Departments, Users & Roles, SLA Config, Approval Routing.

Every route in this router requires Service Desk's own `admin` role
(`require_role("admin")`, app/mmos_seam.py) — this page edits who can approve spending and
access, so it is never left open just because it is "settings". There is no read/write split:
even the GET endpoints here are admin-only, since none of the other three views need this
page's config directly (SLA status is folded into ticket serialization in routers/tickets.py
for whoever can already see the ticket, not exposed here).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..mmos_seam import CurrentUser, require_role
from ..models import ApprovalDefault, ApprovalRule, Department, LocalRole, SlaConfig
from ..org_chart import list_known_people
from ..routing import preview as routing_preview
from ..schemas import (
    ApprovalDefaultIn, ApprovalDefaultOut, ApprovalRuleIn, ApprovalRuleOut,
    DepartmentCreate, DepartmentOut, DepartmentUpdate, LocalRoleIn, LocalRoleOut,
    PersonOut, RoutingPreviewIn, SlaConfigIn, SlaConfigOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_admin = require_role("admin")


# ── Departments ─────────────────────────────────────────────────────────────

@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    return db.scalars(select(Department).order_by(Department.name)).all()


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(body: DepartmentCreate, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    if db.scalar(select(Department).where(Department.name == body.name)):
        raise HTTPException(status_code=409, detail={"error": "department_exists", "name": body.name})
    dept = Department(name=body.name, code=body.code)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


@router.patch("/departments/{dept_id}", response_model=DepartmentOut)
def update_department(
    dept_id: UUID, body: DepartmentUpdate, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin),
):
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if body.name is not None:
        dept.name = body.name
    if body.code is not None:
        dept.code = body.code
    if body.is_active is not None:
        dept.is_active = body.is_active
    db.commit()
    db.refresh(dept)
    return dept


# ── Users & Roles ────────────────────────────────────────────────────────────

@router.get("/people", response_model=list[PersonOut])
def list_people(_: CurrentUser = Depends(_admin)):
    """Read-only identity directory for the "grant a role" picker — see
    app.org_chart.list_known_people. Empty in `ORG_CHART_MODE=http` until the directory
    endpoint it needs exists (same contract gap app/org_chart.py already flags)."""
    return [
        PersonOut(sub=p.sub, employee_code=p.employee_code, full_name=p.full_name, department=p.department)
        for p in list_known_people()
    ]


@router.get("/roles", response_model=list[LocalRoleOut])
def list_roles(db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    return db.scalars(select(LocalRole).order_by(LocalRole.employee_code)).all()


@router.put("/roles/{sub}", response_model=LocalRoleOut)
def upsert_role(sub: str, body: LocalRoleIn, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    row = db.scalar(select(LocalRole).where(LocalRole.sub == sub))
    if row is None:
        row = LocalRole(sub=sub, employee_code=body.employee_code)
        db.add(row)
    # Identity fields are captured once, at grant time, from the read-only org-chart
    # directory — not re-editable through this endpoint's flags-only intent, but harmless to
    # refresh from what was just picked in case the admin re-grants after a name change.
    row.employee_code = body.employee_code
    row.full_name = body.full_name
    row.department = body.department
    row.is_agent = body.is_agent
    row.is_department_manager = body.is_department_manager
    row.is_approver = body.is_approver
    db.commit()
    db.refresh(row)
    return row


@router.delete("/roles/{sub}", status_code=204)
def delete_role(sub: str, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    row = db.scalar(select(LocalRole).where(LocalRole.sub == sub))
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    db.delete(row)
    db.commit()


# ── SLA Config ───────────────────────────────────────────────────────────────

def _sla_out(cfg: SlaConfig) -> SlaConfigOut:
    return SlaConfigOut(
        id=cfg.id, department_id=cfg.department_id, department_name=cfg.department.name,
        priority=cfg.priority, response_time_minutes=cfg.response_time_minutes,
        resolution_time_minutes=cfg.resolution_time_minutes, updated_at=cfg.updated_at,
    )


@router.get("/sla", response_model=list[SlaConfigOut])
def list_sla(db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    rows = db.scalars(
        select(SlaConfig).join(Department).order_by(Department.name, SlaConfig.priority)
    ).all()
    return [_sla_out(r) for r in rows]


@router.put("/sla", response_model=SlaConfigOut)
def upsert_sla(body: SlaConfigIn, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    """Upsert on (department_id, priority) — replaces the existing row rather than
    duplicating it, per MiniHelp's `ON DUPLICATE KEY UPDATE` (server/api/sla.php)."""
    dept = db.get(Department, body.department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail={"error": "department_not_found"})
    row = db.scalar(
        select(SlaConfig).where(SlaConfig.department_id == body.department_id, SlaConfig.priority == body.priority)
    )
    if row is None:
        row = SlaConfig(department_id=body.department_id, priority=body.priority)
        db.add(row)
    row.response_time_minutes = body.response_time_minutes
    row.resolution_time_minutes = body.resolution_time_minutes
    db.commit()
    db.refresh(row)
    return _sla_out(row)


# ── Approval Routing ─────────────────────────────────────────────────────────

def _specificity(rule: ApprovalRule) -> int:
    return sum(1 for f in (rule.department, rule.category, rule.priority) if f is not None)


def _rule_out(rule: ApprovalRule) -> ApprovalRuleOut:
    return ApprovalRuleOut(
        id=rule.id, name=rule.name, department=rule.department, category=rule.category,
        priority=rule.priority, approvers=rule.approvers, mode=rule.mode, is_active=rule.is_active,
        specificity=_specificity(rule), created_at=rule.created_at, updated_at=rule.updated_at,
    )


@router.get("/approval-rules", response_model=list[ApprovalRuleOut])
def list_approval_rules(db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    rows = db.scalars(select(ApprovalRule)).all()
    rows = sorted(rows, key=lambda r: (-_specificity(r), r.created_at))
    return [_rule_out(r) for r in rows]


@router.post("/approval-rules", response_model=ApprovalRuleOut, status_code=201)
def create_approval_rule(body: ApprovalRuleIn, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    rule = ApprovalRule(
        name=body.name, department=body.department, category=body.category, priority=body.priority,
        approvers=[a.model_dump() for a in body.approvers], mode=body.mode, is_active=body.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.patch("/approval-rules/{rule_id}", response_model=ApprovalRuleOut)
def update_approval_rule(
    rule_id: UUID, body: ApprovalRuleIn, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin),
):
    rule = db.get(ApprovalRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    rule.name = body.name
    rule.department = body.department
    rule.category = body.category
    rule.priority = body.priority
    rule.approvers = [a.model_dump() for a in body.approvers]
    rule.mode = body.mode
    rule.is_active = body.is_active
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.delete("/approval-rules/{rule_id}", status_code=204)
def delete_approval_rule(rule_id: UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    rule = db.get(ApprovalRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    db.delete(rule)
    db.commit()


@router.get("/approval-default", response_model=ApprovalDefaultOut | None)
def get_approval_default(db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    row = db.scalars(select(ApprovalDefault)).first()
    return row


@router.put("/approval-default", response_model=ApprovalDefaultOut)
def set_approval_default(body: ApprovalDefaultIn, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    row = db.scalars(select(ApprovalDefault)).first()
    if row is None:
        row = ApprovalDefault(sub=body.sub, employee_code=body.employee_code)
        db.add(row)
    else:
        row.sub = body.sub
        row.employee_code = body.employee_code
    db.commit()
    db.refresh(row)
    return row


@router.post("/approval-preview")
def preview_routing(body: RoutingPreviewIn, db: Session = Depends(get_db), _: CurrentUser = Depends(_admin)):
    return routing_preview(db, body.department, body.category, body.priority, body.requester_sub)
