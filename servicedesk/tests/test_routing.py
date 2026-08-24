"""Approval routing precedence (app/routing.py): explicit rule beats the manager-chain walk,
chain beats the default fallback approver, and among rules the more specific one wins."""
from __future__ import annotations

import pytest

from app.models import ApprovalDefault, ApprovalRule
from app.org_chart import NoApproverFound, compute_approver
from app.routing import resolve_approver


def test_explicit_rule_overrides_the_manager_chain(db):
    # The chain for the operator resolves to the HOD (supervisor is "Operational", doesn't
    # qualify — see test_approver.py). An explicit rule naming the supervisor instead must
    # win regardless.
    rule = ApprovalRule(
        name="P-Spoke overrides", department="P-Spoke", category=None, priority=None,
        approvers=[{"sub": "user:sup-1", "employee_code": "MM05"}], mode="any_of",
    )
    db.add(rule)
    db.commit()

    result = resolve_approver(db, "P-Spoke", None, "normal", "user:op-1")
    assert result.source == "rule"
    assert result.approver_sub == "user:sup-1"
    assert result.approver_sub != compute_approver("user:op-1").sub


def test_no_matching_rule_falls_back_to_chain(db):
    rule = ApprovalRule(
        name="Different department", department="Some-Other-Dept", category=None, priority=None,
        approvers=[{"sub": "user:sup-1", "employee_code": "MM05"}], mode="any_of",
    )
    default = ApprovalDefault(sub="user:apex-1", employee_code="MM01")
    db.add_all([rule, default])
    db.commit()

    result = resolve_approver(db, "P-Spoke", None, "normal", "user:op-1")
    assert result.source == "chain"
    assert result.approver_sub == compute_approver("user:op-1").sub == "user:hod-1"


def test_chain_exhausted_falls_back_to_default(db):
    default = ApprovalDefault(sub="user:apex-1", employee_code="MM01")
    db.add(default)
    db.commit()

    # Apex has nobody above them — the chain genuinely has no qualifying approver.
    with pytest.raises(NoApproverFound):
        compute_approver("user:apex-1")

    result = resolve_approver(db, "Corporate", None, "normal", "user:apex-1")
    assert result.source == "default"
    assert result.approver_sub == "user:apex-1"


def test_no_rule_no_chain_no_default_returns_no_approver(db):
    result = resolve_approver(db, "Corporate", None, "normal", "user:apex-1")
    assert result.source == "none"
    assert result.approver_sub is None


def test_more_specific_rule_wins_over_a_wildcard_rule(db):
    wildcard = ApprovalRule(
        name="Company-wide default", department=None, category=None, priority=None,
        approvers=[{"sub": "user:apex-1", "employee_code": "MM01"}], mode="any_of",
    )
    specific = ApprovalRule(
        name="P-Spoke high priority", department="P-Spoke", category=None, priority="high",
        approvers=[{"sub": "user:hod-1", "employee_code": "MM02"}], mode="any_of",
    )
    db.add_all([wildcard, specific])
    db.commit()

    result = resolve_approver(db, "P-Spoke", None, "high", "user:op-1")
    assert result.source == "rule"
    assert result.rule_name == "P-Spoke high priority"
    assert result.approver_sub == "user:hod-1"

    # A priority that only the wildcard rule covers still resolves through it.
    other = resolve_approver(db, "P-Spoke", None, "urgent", "user:op-1")
    assert other.rule_name == "Company-wide default"


def test_rule_skips_requester_as_their_own_approver(db):
    rule = ApprovalRule(
        name="Self-approval guard", department="P-Spoke", category=None, priority=None,
        approvers=[{"sub": "user:op-1", "employee_code": "MM19"}, {"sub": "user:hod-1", "employee_code": "MM02"}],
        mode="sequence",
    )
    db.add(rule)
    db.commit()

    result = resolve_approver(db, "P-Spoke", None, "normal", "user:op-1")
    assert result.source == "rule"
    assert result.approver_sub == "user:hod-1"  # skipped the requester themselves
