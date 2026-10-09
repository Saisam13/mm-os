import copy
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from app.activity_contract import make_event
from app.models import Department, ServiceActivity, UserCapability
from app.security import hash_token


def test_shared_mailbox_token_and_audit_do_not_claim_an_individual(db, make_employee, make_user):
    import jwt
    from app import security
    from app.deps import audit
    from app.provision import FUNCTIONAL_JOB_TITLE
    employee=make_employee(job_title=FUNCTIONAL_JOB_TITLE)
    user=make_user(employee=employee)
    token,_,_=security.mint_service_token(user=user,employee=employee,service_slug='itemcode',roles=['admin'])
    claims=jwt.decode(token,options={'verify_signature':False})
    assert claims['actor_type']=='service' and claims['sub']==user.subject
    audit(db,action='test.shared_account',actor_user_id=user.id,target_type='test')
    db.commit()
    event=db.scalar(select(ServiceActivity).where(ServiceActivity.action=='test.shared_account'))
    assert event.payload['actor']['type']=='service'


def _event(slug, subject="user:reported", **kwargs):
    return make_event(service=slug, actor={"subject":subject,"name":"Original Person","employee_code":"MM123"},
                      action="tickets.update", target_type="tickets", target_id="42", **kwargs)


def test_collection_requires_service_key_and_enforces_source(db, client, make_service):
    svc, _ = make_service(service_key_hash=hash_token("mmk_activity"))
    event = _event(svc.slug)
    assert client.post("/api/agent/activity", json={"events":[event]}).status_code == 401
    headers={"Authorization":"Bearer mmk_activity"}
    event["service"]="someone_else"
    assert client.post("/api/agent/activity", json={"events":[event]}, headers=headers).status_code == 422
    assert db.scalar(select(func.count()).select_from(ServiceActivity)) == 0


def test_duplicates_acknowledged_but_different_content_conflicts_atomically(db, client, make_service):
    svc, _ = make_service(service_key_hash=hash_token("mmk_activity"))
    headers={"Authorization":"Bearer mmk_activity"}
    event=_event(svc.slug)
    for _ in range(2):
        response=client.post("/api/agent/activity",json={"events":[event]},headers=headers)
        assert response.status_code == 200 and response.json()["acknowledged"]==[event["event_id"]]
    conflicting=copy.deepcopy(event);conflicting["actor"]["name"]="Different person"
    new=_event(svc.slug)
    assert client.post("/api/agent/activity",json={"events":[new,conflicting]},headers=headers).status_code == 409
    assert db.scalar(select(func.count()).select_from(ServiceActivity))==1


def test_scoped_and_private_history_is_filtered_before_pagination(db, client, make_service, make_user, sign_in):
    department=Department(key="activity-dept",name="Activity Dept");db.add(department);db.commit()
    svc,_=make_service(service_key_hash=hash_token("mmk_activity"))
    reader=make_user();db.add(UserCapability(user_id=reader.id,capability="activity.view",scope_department_id=department.id));db.commit()
    visible=_event(svc.slug,department=department.name,restricted=False)
    private=_event(svc.slug,department=department.name)
    outside=_event(svc.slug,department="Other",restricted=False)
    assert client.post("/api/agent/activity",json={"events":[visible,private,outside]},headers={"Authorization":"Bearer mmk_activity"}).status_code==200
    sign_in(reader)
    result=client.get("/api/admin/activity?limit=1")
    assert result.status_code==200 and len(result.json()["events"])==1
    assert result.json()["events"][0]["event_id"]==visible["event_id"] and result.json()["next_offset"] is None
    db.add(UserCapability(user_id=reader.id,capability="activity.private.view",scope_department_id=department.id));db.commit()
    assert len(client.get("/api/admin/activity").json()["events"])==2


def test_platform_admin_does_not_implicitly_read_private_business_activity(client, make_service, make_user, sign_in):
    svc,_=make_service(service_key_hash=hash_token("mmk_activity"))
    event=_event(svc.slug)
    client.post("/api/agent/activity",json={"events":[event]},headers={"Authorization":"Bearer mmk_activity"})
    sign_in(make_user(is_platform_admin=True))
    assert client.get("/api/admin/activity").json()["events"]==[]


def test_collector_rejects_secrets_and_naive_dates(client,make_service):
    svc,_=make_service(service_key_hash=hash_token("mmk_activity"))
    headers={"Authorization":"Bearer mmk_activity"}
    event=_event(svc.slug);event["changes"]={"password":{"before":"old","after":"secret"}}
    assert client.post("/api/agent/activity",json={"events":[event]},headers=headers).status_code==422
    event=_event(svc.slug);event["occurred_at"]="2026-10-07T14:00:00"
    assert client.post("/api/agent/activity",json={"events":[event]},headers=headers).status_code==422
