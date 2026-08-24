"""Approval routing precedence (app/routing.py): explicit rule beats the manager-chain walk,
chain beats the default fallback approver, and among rules the more specific one wins.

Uses the real seeded personas (app/org_chart.SEED_PERSONAS): MM88's manager chain resolves
to MM81; MM33 and MM81 themselves have no manager in the fixture, so their chains are
exhausted and fall back to the configured default (MM-ITADMIN in the real seed, but these
tests configure their own ApprovalDefault rows to keep each test self-contained).
"""
from __future__ import annotations

import pytest

from app.models import ApprovalDefault, ApprovalRule
from app.org_chart import NoApproverFound, compute_approver
from app.routing import resolve_approver


def test_explicit_rule_overrides_the_manager_chain(db):
    # The chain for MM88 resolves to MM81, their real manager. An explicit rule naming MM05
    # instead must win regardless.
    rule = ApprovalRule(
        name="Projects overrides", department="Projects", category=None, priority=None,
        approvers=[{"sub": "user:MM05", "employee_code": "MM05"}], mode="any_of",
    )
    db.add(rule)
    db.commit()

    result = resolve_approver(db, "Projects", None, "normal", "user:MM88")
    assert result.source == "rule"
    assert result.approver_sub == "user:MM05"
    assert result.approver_sub != compute_approver("user:MM88").sub


def test_no_matching_rule_falls_back_to_chain(db):
    rule = ApprovalRule(
        name="Different department", department="Some-Other-Dept", category=None, priority=None,
        approvers=[{"sub": "user:MM05", "employee_code": "MM05"}], mode="any_of",
    )
    default = ApprovalDefault(sub="user:MM-ITADMIN", employee_code="MM-ITADMIN")
    db.add_all([rule, default])
    db.commit()

    result = resolve_approver(db, "Projects", None, "normal", "user:MM88")
    assert result.source == "chain"
    assert result.approver_sub == compute_approver("user:MM88").sub == "user:MM81"


def test_chain_exhausted_falls_back_to_default(db):
    default = ApprovalDefault(sub="user:MM-ITADMIN", employee_code="MM-ITADMIN")
    db.add(default)
    db.commit()

    # MM33 has nobody above them in the fixture — the chain genuinely has no qualifying
    # approver.
    with pytest.raises(NoApproverFound):
        compute_approver("user:MM33")

    result = resolve_approver(db, "StratOps", None, "normal", "user:MM33")
    assert result.source == "default"
    assert result.approver_sub == "user:MM-ITADMIN"


def test_no_rule_no_chain_no_default_returns_no_approver(db):
    result = resolve_approver(db, "StratOps", None, "normal", "user:MM33")
    assert result.source == "none"
    assert result.approver_sub is None


def test_more_specific_rule_wins_over_a_wildcard_rule(db):
    wildcard = ApprovalRule(
        name="Company-wide default", department=None, category=None, priority=None,
        approvers=[{"sub": "user:MM-ITADMIN", "employee_code": "MM-ITADMIN"}], mode="any_of",
    )
    specific = ApprovalRule(
        name="Projects high priority", department="Projects", category=None, priority="high",
        approvers=[{"sub": "user:MM81", "employee_code": "MM81"}], mode="any_of",
    )
    db.add_all([wildcard, specific])
    db.commit()

    result = resolve_approver(db, "Projects", None, "high", "user:MM88")
    assert result.source == "rule"
    assert result.rule_name == "Projects high priority"
    assert result.approver_sub == "user:MM81"

    # A priority that only the wildcard rule covers still resolves through it.
    other = resolve_approver(db, "Projects", None, "urgent", "user:MM88")
    assert other.rule_name == "Company-wide default"


def test_rule_skips_requester_as_their_own_approver(db):
    rule = ApprovalRule(
        name="Self-approval guard", department="Projects", category=None, priority=None,
        approvers=[{"sub": "user:MM88", "employee_code": "MM88"}, {"sub": "user:MM81", "employee_code": "MM81"}],
        mode="sequence",
    )
    db.add(rule)
    db.commit()

    result = resolve_approver(db, "Projects", None, "normal", "user:MM88")
    assert result.source == "rule"
    assert result.approver_sub == "user:MM81"  # skipped the requester themselves


def test_seed_default_routing_is_never_empty(db):
    """Scope decision, 25 Aug 2026: a fresh install (or a wiped test database) must never
    have zero approval rules and zero default approver — app/seed.py's
    `ensure_default_approval_routing` is what the app calls at startup to guarantee that."""
    from app.models import ApprovalDefault, ApprovalRule
    from app.seed import ensure_default_approval_routing

    assert db.query(ApprovalRule).count() == 0
    assert db.query(ApprovalDefault).count() == 0

    ensure_default_approval_routing()

    rules = db.query(ApprovalRule).all()
    assert len(rules) == 1
    assert rules[0].department is None and rules[0].category is None and rules[0].priority is None
    assert rules[0].approvers  # never empty

    default = db.query(ApprovalDefault).first()
    assert default is not None and default.sub

    # Calling it again must not duplicate the catch-all rule or the default row.
    ensure_default_approval_routing()
    assert db.query(ApprovalRule).count() == 1
    assert db.query(ApprovalDefault).count() == 1

    result = resolve_approver(db, "Any-Department-At-All", None, "normal", "user:MM33")
    assert result.approver_sub is not None
