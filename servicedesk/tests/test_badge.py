"""GET /api/badge — the count the OS bar shows (docs/03's /api/me `badges.servicedesk_open`,
docs/07's "MM OS badge count")."""
from tests.conftest import auth, token_for


def test_badge_counts_open_requests_and_pending_approvals(client):
    op = auth(token_for("operator"))
    client.post("/api/tickets", json={"kind": "support", "title": "A", "body": "…"}, headers=op)
    client.post("/api/tickets", json={"kind": "automation", "title": "B", "body": "…"}, headers=op)

    r = client.get("/api/badge", params={"sub": "user:op-1"})
    assert r.status_code == 200
    assert r.json() == {"open": 2, "approvals_waiting": 0}

    agent_hdr = auth(token_for("supervisor", roles=["agent"]))
    tickets = client.get("/api/tickets/mine", headers=op).json()
    automation = next(t for t in tickets if t["kind"] == "automation")
    client.post(f"/api/tickets/{automation['id']}/transition", json={"to_status": "it_review"}, headers=agent_hdr)
    client.post(
        f"/api/tickets/{automation['id']}/proposals",
        json={"scope_summary": "x", "alternatives": "y"}, headers=agent_hdr,
    )
    client.post(f"/api/tickets/{automation['id']}/transition", json={"to_status": "manager_review"}, headers=agent_hdr)

    r = client.get("/api/badge", params={"sub": "user:hod-1"})
    assert r.json()["approvals_waiting"] == 1
