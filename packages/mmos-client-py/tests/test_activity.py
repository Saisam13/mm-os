import json
import sqlite3
from datetime import datetime, timezone

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from mmos_client.activity import (SQLiteActivityPublisher, install_sqlite_capture, validate_event, canonical,
                                 install_orm_capture, ActivityPublisher, make_event, enqueue)


ACTOR = {'sub':'user:stable','name':'Original Person','emp':'MM0042'}


def setup_sqlite(path, provider=lambda:ACTOR):
    con=sqlite3.connect(path)
    con.execute('CREATE TABLE IF NOT EXISTS business(id INTEGER PRIMARY KEY, secret TEXT)')
    install_sqlite_capture(con,service='example',actor_provider=provider,included_tables={'business'})
    return con


def test_sqlite_writes_rollback_with_evidence_and_payload_excludes_content(tmp_path):
    path=tmp_path/'business.db'
    con=setup_sqlite(path)
    con.execute("INSERT INTO business(secret) VALUES('private content')")
    event=json.loads(con.execute('SELECT payload FROM activity_events').fetchone()[0])
    validate_event(event)
    assert event['actor']['subject']=='user:stable' and event['actor']['employee_code']=='MM0042'
    assert 'private content' not in canonical(event)
    assert con.execute('SELECT event_id FROM activity_delivery').fetchone()[0]==event['event_id']
    assert con.execute('SELECT event_id FROM activity_events').fetchone()[0]==event['event_id']
    con.rollback()
    assert con.execute('SELECT COUNT(*) FROM business').fetchone()[0]==0
    assert con.execute('SELECT COUNT(*) FROM activity_events').fetchone()[0]==0
    con.close()


def test_sqlite_actor_failure_prevents_unattributed_business_commit_and_events_are_immutable(tmp_path):
    con=setup_sqlite(tmp_path/'atomic.db')
    con.execute("INSERT INTO business(secret) VALUES('value')");con.commit()
    for statement in ['UPDATE activity_events SET payload=payload','DELETE FROM activity_events']:
        with pytest.raises(sqlite3.IntegrityError):con.execute(statement)
        con.rollback()
    install_sqlite_capture(con,service='example',actor_provider=lambda: {},included_tables={'business'})
    with pytest.raises(sqlite3.OperationalError):con.execute("UPDATE business SET secret='changed'")
    con.rollback()
    assert con.execute('SELECT secret FROM business').fetchone()[0]=='value'
    con.close()


def test_sqlite_delivery_survives_restart_outage_and_invalid_acknowledgement(tmp_path):
    path=tmp_path/'restart.db'
    con=setup_sqlite(path);con.execute("INSERT INTO business(secret) VALUES('value')");con.commit();con.close()
    behavior={'mode':'down'}
    received=[]
    def handle(request):
        body=json.loads(request.content);received.append(body['events'])
        if behavior['mode']=='down': return httpx.Response(503)
        if behavior['mode']=='forged':return httpx.Response(200,json={'acknowledged':['unexpected']})
        return httpx.Response(200,json={'acknowledged':[e['event_id'] for e in body['events']]})
    client=httpx.Client(transport=httpx.MockTransport(handle),base_url='https://os.test')
    def worker():return SQLiteActivityPublisher(connection_factory=lambda:sqlite3.connect(path),os_url='https://os.test',
                                               service='example',service_key='test-key',http_client=client)
    assert worker().publish_once()==0
    con=sqlite3.connect(path);con.execute('UPDATE activity_delivery SET next_attempt_at=NULL');con.commit();con.close()
    behavior['mode']='forged';assert worker().publish_once()==0
    con=sqlite3.connect(path);con.execute('UPDATE activity_delivery SET next_attempt_at=NULL');con.commit();con.close()
    behavior['mode']='up';assert worker().publish_once()==1
    assert worker().publish_once()==0
    assert received[0][0]['event_id']==received[-1][0]['event_id']
    con=sqlite3.connect(path)
    assert con.execute('SELECT COUNT(*) FROM activity_events').fetchone()[0]==1
    assert con.execute('SELECT delivered_at FROM activity_delivery').fetchone()[0]
    con.close()


def test_orm_flush_and_bulk_delete_capture_actor_in_business_transaction(tmp_path):
    class Base(DeclarativeBase):pass
    class Business(Base):
        __tablename__='business_orm'
        id=sa.Column(sa.Integer,primary_key=True)
        user_name=sa.Column(sa.String)
        secret=sa.Column(sa.String)
    engine=sa.create_engine(f"sqlite:///{tmp_path/'orm.db'}")
    tables=install_orm_capture(metadata=Base.metadata,service='example',actor_provider=lambda:ACTOR,included_tables={'business_orm'})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row=Business(user_name='forged',secret='never export this');db.add(row);db.commit()
        assert row.user_name=='Original Person'
        payload=db.execute(sa.select(tables[0].c.payload)).scalar_one()
        assert payload['actor']['subject']=='user:stable' and 'never export this' not in canonical(payload)
        db.execute(sa.delete(Business).where(Business.id==row.id));db.rollback()
        assert db.get(Business,row.id) is not None
        assert db.execute(sa.select(sa.func.count()).select_from(tables[0])).scalar_one()==1
        db.execute(sa.delete(Business).where(Business.id==row.id));db.commit()
        assert db.execute(sa.select(sa.func.count()).select_from(tables[0])).scalar_one()==2
    engine.dispose()
