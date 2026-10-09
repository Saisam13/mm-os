from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import sqlalchemy as sa

from app.activity import TABLES
from app.activity_contract import ActivityPublisher, enqueue, make_event
from app.db import SessionLocal
from app.models import Ticket
from tests.conftest import token_for, auth


def test_shared_mailbox_claim_is_retained_in_local_evidence(client):
    from app.mmos_seam import make_dev_token
    token=make_dev_token({'sub':'user:shared','emp':'SHARED','name':'Functional mailbox','dept':'IT',
        'roles':['agent'],'actor_type':'service'})
    result=client.post('/api/tickets',json={'kind':'support','title':'synthetic','body':'test'},headers=auth(token))
    assert result.status_code==201
    with SessionLocal() as db:
        event=next(e for e in db.execute(sa.select(TABLES[0].c.payload)).scalars() if e['action']=='tickets.create')
        assert event['actor']['type']=='service'


def test_delivery_status_requires_administration(client):
    assert client.get('/api/admin/activity-delivery',headers=auth(token_for('MM88',roles=['requester']))).status_code==403
    response=client.get('/api/admin/activity-delivery',headers=auth(token_for('MM88',roles=['admin'])))
    assert response.status_code==200 and 'pending' in response.json()


def test_verified_actor_overrides_supplied_identity_and_history_is_readable(client):
    token=token_for("MM88",roles=["agent"])
    response=client.post("/api/tickets",json={"kind":"support","title":"Synthetic request","body":"No real data",
        "actor_sub":"user:forged","requester_sub":"user:forged"},headers=auth(token))
    assert response.status_code==201
    ticket=response.json()
    assert ticket["requester_sub"]!="user:forged"
    events=client.get(f"/api/tickets/{ticket['id']}/events",headers=auth(token)).json()
    assert events[0]["actor_name"] and events[0]["actor_code"]=="MM88"
    assignment=client.post(f"/api/tickets/{ticket['id']}/assign",json={},headers=auth(token))
    assert assignment.status_code==200
    events=client.get(f"/api/tickets/{ticket['id']}/events",headers=auth(token)).json()
    assert any(e["detail"].get("action")=="assigned" and e["actor_code"]=="MM88" for e in events)
    with SessionLocal() as db:
        payloads=db.execute(sa.select(TABLES[0].c.payload)).scalars().all()
        assert any(e["action"]=="tickets.create" and e["actor"]["employee_code"]=="MM88" for e in payloads)
        assert all(e["actor"]["subject"]!="user:forged" for e in payloads)
        assert "No real data" not in str(payloads)


def test_business_rollback_removes_queued_success_event():
    with SessionLocal() as db:
        db.info["activity_actor"]=SimpleNamespace(sub="user:test",name="Test Person",employee_code="MMTEST")
        row=Ticket(ref="SUP-rollback",kind="support",title="test",body="test",requester_sub="user:test",
            requester_code="MMTEST",requester_dept="IT",status="open")
        db.add(row);db.flush()
        assert db.scalar(sa.select(sa.func.count()).select_from(TABLES[0]))==1
        db.rollback()
    with SessionLocal() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(TABLES[0]))==0
        assert db.scalar(sa.select(sa.func.count()).select_from(Ticket))==0


def test_outage_restart_retry_and_partial_ack_preserve_evidence():
    event=make_event(service="servicedesk",actor={"subject":"user:test","name":"Original Name","employee_code":"MMTEST"},
        action="tickets.update",target_type="tickets",target_id="42")
    with SessionLocal() as db:
        enqueue(db,TABLES,event);db.commit()
    down=httpx.Client(base_url="https://mmos.test",transport=httpx.MockTransport(lambda _:httpx.Response(503)))
    sender=ActivityPublisher(session_factory=SessionLocal,tables=TABLES,os_url="https://mmos.test",service_key="mmk_test",service="servicedesk",http_client=down)
    assert sender.publish_once()==0
    with SessionLocal() as db:
        assert db.scalar(sa.select(TABLES[1].c.delivered_at)) is None
        assert db.scalar(sa.select(TABLES[0].c.payload))["actor"]["name"]=="Original Name"
        db.execute(TABLES[1].update().values(next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1)));db.commit()
    received=[]
    def ack(request):
        import json
        received.extend(json.loads(request.content)["events"])
        return httpx.Response(200,json={"acknowledged":[event["event_id"]]})
    up=httpx.Client(base_url="https://mmos.test",transport=httpx.MockTransport(ack))
    restarted=ActivityPublisher(session_factory=SessionLocal,tables=TABLES,os_url="https://mmos.test",service_key="mmk_test",service="servicedesk",http_client=up)
    assert restarted.publish_once()==1 and restarted.publish_once()==0
    assert received==[event]
    with SessionLocal() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(TABLES[0]))==1
