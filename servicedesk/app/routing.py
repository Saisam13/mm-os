"""Approval routing — the explicit, editable department/category/priority matrix that the
Approval Routing tab manages, and the resolution order the brief asks for:

    an explicit rule (most specific first) overrides the manager-chain walk
    (app/org_chart.compute_approver); where none matches, fall back to the chain; where the
    chain also fails (NoApproverFound — today's actual failure: only 11 of 73 managers
    resolve), fall back to the single configured `ApprovalDefault`.

`resolve_approver` is the one function routers/tickets.py calls; it never raises — it
returns a `RoutingResult` with `source == "none"` only when no rule matches, the chain
fails, *and* no default has been configured yet (fresh install, nobody has visited the
Approval Routing tab). That is the one remaining way to get "no approver", and it is a
config gap the admin page makes fixable in one save, not a code path.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ApprovalDefault, ApprovalRule
from .org_chart import NoApproverFound, compute_approver


def _specificity(rule: ApprovalRule) -> int:
    return sum(1 for f in (rule.department, rule.category, rule.priority) if f is not None)


def find_matching_rules(db: Session, department: str, category: str | None, priority: str) -> list[ApprovalRule]:
    """All active rules whose non-null axes match this ticket, most specific first (ties
    broken by creation order, so the oldest matching rule of equal specificity wins —
    deterministic, and stable as new rules of the same specificity get added later)."""
    rows = db.scalars(select(ApprovalRule).where(ApprovalRule.is_active.is_(True))).all()
    matches = [
        r for r in rows
        if (r.department is None or r.department == department)
        and (r.category is None or r.category == category)
        and (r.priority is None or r.priority == priority)
    ]
    matches.sort(key=lambda r: (-_specificity(r), r.created_at))
    return matches


def best_rule(db: Session, department: str, category: str | None, priority: str) -> ApprovalRule | None:
    matches = find_matching_rules(db, department, category, priority)
    return matches[0] if matches else None


def get_default(db: Session) -> ApprovalDefault | None:
    return db.scalars(select(ApprovalDefault)).first()


@dataclass(frozen=True)
class RoutingResult:
    approver_sub: str | None
    approver_code: str | None
    source: str  # "rule" | "chain" | "default" | "none"
    rule_id: str | None = None
    rule_name: str | None = None
    approvers: list | None = None
    mode: str | None = None
    explanation: str = ""


def resolve_approver(
    db: Session, department: str, category: str | None, priority: str, requester_sub: str,
) -> RoutingResult:
    rule = best_rule(db, department, category, priority)
    if rule and rule.approvers:
        # A requester can never approve their own request (docs/07's rule, carried over
        # here too) — skip a listed approver who happens to be the requester and try the
        # next name in the rule before giving up on the rule entirely.
        for candidate in rule.approvers:
            sub = candidate.get("sub")
            if sub and sub != requester_sub:
                return RoutingResult(
                    approver_sub=sub, approver_code=candidate.get("employee_code"),
                    source="rule", rule_id=str(rule.id), rule_name=rule.name,
                    approvers=rule.approvers, mode=rule.mode,
                    explanation=f'matched rule "{rule.name}"',
                )

    try:
        node = compute_approver(requester_sub)
        return RoutingResult(
            approver_sub=node.sub, approver_code=node.employee_code, source="chain",
            explanation="no matching rule — resolved from the manager chain",
        )
    except NoApproverFound:
        pass

    default = get_default(db)
    if default and default.sub:
        return RoutingResult(
            approver_sub=default.sub, approver_code=default.employee_code, source="default",
            explanation="no matching rule, manager chain exhausted — used the default fallback approver",
        )

    return RoutingResult(
        approver_sub=None, approver_code=None, source="none",
        explanation="no matching rule, manager chain exhausted, and no default fallback approver is configured",
    )


def preview(
    db: Session, department: str, category: str | None, priority: str, requester_sub: str | None,
) -> dict:
    """Plain-language preview for the Approval Routing tab: "a request of this shape routes
    to X because Y" — without a preview, a matrix of rules is unauditable, per the brief."""
    rule = best_rule(db, department, category, priority)
    if rule and rule.approvers:
        names = ", ".join(a.get("employee_code", a.get("sub", "?")) for a in rule.approvers)
        mode_text = "in sequence" if rule.mode == "sequence" else "any one of"
        return {
            "source": "rule",
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "approvers": rule.approvers,
            "mode": rule.mode,
            "text": f'Rule "{rule.name}" applies: routes to {mode_text} [{names}].',
        }

    if requester_sub:
        result = resolve_approver(db, department, category, priority, requester_sub)
        if result.source == "chain":
            return {"source": "chain", "approver_code": result.approver_code, "sub": result.approver_sub,
                    "text": f"No rule matches. Falls back to the manager chain — resolves to {result.approver_code}."}
        if result.source == "default":
            return {"source": "default", "approver_code": result.approver_code, "sub": result.approver_sub,
                    "text": f"No rule matches and the manager chain is exhausted. Falls back to the default "
                             f"approver — {result.approver_code}."}
        return {"source": "none", "text": "No rule matches, the manager chain is exhausted, and no default "
                                            "fallback approver is configured — this request would have no approver."}

    default = get_default(db)
    default_text = f"the default approver ({default.employee_code})" if default else "no default approver — "\
        "none is configured yet"
    return {
        "source": "unresolved",
        "text": f"No rule matches this combination. Falls back to the requester's manager chain, then to {default_text}.",
    }
