"""The acceptance test that matters most: an automation request through the full approval
chain — raised, triaged, IT proposal, department-manager approval, resolved — with an events
row for every hop (docs/07 / agents/A5-servicedesk.md)."""
from tests.conftest import auth, token_for

AGENT = auth(token_for("MM05", roles=["agent"]))
HOD = auth(token_for("MM81"))


def test_requester_to_it_proposal_to_manager_approval_to_build_to_deployed(client, db):
    import uuid

    from app.models import Event

    submit = client.post(
        "/api/tickets",
        json={"kind": "automation", "title": "Nightly DPR watch", "body": "Flag variance beyond 5%"},
        headers=auth(token_for("MM88")),
    )
    assert submit.status_code == 201
    ticket = submit.json()
    tid = ticket["id"]
    assert ticket["status"] == "submitted"
    assert ticket["approver_sub"] == "user:MM81"

    r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": "it_review"}, headers=AGENT)
    assert r.status_code == 200 and r.json()["status"] == "it_review"

    r = client.post(
        f"/api/tickets/{tid}/proposals",
        json={
            "scope_summary": "Nightly job pulls DPR, flags variance beyond 5%, mails HOD.",
            "effort_days": 4, "resources": {"container": {"cpu": "0.5", "ram_mb": 512}},
            "alternatives": "An ERPNext report and a saved filter, at zero build cost.",
        },
        headers=AGENT,
    )
    assert r.status_code == 201
    assert client.get(f"/api/tickets/{tid}", headers=AGENT).json()["status"] == "proposal_ready"

    r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": "manager_review"}, headers=AGENT)
    assert r.status_code == 200 and r.json()["status"] == "manager_review"

    r = client.post(f"/api/tickets/{tid}/decisions", json={"decision": "approved", "comment": "Go ahead"}, headers=HOD)
    assert r.status_code == 201
    assert client.get(f"/api/tickets/{tid}", headers=AGENT).json()["status"] == "approved"

    r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": "in_build"}, headers=AGENT)
    assert r.status_code == 200

    r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": "deployed"}, headers=AGENT)
    assert r.status_code == 200

    r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": "closed"}, headers=AGENT)
    assert r.status_code == 200 and r.json()["status"] == "closed"

    events = db.query(Event).filter(Event.ticket_id == uuid.UUID(tid)).order_by(Event.created_at.asc()).all()
    hops = [(e.from_status, e.to_status) for e in events]
    assert hops == [
        (None, "submitted"),
        ("submitted", "it_review"),
        ("it_review", "proposal_ready"),
        ("proposal_ready", "manager_review"),
        ("manager_review", "approved"),
        ("approved", "in_build"),
        ("in_build", "deployed"),
        ("deployed", "closed"),
    ]


def test_support_ticket_full_lifecycle(client):
    submit = client.post(
        "/api/tickets", json={"kind": "support", "title": "VPN drops", "body": "Disconnects every 10 min"},
        headers=auth(token_for("MM88")),
    )
    tid = submit.json()["id"]
    for to_status in ("in_progress", "waiting_on_requester", "resolved", "closed"):
        r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": to_status}, headers=AGENT)
        assert r.status_code == 200
    r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": "resolved"}, headers=AGENT)
    assert r.status_code == 200 and r.json()["status"] == "resolved"


def test_events_endpoint_lists_history_and_respects_privacy(client):
    from tests.conftest import custom_token

    submit = client.post(
        "/api/tickets",
        json={"kind": "support", "title": "Private one", "body": "…", "is_private": True},
        headers=auth(token_for("MM88")),
    )
    tid = submit.json()["id"]

    mine = client.get(f"/api/tickets/{tid}/events", headers=auth(token_for("MM88"))).json()
    assert len(mine) == 1 and mine[0]["to_status"] == "open"

    peer = auth(custom_token("user:peer-2", dept="P-Spoke", roles=["requester"]))
    assert client.get(f"/api/tickets/{tid}/events", headers=peer).json() == []
