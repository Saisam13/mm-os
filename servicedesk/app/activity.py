"""Capture domain changes inside their transactions, preserving verified actor snapshots."""
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .activity_contract import ActivityPublisher, SAFE_VALUES, actor_snapshot, define_tables, enqueue, make_event
from .config import settings
from .models import Base, Ticket

TABLES = define_tables(Base.metadata)
DOMAIN = {"tickets", "proposals", "decisions", "comments", "events", "departments", "local_roles", "sla_configs", "approval_rules", "approval_defaults"}
SNAPSHOTS = {"tickets": ("requester_sub", "requester_name", "requester_code"),
             "proposals": ("author_sub", "author_name", "author_code"),
             "comments": ("author_sub", "author_name", "author_code"),
             "decisions": ("approver_sub", "approver_name", "approver_code"),
             "events": ("actor_sub", "actor_name", "actor_code")}


@sa.event.listens_for(Session, "before_flush")
def capture_changes(db, _context, _instances):
    request = db.info.get("activity_request")
    principal = getattr(request.state, "activity_actor", None) if request else db.info.get("activity_actor")
    if principal is None:
        return  # Seed/system jobs must opt in with an explicit system principal.
    pending = []
    for obj, verb in [(x, "create") for x in db.new] + [(x, "update") for x in db.dirty] + [(x, "delete") for x in db.deleted]:
        table = getattr(getattr(obj, "__table__", None), "name", "")
        if table not in DOMAIN:
            continue
        if verb == "update" and not db.is_modified(obj, include_collections=False):
            continue
        actor = actor_snapshot(principal)
        fields = SNAPSHOTS.get(table)
        if verb == "create" and fields and getattr(obj, fields[0], None) == actor["subject"]:
            setattr(obj, fields[1], actor["name"])
            setattr(obj, fields[2], actor["employee_code"])
        changes, changed = {}, []
        for attr in sa.inspect(obj).mapper.column_attrs:
            history = sa.inspect(obj).attrs[attr.key].history
            if history.has_changes() or verb == "delete":
                changed.append(attr.key)
                if attr.key in SAFE_VALUES:
                    before = history.deleted[0] if history.deleted else getattr(obj, attr.key, None) if verb == "delete" else None
                    after = history.added[0] if history.added else None
                    if all(v is None or type(v) in {str, int, bool} for v in [before, after]):
                        changes[attr.key] = {"before": before, "after": after}
        pending.append((obj, table, verb, actor, changed, changes))
    db.info.setdefault("pending_activity", []).extend(pending)


@sa.event.listens_for(Session, "after_flush_postexec")
def persist_changes(db, _context):
    pending = db.info.pop("pending_activity", [])
    request = db.info.get("activity_request")
    for obj, table, verb, actor, changed, changes in pending:
        record_id = getattr(obj, "id", None) or getattr(obj, "sub", None)
        if record_id is None:
            raise ValueError("Activity requires a stable record ID")
        department = obj.requester_dept if isinstance(obj, Ticket) else None
        if getattr(obj, "ticket_id", None):
            ticket = db.get(Ticket, obj.ticket_id)
            department = ticket.requester_dept if ticket else None
        # Central activity deliberately contains no ticket/comment/proposal content.
        # All SD business metadata requires explicit private-history authority or own actor.
        enqueue(db, TABLES, make_event(service="servicedesk", actor=actor, action=f"{table}.{verb}",
            target_type=table, target_id=record_id, changes=changes, changed_fields=changed,
            restricted=True, department=department,
            request_id=getattr(request.state, "activity_request_id", None) if request else None))


@sa.event.listens_for(Session, "after_rollback")
def discard_rollback(db):
    db.info.pop("pending_activity", None)


def publisher():
    from .db import SessionLocal
    cfg = settings()
    return ActivityPublisher(session_factory=SessionLocal, tables=TABLES, os_url=cfg.mmos_os_url,
                             service_key=cfg.mmos_service_key, service="servicedesk")


async def observe_request(request, call_next):
    request.state.activity_request_id = uuid.uuid4().hex
    try:
        response = await call_next(request)
    except Exception:
        principal = getattr(request.state, "activity_actor", None)
        if principal is not None and request.url.path.startswith("/api/"):
            from .db import SessionLocal
            with SessionLocal() as db:
                enqueue(db,TABLES,make_event(service="servicedesk",actor=principal,action="http.failed",
                    target_type="endpoint",target_id=request.url.path,outcome="failed",request_id=request.state.activity_request_id))
                db.commit()
        raise
    principal = getattr(request.state, "activity_actor", None)
    if principal is not None and request.url.path.startswith("/api/"):
        # Mutations already persist through flush listeners. Independently record denials,
        # failures and authenticated reads, with no query string/body/exception content.
        if response.status_code >= 400 or request.method == "GET":
            from .db import SessionLocal
            outcome = "denied" if response.status_code in {401,403} else "failed" if response.status_code >= 400 else "success"
            with SessionLocal() as db:
                enqueue(db, TABLES, make_event(service="servicedesk", actor=principal,
                    action="http.read" if outcome == "success" else f"http.{outcome}",
                    target_type="endpoint", target_id=request.url.path, outcome=outcome,
                    restricted=True, request_id=request.state.activity_request_id))
                db.commit()
    response.headers["x-request-id"] = request.state.activity_request_id
    return response
