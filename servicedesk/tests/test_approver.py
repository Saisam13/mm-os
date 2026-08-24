"""Computed approver — docs/07's central rule, and the escalation acceptance test."""
import pytest

from app.org_chart import NoApproverFound, compute_approver, default_seed


def test_operator_escalates_to_qualifying_hod():
    client = default_seed()
    approver = compute_approver("user:op-1", client)
    assert approver.sub == "user:hod-1"  # supervisor is "Operational" — does not qualify


def test_hod_raising_own_request_escalates_past_self_to_apex():
    """Acceptance test: "a requester who is their own computed approver sees it escalate
    one level." The HOD qualifies on their own approval_level, so the naive walk would stop
    at the requester themselves — compute_approver must skip that and keep climbing."""
    client = default_seed()
    approver = compute_approver("user:hod-1", client)
    assert approver.sub == "user:apex-1"
    assert approver.sub != "user:hod-1"


def test_apex_with_nobody_above_raises():
    client = default_seed()
    with pytest.raises(NoApproverFound):
        compute_approver("user:apex-1", client)


def test_is_approver_override_qualifies_regardless_of_level(monkeypatch):
    from app.org_chart import PersonNode, SeedOrgChartClient

    requester = PersonNode(sub="u:r", employee_code="MM90", full_name="R", department="X",
                            approval_level="Operational", is_approver=False, manager_sub="u:override")
    override = PersonNode(sub="u:override", employee_code="MM91", full_name="Override", department="X",
                           approval_level=None, is_approver=True, manager_sub=None)
    client = SeedOrgChartClient({requester.sub: requester, override.sub: override})
    approver = compute_approver("u:r", client)
    assert approver.sub == "u:override"
