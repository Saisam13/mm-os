"""Versioned, content-minimized activity events and a transactional SQLAlchemy outbox.

Service keys attest the reporting service. Services bind human actors to verified request
principals; the collector must never treat reported actors as authentication credentials.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone


SAFE_VALUES = {"status", "priority", "is_active", "is_private", "assignee_sub", "approver_sub", "decision", "version", "mode", "role", "permissions"}


def actor_snapshot(principal):
    def get(key, default=None):
        return principal.get(key, default) if isinstance(principal, dict) else getattr(principal, key, default)
    subject = get("sub") or get("subject") or get("id")
    if not subject:
        raise ValueError("An authenticated actor or explicit system identity is required")
    return {"subject": str(subject), "type": get("actor_type") or get("type") or "human",
            "name": get("name") or get("full_name") or None,
            "employee_code": get("employee_code") or get("emp") or None}


def make_event(*, service, actor, action, target_type, target_id, changed_fields=(), changes=None,
               restricted=True, department=None, request_id=None, outcome="success", event_id=None):
    event = {"schema_version": 1, "event_id": str(event_id or uuid.uuid4()), "service": service,
             "actor": actor_snapshot(actor), "action": action,
             "target": {"type": str(target_type), "id": str(target_id)},
             "occurred_at": datetime.now(timezone.utc).isoformat(), "outcome": outcome,
             "restricted": bool(restricted), "department": department,
             "request_id": request_id, "changed_fields": sorted(set(changed_fields)),
             "changes": {k: v for k, v in (changes or {}).items() if k in SAFE_VALUES}}
    validate_event(event)
    return event


def validate_event(event):
    required = {"schema_version", "event_id", "service", "actor", "action", "target", "occurred_at", "outcome", "restricted", "department", "request_id", "changed_fields", "changes"}
    if not isinstance(event, dict) or set(event) != required or type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValueError("Unsupported activity schema")
    if not isinstance(event["event_id"], str):
        raise ValueError("Invalid event ID")
    uuid.UUID(event["event_id"])
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", event["service"]) or not re.fullmatch(r"[a-z0-9_.-]{1,96}", event["action"]):
        raise ValueError("Invalid service or action")
    def bounded(value, limit, optional=False):
        if optional and value is None:
            return
        if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid activity field")
    actor = event["actor"]
    if not isinstance(actor, dict) or set(actor) != {"subject", "type", "name", "employee_code"}:
        raise ValueError("Invalid actor")
    bounded(actor["subject"], 180)
    bounded(actor["name"], 180, True)
    bounded(actor["employee_code"], 32, True)
    if actor["type"] not in {"human", "service", "system", "legacy_unknown"}:
        raise ValueError("Invalid actor type")
    if not isinstance(event["target"], dict) or set(event["target"]) != {"type", "id"}:
        raise ValueError("Invalid target")
    bounded(event["target"]["type"], 64)
    bounded(event["target"]["id"], 180)
    bounded(event["department"], 180, True)
    bounded(event["request_id"], 128, True)
    bounded(event["occurred_at"], 64)
    at = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    if at.tzinfo is None or at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("Invalid activity timestamp")
    if event["outcome"] not in {"success", "denied", "failed"} or type(event["restricted"]) is not bool:
        raise ValueError("Invalid outcome or visibility")
    if not isinstance(event["changed_fields"], list) or len(event["changed_fields"]) > 100:
        raise ValueError("Invalid changed fields")
    for value in event["changed_fields"]:
        bounded(value, 64)
    if not isinstance(event["changes"], dict) or not set(event["changes"]).issubset(SAFE_VALUES):
        raise ValueError("Sensitive or unsupported change values")
    # Change values are short scalar snapshots, never arbitrary request bodies.
    for value in event["changes"].values():
        if not isinstance(value, dict) or set(value) != {"before", "after"}:
            raise ValueError("Invalid change snapshot")
        for scalar in value.values():
            if scalar is not None and type(scalar) not in {str, int, bool}:
                raise ValueError("Only scalar change values are supported")
            if isinstance(scalar, str) and (len(scalar) > 180 or any(ord(c) < 32 for c in scalar)):
                raise ValueError("Invalid change value")
    if len(canonical(event).encode()) > 12000:
        raise ValueError("Activity event too large")
    return event


def canonical(event):
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def define_tables(metadata):
    import sqlalchemy as sa
    if "activity_events" in metadata.tables:
        return metadata.tables["activity_events"], metadata.tables["activity_delivery"]
    events = sa.Table("activity_events", metadata,
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    delivery = sa.Table("activity_delivery", metadata,
        sa.Column("event_id", sa.String(36), sa.ForeignKey("activity_events.event_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer, nullable=False, default=0),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(64)))
    sa.Index("ix_activity_delivery_pending", delivery.c.delivered_at, delivery.c.next_attempt_at)
    sa.event.listen(events, "after_create", sa.DDL("CREATE TRIGGER activity_events_no_update BEFORE UPDATE ON activity_events BEGIN SELECT RAISE(ABORT,'Activity evidence is immutable'); END").execute_if(dialect="sqlite"))
    sa.event.listen(events, "after_create", sa.DDL("CREATE TRIGGER activity_events_no_delete BEFORE DELETE ON activity_events BEGIN SELECT RAISE(ABORT,'Activity evidence is immutable'); END").execute_if(dialect="sqlite"))
    sa.event.listen(events, "after_create", sa.DDL("CREATE OR REPLACE FUNCTION mmos_local_activity_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Activity evidence is immutable'; END $$").execute_if(dialect="postgresql"))
    sa.event.listen(events, "after_create", sa.DDL("CREATE TRIGGER activity_events_immutable BEFORE UPDATE OR DELETE ON activity_events FOR EACH ROW EXECUTE FUNCTION mmos_local_activity_immutable()").execute_if(dialect="postgresql"))
    return events, delivery


def delivery_status(db, tables):
    import sqlalchemy as sa
    events, delivery = tables
    pending = delivery.c.delivered_at.is_(None)
    count = db.execute(sa.select(sa.func.count()).select_from(delivery).where(pending)).scalar_one()
    oldest = db.execute(sa.select(sa.func.min(events.c.created_at)).select_from(events.join(delivery)).where(pending)).scalar_one()
    delivered = db.execute(sa.select(sa.func.max(delivery.c.delivered_at))).scalar_one()
    return {"pending":count,"oldest_pending_at":oldest.isoformat() if oldest else None,
            "last_delivered_at":delivered.isoformat() if delivered else None}


def enqueue(db, tables, event):
    """Use the caller's business transaction. This function never commits."""
    validate_event(event)
    events, delivery = tables
    db.execute(events.insert().values(event_id=event["event_id"], payload=event,
               digest=hashlib.sha256(canonical(event).encode()).hexdigest(), created_at=datetime.now(timezone.utc)))
    db.execute(delivery.insert().values(event_id=event["event_id"], attempts=0))
    return event["event_id"]


class ActivityPublisher:
    """Retry unacknowledged events; multiple publishers are safe through collector dedupe."""
    def __init__(self, *, session_factory, tables, os_url, service_key, service, interval=30, http_client=None):
        import httpx
        self.session_factory, self.tables = session_factory, tables
        self.service, self.service_key = service, service_key
        self.http = http_client or httpx.Client(base_url=os_url.rstrip("/"), follow_redirects=False)
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None

    def publish_once(self):
        import sqlalchemy as sa
        events, delivery = self.tables
        now = datetime.now(timezone.utc)
        with self.session_factory() as db:
            rows = db.execute(sa.select(events.c.event_id, events.c.payload, delivery.c.attempts)
                .join(delivery).where(delivery.c.delivered_at.is_(None),
                    sa.or_(delivery.c.next_attempt_at.is_(None), delivery.c.next_attempt_at <= now))
                .order_by(events.c.created_at, events.c.event_id).limit(20)).all()
        if not rows:
            return 0
        ids = {row.event_id for row in rows}
        acknowledged = set()
        error = None
        try:
            response = self.http.post("/api/agent/activity", json={"events": [r.payload for r in rows]},
                headers={"Authorization": f"Bearer {self.service_key}"}, timeout=5)
            response.raise_for_status()
            ack = response.json()["acknowledged"]
            if not isinstance(ack, list) or not all(isinstance(i, str) for i in ack) or not set(ack).issubset(ids):
                raise ValueError("Invalid acknowledgement")
            acknowledged = set(ack)
            if acknowledged != ids:
                error = "partial_acknowledgement"
        except Exception as exc:
            # Never save URLs, credentials, response bodies or exception messages.
            error = type(exc).__name__[:64]
        with self.session_factory() as db:
            for row in rows:
                attempts = row.attempts + 1
                values = {"attempts": attempts, "last_error": None if row.event_id in acknowledged else error,
                          "next_attempt_at": None if row.event_id in acknowledged else now + timedelta(seconds=min(300, 2 ** min(attempts, 8)))}
                if row.event_id in acknowledged:
                    values["delivered_at"] = now
                db.execute(delivery.update().where(delivery.c.event_id == row.event_id,
                    delivery.c.delivered_at.is_(None)).values(**values))
            db.commit()
        return len(acknowledged)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="mmos-activity-delivery")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=6)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.publish_once()
            except Exception:
                # A database outage must not kill retries permanently.
                pass
            self.stop_event.wait(self.interval)


def install_orm_capture(*, metadata, service, actor_provider, included_tables, context_provider=lambda: None, rewrite_names=True):
    """Capture mapped and ORM bulk changes without trusting client creator/name fields.

    Call once per service. Explicit table inventory avoids logging caches and generated
    ingestion rows as if they were individual human business decisions.
    """
    import sqlalchemy as sa
    from sqlalchemy.orm import Session
    tables = define_tables(metadata)
    marker = f"activity_pending:{service}"

    def context():
        ctx = context_provider() or {}
        return ctx.get("request_id"), ctx.get("department")

    def persist(db, obj, table, verb, actor, fields):
        record_id = ":".join(str(getattr(obj, column.key)) for column in sa.inspect(obj).mapper.primary_key)
        request_id, department = context()
        enqueue(db, tables, make_event(service=service, actor=actor, action=f"{table}.{verb}",
            target_type=table, target_id=record_id, changed_fields=fields,
            request_id=request_id, department=department))

    @sa.event.listens_for(Session, "before_flush")
    def before(db, _ctx, _instances):
        pending = []
        for obj, verb in [(x,"create") for x in db.new] + [(x,"update") for x in db.dirty] + [(x,"delete") for x in db.deleted]:
            state = sa.inspect(obj)
            table = state.mapper.local_table.name
            if state.mapper.local_table.metadata is not metadata or table not in included_tables:
                continue
            if verb == "update" and not db.is_modified(obj, include_collections=False):
                continue
            actor = actor_snapshot(actor_provider())
            display = actor["name"] or actor["employee_code"] or actor["subject"]
            for field in (["created_by", "updated_by", "uploaded_by", "user_name"] if rewrite_names else []):
                if field in state.mapper.column_attrs and (verb == "create" or field == "updated_by" or state.attrs[field].history.has_changes()):
                    if isinstance(state.mapper.column_attrs[field].columns[0].type, sa.String):
                        setattr(obj, field, display)
            fields = [a.key for a in state.mapper.column_attrs if state.attrs[a.key].history.has_changes()]
            pending.append((obj, table, verb, actor, fields))
        db.info.setdefault(marker, []).extend(pending)

    @sa.event.listens_for(Session, "after_flush_postexec")
    def after(db, _ctx):
        for args in db.info.pop(marker, []):
            persist(db, *args)

    @sa.event.listens_for(Session, "after_rollback")
    def rollback(db):
        db.info.pop(marker, None)

    @sa.event.listens_for(Session, "do_orm_execute")
    def bulk(state):
        if not (state.is_update or state.is_delete):
            return
        statement = state.statement
        table = statement.table
        if table.name not in included_tables or table.metadata is not metadata:
            return
        # Sessions from another app/process test harness cannot use this inventory.
        actual = metadata.tables.get(table.name)
        if actual is None or state.session.get_bind(mapper=state.bind_mapper) is None:
            return
        if state.bind_mapper is not None and state.bind_mapper.local_table.metadata is not metadata:
            return
        ids = state.session.connection().execute(sa.select(*actual.primary_key.columns)
            .where(statement.whereclause if statement.whereclause is not None else sa.true())).all()
        actor = actor_snapshot(actor_provider())
        request_id, department = context()
        for identity in ids:
            enqueue(state.session, tables, make_event(service=service, actor=actor,
                action=f"{table.name}.{'delete' if state.is_delete else 'update'}",
                target_type=table.name, target_id=":".join(str(i) for i in identity),
                changed_fields=["bulk_operation"], request_id=request_id, department=department))
    return tables


def install_sqlite_capture(connection, *, service, actor_provider, included_tables, context_provider=lambda: None):
    """Install once during database initialization, before business transactions.

    Triggers cover direct SQL writes and enqueue in their exact transaction.
    Register the functions on EVERY connection that can write these tables.
    Values and raw documents never enter the event; only table and record ID.
    """
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS activity_events(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS activity_delivery(event_id TEXT PRIMARY KEY REFERENCES activity_events(event_id) ON DELETE RESTRICT,
          delivered_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, last_error TEXT);
        CREATE INDEX IF NOT EXISTS ix_activity_delivery_pending ON activity_delivery(delivered_at,next_attempt_at);
        CREATE TRIGGER IF NOT EXISTS activity_events_no_update BEFORE UPDATE ON activity_events BEGIN SELECT RAISE(ABORT,'Activity evidence is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS activity_events_no_delete BEFORE DELETE ON activity_events BEGIN SELECT RAISE(ABORT,'Activity evidence is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS activity_events_delivery AFTER INSERT ON activity_events BEGIN INSERT INTO activity_delivery(event_id) VALUES(NEW.event_id); END;
    """)
    def event_payload(table, verb, identity):
        context = context_provider() or {}
        return canonical(make_event(service=service() if callable(service) else service, actor=actor_provider(),
            action=f"{table}.{verb}", target_type=table, target_id=identity,
            request_id=context.get("request_id"), department=context.get("department"), changed_fields=["record"]))
    connection.create_function("mmos_activity_event", 3, event_payload)
    connection.create_function("mmos_activity_digest", 1, lambda payload: hashlib.sha256(payload.encode()).hexdigest())
    for table in included_tables:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", table):
            raise ValueError("Invalid table inventory")
        columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        keys = sorted([(row[5],row[1]) for row in columns if row[5]])
        if not columns or not keys:
            continue
        for operation, verb, source in [("INSERT","create","NEW"),("UPDATE","update","NEW"),("DELETE","delete","OLD")]:
            identity = " || ':' || ".join(f'CAST({source}."{key}" AS TEXT)' for _,key in keys)
            connection.execute(f'''CREATE TRIGGER IF NOT EXISTS "activity_{table}_{verb}" AFTER {operation} ON "{table}" BEGIN
                INSERT INTO activity_events(event_id,payload,digest,created_at)
                SELECT json_extract(payload,'$.event_id'),payload,mmos_activity_digest(payload),json_extract(payload,'$.occurred_at')
                FROM (SELECT mmos_activity_event('{table}','{verb}',{identity}) AS payload LIMIT 1);
                END''')
    connection.commit()


def enqueue_sqlite(connection, event):
    validate_event(event)
    payload = canonical(event)
    connection.execute("INSERT INTO activity_events(event_id,payload,digest,created_at) VALUES(?,?,?,?)",
        (event["event_id"], payload, hashlib.sha256(payload.encode()).hexdigest(), event["occurred_at"]))
    # Installed AFTER INSERT trigger creates the retry record in this same transaction.


class SQLiteActivityPublisher(ActivityPublisher):
    """Standard-library delivery for services without SQLAlchemy or httpx."""
    def __init__(self, *, connection_factory, os_url, service_key, service, interval=30, http_client=None):
        self.connection_factory = connection_factory
        self.os_url, self.service_key, self.service = os_url.rstrip("/"), service_key, service
        self.interval, self.http = interval, http_client
        self.stop_event, self.thread = threading.Event(), None

    def publish_once(self):
        now = datetime.now(timezone.utc)
        connection = self.connection_factory()
        try:
            rows = connection.execute("""SELECT e.event_id,e.payload,d.attempts FROM activity_events e
                JOIN activity_delivery d ON d.event_id=e.event_id WHERE d.delivered_at IS NULL
                AND (d.next_attempt_at IS NULL OR d.next_attempt_at<=?) ORDER BY e.created_at,e.event_id LIMIT 20""",(now.isoformat(),)).fetchall()
            if not rows:
                return 0
            ids = {row[0] for row in rows}
            acknowledged, error = set(), None
            try:
                body = {"events":[json.loads(row[1]) for row in rows]}
                if self.http:
                    response = self.http.post("/api/agent/activity",json=body,headers={"Authorization":f"Bearer {self.service_key}"},timeout=5)
                    response.raise_for_status()
                    result = response.json()
                else:
                    import urllib.request
                    class NoRedirect(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self, *args, **kwargs):
                            return None
                    request = urllib.request.Request(self.os_url+"/api/agent/activity",data=json.dumps(body).encode(),
                        headers={"Authorization":f"Bearer {self.service_key}","Content-Type":"application/json"},method="POST")
                    with urllib.request.build_opener(NoRedirect()).open(request,timeout=5) as response:
                        result = json.loads(response.read(64000))
                ack = result["acknowledged"]
                if not isinstance(ack,list) or not all(isinstance(value,str) for value in ack) or not set(ack).issubset(ids):
                    raise ValueError("Invalid acknowledgement")
                acknowledged = set(ack)
                if acknowledged != ids:
                    error = "partial_acknowledgement"
            except Exception as exc:
                error = type(exc).__name__[:64]
            for event_id, _, attempts in rows:
                delivered = event_id in acknowledged
                connection.execute("""UPDATE activity_delivery SET delivered_at=?,attempts=?,next_attempt_at=?,last_error=?
                    WHERE event_id=? AND delivered_at IS NULL""", (now.isoformat() if delivered else None, attempts+1,
                    None if delivered else (now+timedelta(seconds=min(300,2**min(attempts+1,8)))).isoformat(),
                    None if delivered else error,event_id))
            connection.commit()
            return len(acknowledged)
        finally:
            connection.close()
