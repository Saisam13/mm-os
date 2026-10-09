"""Real PostgreSQL concurrency checks through independent authenticated HTTP requests.

Run only against a disposable database: the shared test harness recreates its schema.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.db import engine
from app.main import app
from app.models import Employee, Session, User
from app.provision import FUNCTIONAL_JOB_TITLE
from app.security import new_session_token, session_expiry

pytestmark = [pytest.mark.needs_postgres, pytest.mark.skipif(engine.dialect.name != "postgresql", reason="Requires real PostgreSQL row and advisory locks")]


def test_simultaneous_duplicate_activity_deliveries_are_acknowledged_once(db, make_service):
    from app.activity_contract import make_event
    from app.models import ServiceActivity
    from app.security import hash_token
    service,_=make_service(service_key_hash=hash_token('mmk_concurrent_activity'))
    event=make_event(service=service.slug,actor={'sub':'user:synthetic','name':'Synthetic Person'},
        action='record.update',target_type='record',target_id='42')
    barrier=Barrier(2)
    def deliver(_):
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            return client.post('/api/agent/activity',json={'events':[event]},
                headers={'Authorization':'Bearer mmk_concurrent_activity'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(deliver,range(2)))
    assert [r.status_code for r in responses]==[200,200]
    assert all(r.json()['acknowledged']==[event['event_id']] for r in responses)
    assert db.scalar(select(func.count()).select_from(ServiceActivity))==1


@pytest.mark.parametrize("route", ["users", "accounts"])
def test_concurrent_self_deactivation_cannot_remove_every_admin(db, make_user, route):
    users = [make_user(is_platform_admin=True), make_user(is_platform_admin=True)]
    credentials = []
    for user in users:
        user.employee.job_title = FUNCTIONAL_JOB_TITLE
        raw, digest = new_session_token()
        db.add(Session(user_id=user.id, token_hash=digest, auth_method="google", expires_at=session_expiry()))
        credentials.append((str(user.id), raw))
    db.commit()
    barrier = Barrier(2)

    def deactivate(credential):
        user_id, cookie = credential
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            client.cookies.set(settings().cookie_name, cookie)
            barrier.wait(timeout=10)
            return client.patch(f"/api/admin/{route}/{user_id}", json={"is_active": False}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(deactivate, credentials))
    assert sorted(statuses) == [200, 409]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(User).join(Employee).where(
        User.is_platform_admin.is_(True), User.is_active.is_(True), Employee.status == "active",
    )) == 1


def test_parallel_wrong_pin_attempts_do_not_lose_account_lockout(db, make_user):
    user = make_user(auth_type="local_pin", pin="827461")
    code = user.employee.employee_code
    barrier = Barrier(6)

    def attempt(_):
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            barrier.wait(timeout=10)
            return client.post("/api/auth/pin", json={"employee_code": code, "pin": "000000"}).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(attempt, range(6)))
    assert statuses == [401] * 6
    db.refresh(user)
    assert user.failed_pin_attempts == settings().pin_max_attempts
    assert user.locked_until is not None
