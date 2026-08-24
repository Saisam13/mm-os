"""Proposal validation and the immutable decision snapshot — docs/07's two rules that make
approval real."""
from tests.conftest import auth, token_for

AGENT = auth(token_for("supervisor", roles=["agent"]))
HOD_APPROVES = auth(token_for("hod"))


def _to_it_review(client, ticket_id):
    client.post(f"/api/tickets/{ticket_id}/transition", json={"to_status": "it_review"}, headers=AGENT)


def _submit(client):
    r = client.post(
        "/api/tickets",
        json={"kind": "automation", "title": "Nightly DPR watch", "body": "Flag variance beyond 5%"},
        headers=auth(token_for("operator")),
    )
    return r.json()


def test_proposal_without_alternatives_is_rejected(client):
    ticket = _submit(client)
    _to_it_review(client, ticket["id"])
    r = client.post(
        f"/api/tickets/{ticket['id']}/proposals",
        json={"scope_summary": "Nightly job", "effort_days": 4, "resources": {}, "alternatives": ""},
        headers=AGENT,
    )
    assert r.status_code == 422


def test_proposal_moves_ticket_to_proposal_ready(client):
    ticket = _submit(client)
    _to_it_review(client, ticket["id"])
    r = client.post(
        f"/api/tickets/{ticket['id']}/proposals",
        json={"scope_summary": "Nightly job", "effort_days": 4, "resources": {}, "alternatives": "A saved report"},
        headers=AGENT,
    )
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1
    detail = client.get(f"/api/tickets/{ticket['id']}", headers=AGENT).json()
    assert detail["status"] == "proposal_ready"


def _to_manager_review(client, ticket_id, alternatives="A saved report"):
    _to_it_review(client, ticket_id)
    client.post(
        f"/api/tickets/{ticket_id}/proposals",
        json={"scope_summary": "Nightly job", "effort_days": 4, "resources": {"cpu": "0.5"}, "alternatives": alternatives},
        headers=AGENT,
    )
    client.post(f"/api/tickets/{ticket_id}/transition", json={"to_status": "manager_review"}, headers=AGENT)


def test_snapshot_immutable_across_later_proposal_revision(client):
    ticket = _submit(client)
    _to_manager_review(client, ticket["id"])

    r = client.post(f"/api/tickets/{ticket['id']}/decisions", json={"decision": "approved"}, headers=HOD_APPROVES)
    assert r.status_code == 201, r.text
    decision = r.json()
    assert decision["snapshot"]["effort_days"] == 4.0
    assert decision["snapshot"]["version"] == 1

    # IT later revises the proposal (v2) — the earlier decision's snapshot must not move.
    client.post(
        f"/api/tickets/{ticket['id']}/proposals",
        json={"scope_summary": "Nightly job, wider scope", "effort_days": 9, "resources": {}, "alternatives": "None now"},
        headers=AGENT,
    )
    decisions = client.get(f"/api/tickets/{ticket['id']}/decisions", headers=AGENT).json()
    assert decisions[0]["snapshot"]["effort_days"] == 4.0
    assert decisions[0]["snapshot"]["version"] == 1


def test_requester_cannot_decide_even_if_somehow_the_approver_sub(client, db):
    import uuid

    from app.models import Ticket

    ticket = _submit(client)
    _to_manager_review(client, ticket["id"])
    row = db.get(Ticket, uuid.UUID(ticket["id"]))
    row.approver_sub = row.requester_sub  # simulate a bad row / bug
    db.commit()

    r = client.post(
        f"/api/tickets/{ticket['id']}/decisions", json={"decision": "approved"},
        headers=auth(token_for("operator")),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "cannot_approve_own_request"


def test_only_computed_approver_may_decide(client):
    ticket = _submit(client)
    _to_manager_review(client, ticket["id"])
    r = client.post(
        f"/api/tickets/{ticket['id']}/decisions", json={"decision": "approved"},
        headers=auth(token_for("apex")),  # not this ticket's computed approver (HOD is)
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_the_approver"
