"""Multi-worker-safe rate limiting, shared through the one Postgres.

Replaces the in-process sliding-window deques that used to live in `routers/auth.py`
(PIN login) and `routers/tokens.py` (service-token minting). Those kept their budget in a
module-level dict, so every uvicorn worker or replica had its own counter and every limit
silently became N times more permissive -- which is exactly why the deployment was pinned to
`--workers 1`. A single shared table removes that pin: N workers share one budget.

Design -- a **fixed-window counter**, not a per-hit log:

  * One row per (bucket, window_key) in `rate_limits`. `window_key = epoch // window_seconds`,
    so every hit inside the same 60-second window increments the *same* row. The table can
    never grow faster than one row per active identity per window.
  * The increment is done with an **atomic conditional UPDATE** (`... WHERE count < limit`),
    so correctness does not depend on the worker count: two workers racing at the boundary
    serialize on the row lock and exactly one of them crosses it. No read-modify-write gap.
  * "Don't write-amplify under attack" is preserved: once a bucket is at its limit, the
    conditional UPDATE matches zero rows and we return "limited" **without writing anything**.
    An over-budget flood costs reads, never a growing table and never a commit of new data.

Portable to both SQLite (tests) and Postgres (production): plain Core UPDATE/INSERT and a
UNIQUE(bucket, window_key) constraint, no dialect-specific upsert syntax and no SAVEPOINT
(pysqlite's savepoint handling is unreliable without extra event wiring the frozen test
harness does not install).
"""
from __future__ import annotations

import time

from sqlalchemy import delete, insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .models import RateLimit


def check_rate_limit(
    db: OrmSession,
    *,
    bucket: str,
    limit: int,
    window_seconds: float,
    now: float | None = None,
) -> bool:
    """Record one hit against `bucket` and report whether it is now over budget.

    Returns True if the caller is rate-limited (this hit is NOT counted in that case, and
    nothing is written), False if the hit was accepted. `limit` hits are allowed per fixed
    window of `window_seconds`; the (limit+1)-th within the same window is refused.

    Commits its own small transaction so the counter is durable immediately and visible to
    every other worker. Callers run this before any other DB work, so the internal rollback
    on a first-hit race never discards anything the request had already staged.
    """
    now = time.time() if now is None else now
    window_key = int(now // window_seconds)

    # Fast path / steady state: increment in place, but only while still under budget. The
    # `count < limit` predicate is evaluated by the database under the row lock, so this is
    # atomic across workers -- no worker can push the counter past `limit`.
    res = db.execute(
        update(RateLimit)
        .where(
            RateLimit.bucket == bucket,
            RateLimit.window_key == window_key,
            RateLimit.count < limit,
        )
        .values(count=RateLimit.count + 1)
    )
    if res.rowcount and res.rowcount > 0:
        db.commit()
        return False

    # No row matched. Either this is the first hit of the window (no row yet), or the row
    # exists and is already at the limit. Try to create the first-hit row.
    try:
        db.execute(insert(RateLimit).values(bucket=bucket, window_key=window_key, count=1))
        db.commit()
        return False
    except IntegrityError:
        # A row already exists for this (bucket, window_key): either a concurrent worker just
        # created it, or it is already at the limit. Roll back the failed insert (nothing else
        # is staged -- this runs first) and settle it with one more atomic conditional bump.
        db.rollback()
        res = db.execute(
            update(RateLimit)
            .where(
                RateLimit.bucket == bucket,
                RateLimit.window_key == window_key,
                RateLimit.count < limit,
            )
            .values(count=RateLimit.count + 1)
        )
        db.commit()
        # rowcount 0 -> the row is at/over the limit -> limited, and we wrote nothing.
        return not (res.rowcount and res.rowcount > 0)


def purge_expired_rate_limits(db: OrmSession, *, window_seconds: float = 60.0, keep_windows: int = 2) -> int:
    """Delete counter rows for windows old enough that no live limiter still reads them.

    A window is only ever consulted while `now` falls inside it, so anything older than the
    current window (plus a small margin) is dead weight. Called from agent.py's hourly purge
    loop alongside the revocation purge.
    """
    current_window = int(time.time() // window_seconds)
    result = db.execute(
        delete(RateLimit).where(RateLimit.window_key < current_window - keep_windows)
    )
    db.commit()
    return result.rowcount or 0
