"""Authenticated, idempotent service collection and scope-filtered activity history."""
import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import or_, select

from ..activity_contract import canonical, validate_event
from ..authorization import capability_scopes, scope_query
from ..db import get_db
from ..deps import audit, require_capability, require_revocation_key
from ..models import Department, ServiceActivity, User

router = APIRouter()


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[dict] = Field(min_length=1, max_length=20)


@router.post("/api/agent/activity")
async def collect_activity(request: Request, service=Depends(require_revocation_key), db=Depends(get_db)):
    if service.slug == "mmos":
        raise HTTPException(403, {"error":"reserved_activity_source"})
    # Disabled services may drain existing evidence, but cannot mint access.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 256000:
            raise HTTPException(413, {"error": "activity_batch_too_large"})
    try:
        batch = Batch.model_validate_json(raw)
        for event in batch.events:
            validate_event(event)
            if event["service"] != service.slug:
                raise ValueError("Service mismatch")
    except (ValueError, TypeError, KeyError, OverflowError):
        raise HTTPException(422, {"error": "invalid_activity_batch"})
    ack = []
    for event in batch.events:
        digest = hashlib.sha256(canonical(event).encode()).hexdigest()
        key = (ServiceActivity.source_service_id == service.id, ServiceActivity.event_id == event["event_id"])
        existing = db.scalar(select(ServiceActivity).where(*key))
        if existing is not None:
            if existing.digest != digest:
                db.rollback()
                raise HTTPException(409, {"error": "activity_event_conflict"})
            ack.append(event["event_id"])
            continue
        department = db.scalar(select(Department).where(Department.name == event["department"])) if event["department"] else None
        actor = event["actor"]
        row = ServiceActivity(event_id=event["event_id"], source_service_id=service.id,
            service_slug=service.slug, actor_subject=actor["subject"], actor_name=actor["name"],
            actor_code=actor["employee_code"], department_id=department.id if department else None,
            action=event["action"], target_type=event["target"]["type"], target_id=event["target"]["id"],
            outcome=event["outcome"], restricted=event["restricted"],
            occurred_at=datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")), payload=event, digest=digest)
        # An upsert keeps the whole batch in one transaction, including SQLite's
        # legacy transaction mode where a first SAVEPOINT can otherwise commit early.
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        values = {column.name: getattr(row, column.name) for column in ServiceActivity.__table__.columns
                  if column.name not in {"id", "received_at"}}
        db.execute(insert(ServiceActivity).values(**values).on_conflict_do_nothing(
            index_elements=["source_service_id", "event_id"]))
        existing = db.scalar(select(ServiceActivity).where(*key))
        if existing is None or existing.digest != digest:
            db.rollback()
            raise HTTPException(409, {"error": "activity_event_conflict"})
        ack.append(event["event_id"])
    db.commit()
    return {"acknowledged": ack}


@router.get("/api/admin/activity")
def list_activity(service: str | None = None, actor: str | None = None, action: str | None = None,
                  target: str | None = None, after: datetime | None = None, before: datetime | None = None,
                  offset: int = Query(0, ge=0, le=100000), limit: int = Query(50, ge=1, le=200),
                  reader: User = Depends(require_capability("activity.view", allow_scoped=True)), db=Depends(get_db)):
    query = scope_query(db, reader, "activity.view", select(ServiceActivity), ServiceActivity.department_id)
    # Private activity needs an explicit row even for platform administrators.
    scopes = capability_scopes(db, reader, "activity.private.view")
    if None not in scopes:
        query = query.where(or_(ServiceActivity.restricted.is_(False), ServiceActivity.actor_subject == reader.subject,
                               ServiceActivity.department_id.in_(scopes)))
    for column, value in [(ServiceActivity.service_slug, service), (ServiceActivity.action, action), (ServiceActivity.target_id, target)]:
        if value:
            query = query.where(column == value)
    if actor:
        query = query.where(or_(ServiceActivity.actor_subject == actor, ServiceActivity.actor_code == actor))
    for value in [after, before]:
        if value is not None and value.tzinfo is None:
            raise HTTPException(422, {"error": "timezone_required"})
    if after:
        query = query.where(ServiceActivity.occurred_at >= after)
    if before:
        query = query.where(ServiceActivity.occurred_at <= before)
    rows = db.scalars(query.order_by(ServiceActivity.occurred_at.desc(), ServiceActivity.id.desc()).offset(offset).limit(limit + 1)).all()
    audit(db, action="activity.history_read", actor_user_id=reader.id, target_type="activity", filters={"service":service,"actor":actor,"action":action,"target":target}, count=min(len(rows),limit))
    db.commit()
    return {"events": [dict(r.payload, received_at=r.received_at.isoformat(), attribution="service_reported") for r in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}
