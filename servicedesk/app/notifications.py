"""Email notifications via Workspace SMTP — docs/09-service-desk deliverable #6: submitted,
proposal ready, decision, resolved. One module, one place the wording lives.

A failed send must never fail the transition it rides along with. `notify()` never raises;
it swallows SMTP errors and appends them to an in-memory queue that the IT agent console
surfaces (`failed_notifications()`), and `retry_failed()` can be called (from the heartbeat
tick, in production) to flush it. There is no message broker here — v1 scope, ~74 people,
an in-memory list is enough and is explicitly allowed to be lost on restart.
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage

from .config import settings

TEMPLATES = {
    "submitted": ("[{ref}] Request submitted", "Your request \"{title}\" ({ref}) was submitted and is awaiting IT review."),
    "proposal_ready": ("[{ref}] Proposal ready", "IT has proposed scope and cost for \"{title}\" ({ref}). It now needs your manager's decision."),
    "decision": ("[{ref}] Decision: {decision}", "\"{title}\" ({ref}) was {decision} by {approver_code}.{comment_line}"),
    "resolved": ("[{ref}] Resolved", "\"{title}\" ({ref}) has been marked resolved. Reply within 7 days to reopen it."),
}


@dataclass
class FailedNotification:
    to: str
    event_type: str
    ref: str
    error: str
    context: dict = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_failed: list[FailedNotification] = []


def failed_notifications() -> list[FailedNotification]:
    return list(_failed)


def clear_failed_notifications() -> None:
    """Test seam."""
    _failed.clear()


def _send(to: str, subject: str, body: str) -> None:
    cfg = settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_user or "servicedesk@m-mines.com"
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if cfg.smtp_user:
            smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(msg)


def notify(event_type: str, to_email: str | None, **context) -> None:
    cfg = settings()
    if not cfg.notifications_enabled or not to_email:
        return
    subject_tpl, body_tpl = TEMPLATES[event_type]
    context.setdefault("comment_line", f" ({context['comment']})" if context.get("comment") else "")
    subject = subject_tpl.format(**context)
    body = body_tpl.format(**context)
    try:
        _send(to_email, subject, body)
    except Exception as exc:  # pragma: no cover - no SMTP server in this sandbox
        _failed.append(FailedNotification(
            to=to_email, event_type=event_type, ref=context.get("ref", ""), error=str(exc), context=context,
        ))


def retry_failed() -> None:  # pragma: no cover - exercised only with a real SMTP server
    pending = list(_failed)
    _failed.clear()
    for item in pending:
        notify(item.event_type, item.to, **item.context)
