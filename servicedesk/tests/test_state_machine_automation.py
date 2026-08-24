"""Automation request state machine — the point of this service (docs/07)."""
from tests.conftest import auth, token_for


def _submit(client, requester="MM88"):
    r = client.post(
        "/api/tickets",
        json={"kind": "automation", "title": "Nightly DPR watch", "body": "Flag variance beyond 5%"},
        headers=auth(token_for(requester)),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_starts_submitted_with_computed_approver(client):
    ticket = _submit(client)
    assert ticket["status"] == "submitted"
    assert ticket["approver_sub"] == "user:MM81"  # MM88's manager chain -> MM81 qualifies


def test_cannot_skip_submitted_to_manager_review(client):
    ticket = _submit(client)
    agent_hdr = auth(token_for("MM05", roles=["agent"]))
    r = client.post(f"/api/tickets/{ticket['id']}/transition", json={"to_status": "manager_review"}, headers=agent_hdr)
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["error"] == "invalid_transition"
    assert body["from"] == "submitted"
    assert body["to"] == "manager_review"


def test_it_review_can_reject_not_feasible(client):
    ticket = _submit(client)
    agent_hdr = auth(token_for("MM05", roles=["agent"]))
    client.post(f"/api/tickets/{ticket['id']}/transition", json={"to_status": "it_review"}, headers=agent_hdr)
    r = client.post(
        f"/api/tickets/{ticket['id']}/transition",
        json={"to_status": "rejected", "detail": {"reason": "not feasible"}},
        headers=agent_hdr,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_proposal_ready_and_manager_review_not_reachable_via_generic_transition(client):
    """it_review -> proposal_ready and manager_review -> * are only reachable through the
    proposals/decisions endpoints, never the generic one — see routers/tickets.py."""
    ticket = _submit(client)
    agent_hdr = auth(token_for("MM05", roles=["agent"]))
    client.post(f"/api/tickets/{ticket['id']}/transition", json={"to_status": "it_review"}, headers=agent_hdr)
    r = client.post(f"/api/tickets/{ticket['id']}/transition", json={"to_status": "proposal_ready"}, headers=agent_hdr)
    assert r.status_code == 409
