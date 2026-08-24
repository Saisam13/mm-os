"""Department-queue privacy — docs/07: "filter in the query, not in the browser." The
acceptance test that matters here is what a third department member — not the requester, not
the assignee, not the approver — actually receives over the API, not what the UI would show
them.
"""
from tests.conftest import auth, custom_token, token_for

THIRD_MEMBER = auth(custom_token("user:peer-1", dept="Projects", roles=["requester"], emp="MM20"))


def test_private_ticket_is_a_hidden_row_to_a_third_department_member(client):
    create = client.post(
        "/api/tickets",
        json={"kind": "support", "title": "Payroll discrepancy", "body": "My March salary is short",
              "is_private": True},
        headers=auth(token_for("MM88")),
    )
    ticket = create.json()
    tid = ticket["id"]
    assert ticket["title"] == "Payroll discrepancy"  # the requester sees their own in full

    dept_queue = client.get("/api/tickets/department", headers=THIRD_MEMBER).json()
    row = next(r for r in dept_queue if r["id"] == tid)
    assert row["hidden"] is True
    assert "title" not in row
    assert "body" not in row
    assert row["status"] == "open"
    assert "assignee_sub" in row  # age/assignee only, so the queue count and wait stay honest

    detail = client.get(f"/api/tickets/{tid}", headers=THIRD_MEMBER).json()
    assert "title" not in detail
    assert "body" not in detail
    assert detail["hidden"] is True

    client.post(f"/api/tickets/{tid}/comments", json={"body": "internal note"}, headers=auth(token_for("MM88")))
    comments = client.get(f"/api/tickets/{tid}/comments", headers=THIRD_MEMBER).json()
    assert comments == []


def test_private_ticket_still_counts_in_department_queue(client):
    client.post(
        "/api/tickets",
        json={"kind": "support", "title": "Private one", "body": "…", "is_private": True},
        headers=auth(token_for("MM88")),
    )
    dept_queue = client.get("/api/tickets/department", headers=THIRD_MEMBER).json()
    assert len(dept_queue) == 1


def test_requester_assignee_and_approver_see_full_private_ticket(client):
    create = client.post(
        "/api/tickets",
        json={"kind": "automation", "title": "Private automation", "body": "…", "is_private": True},
        headers=auth(token_for("MM88")),
    )
    tid = create.json()["id"]
    agent_hdr = auth(token_for("MM05", roles=["agent"]))
    client.post(f"/api/tickets/{tid}/transition", json={"to_status": "it_review"}, headers=agent_hdr)
    client.post(f"/api/tickets/{tid}/assign", json={}, headers=agent_hdr)

    for hdr in (auth(token_for("MM88")), agent_hdr, auth(token_for("MM81"))):
        detail = client.get(f"/api/tickets/{tid}", headers=hdr).json()
        assert detail["title"] == "Private automation"


def test_non_private_ticket_is_fully_visible_in_department_queue(client):
    client.post(
        "/api/tickets", json={"kind": "support", "title": "Broken chair", "body": "…"},
        headers=auth(token_for("MM88")),
    )
    dept_queue = client.get("/api/tickets/department", headers=THIRD_MEMBER).json()
    assert dept_queue[0]["title"] == "Broken chair"
