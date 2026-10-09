"""Security regressions for object privacy, permissions and approval policy."""
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import ApprovalRule, Decision, Ticket
from app.routing import resolve_approver
from .conftest import auth, token_for


def _ticket(db, **kw):
    ticket = Ticket(ref="AUDIT-0001", kind="automation", title="Restricted audit ticket",
                    body="Synthetic confidential information", requester_sub="user:MM88",
                    requester_code="MM88", requester_dept="Projects", status="manager_review",
                    assignee_sub="user:assigned-agent", approver_sub="user:MM81", is_private=True,
                    **kw)
    db.add(ticket)
    db.commit()
    return ticket


def test_A15_real_lifespan_starts_and_stops_revocation_poller(monkeypatch):
    from app.main import lifespan
    from mmos_client.core import MMOS
    # Actual Service Desk lifespan, with the service key empty to suppress outbound heartbeat.
    service = FastAPI(lifespan=lifespan)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"keys": []}))
    with httpx.Client(base_url="https://audit.invalid", transport=transport) as http:
        mmos = MMOS(slug="audit", os_url="https://audit.invalid", service_key="synthetic",
                    http_client=http)
        started = []
        monkeypatch.setattr(mmos.poller, "start", lambda: started.append("revocations"))
        monkeypatch.setattr(mmos.heartbeat, "start", lambda: started.append("heartbeat"))
        mmos.install(service)
        with TestClient(service):
            assert started == ["revocations", "heartbeat"]


def test_A16_unrelated_user_cannot_read_private_decision(db, client):
    ticket = _ticket(db)
    db.add(Decision(ticket_id=ticket.id, approver_sub="user:MM81", approver_code="MM81",
                    decision="approved", comment="Synthetic restricted comment",
                    snapshot={"scope_summary": "Synthetic restricted scope", "resources": {"budget": 42}}))
    db.commit()
    response = client.get(f"/api/tickets/{ticket.id}/decisions", headers=auth(token_for("MM05")))
    assert response.status_code == 403
    assert "snapshot" not in response.text


def test_A16_unauthenticated_decision_read_denied(db, client):
    ticket = _ticket(db)
    db.add(Decision(ticket_id=ticket.id, approver_sub="user:MM81", approver_code="MM81",
                    decision="approved", snapshot={"scope_summary": "Synthetic restricted scope"}))
    db.commit()
    response = client.get(f"/api/tickets/{ticket.id}/decisions")
    assert response.status_code == 401


def test_A17_unassigned_agent_cannot_claim_private_ticket(db, client):
    ticket = _ticket(db)
    credentials = auth(token_for("MM05", roles=["agent"]))
    before = client.get(f"/api/tickets/{ticket.id}", headers=credentials)
    assert "body" not in before.json()
    response = client.post(f"/api/tickets/{ticket.id}/assign", headers=credentials, json={})
    assert response.status_code == 403
    db.refresh(ticket)
    assert ticket.assignee_sub == "user:assigned-agent"


def test_A18_sequence_rule_requires_every_approval(db, client):
    db.add(ApprovalRule(name="Two independent approvals", department="Projects", mode="sequence",
                        approvers=[{"sub": "user:MM81", "employee_code": "MM81"},
                                   {"sub": "user:MM05", "employee_code": "MM05"}]))
    db.commit()
    routing = resolve_approver(db, "Projects", None, "normal", "user:MM88")
    assert routing.approver_sub == "user:MM81"
    ticket = _ticket(db)
    ticket.approval_policy = {"mode": routing.mode, "approvers": routing.approvers}
    db.commit()
    response = client.post(f"/api/tickets/{ticket.id}/decisions", headers=auth(token_for("MM81")),
                           json={"decision": "approved", "comment": "First approval only"})
    assert response.status_code == 201
    db.refresh(ticket)
    assert ticket.status == "manager_review"
    assert ticket.approver_sub == "user:MM05"
    final = client.post(f"/api/tickets/{ticket.id}/decisions", headers=auth(token_for("MM05")), json={"decision": "approved"})
    assert final.status_code == 201
    db.refresh(ticket)
    assert ticket.status == "approved"


def test_A19_empty_permissions_deny_agent_authority(db, client):
    from app.mmos_seam import make_dev_token
    claims = {"sub": "user:MM05", "emp": "MM05", "dept": "P-Spoke",
              "roles": ["agent"], "permissions": [], "pv": "empty"}
    response = client.get("/api/tickets/queue", headers=auth(make_dev_token(claims)))
    assert response.status_code == 403


def test_A20_foreign_origin_cookie_mutation_denied(client):
    from app.mmos_seam import COOKIE_NAME
    client.cookies.set(COOKIE_NAME, token_for("MM88"))
    response = client.post("/api/tickets", headers={"Origin": "https://foreign.example"},
                           json={"kind": "support", "title": "Synthetic audit request",
                                 "body": "Synthetic audit body"})
    assert response.status_code == 403
