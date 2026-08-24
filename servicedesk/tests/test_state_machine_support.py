"""Support ticket state machine — docs/07's diagram, enforced not by convention."""
from tests.conftest import auth, token_for


def _open_ticket(client):
    r = client.post("/api/tickets", json={"kind": "support", "title": "Printer jam", "body": "Floor 2 printer stuck"},
                     headers=auth(token_for("MM88")))
    assert r.status_code == 201, r.text
    return r.json()


def test_support_full_path_and_reopen(client):
    ticket = _open_ticket(client)
    assert ticket["status"] == "open"
    tid = ticket["id"]
    agent_hdr = auth(token_for("MM05", roles=["agent"]))

    for to_status in ("in_progress", "waiting_on_requester", "resolved", "closed"):
        r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": to_status}, headers=agent_hdr)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == to_status

    # reopen within the 7-day window
    r = client.post(f"/api/tickets/{tid}/transition", json={"to_status": "resolved"}, headers=agent_hdr)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"


def test_support_reject_from_open(client):
    ticket = _open_ticket(client)
    agent_hdr = auth(token_for("MM05", roles=["agent"]))
    r = client.post(f"/api/tickets/{ticket['id']}/transition", json={"to_status": "rejected"}, headers=agent_hdr)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_illegal_support_transition_is_409(client):
    ticket = _open_ticket(client)
    agent_hdr = auth(token_for("MM05", roles=["agent"]))
    # open -> resolved skips in_progress and waiting_on_requester
    r = client.post(f"/api/tickets/{ticket['id']}/transition", json={"to_status": "resolved"}, headers=agent_hdr)
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["error"] == "invalid_transition"
    assert body["from"] == "open"
    assert body["to"] == "resolved"


def test_reopen_window_expired(client, db):
    import uuid
    from datetime import datetime, timedelta, timezone

    from app.models import Ticket

    ticket = _open_ticket(client)
    row = db.get(Ticket, uuid.UUID(ticket["id"]))
    row.status = "closed"
    row.closed_at = datetime.now(timezone.utc) - timedelta(days=8)
    db.commit()

    agent_hdr = auth(token_for("MM05", roles=["agent"]))
    r = client.post(f"/api/tickets/{ticket['id']}/transition", json={"to_status": "resolved"}, headers=agent_hdr)
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "reopen_window_expired"
