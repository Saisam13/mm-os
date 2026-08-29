"""The DB-backed, multi-worker-safe rate limiter (app/ratelimit.py, models.RateLimit).

Proves the three properties the L1/L2 phase relies on to drop the old `--workers 1` pin:
a window's budget is a hard cap that writes nothing once exceeded, a fresh window resets it,
and two independent sessions (standing in for two uvicorn workers) share one budget through
the one database rather than each keeping its own.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import RateLimit
from app.ratelimit import check_rate_limit


def _count(db, bucket: str, window_key: int) -> int:
    return db.scalar(
        select(RateLimit.count).where(
            RateLimit.bucket == bucket, RateLimit.window_key == window_key
        )
    )


def test_over_limit_in_one_window_is_refused_and_writes_nothing_past_the_cap(db):
    bucket = "pin:1.2.3.4"
    now = 1_000_000.0
    window_key = int(now // 60.0)

    # `limit` hits are accepted; every hit after that in the same window is refused.
    for _ in range(3):
        assert check_rate_limit(db, bucket=bucket, limit=3, window_seconds=60.0, now=now) is False
    for _ in range(5):
        assert check_rate_limit(db, bucket=bucket, limit=3, window_seconds=60.0, now=now) is True

    # The counter never climbs past the cap: over-budget hits write nothing.
    assert _count(db, bucket, window_key) == 3
    # And exactly one row exists for this (bucket, window) -- a fixed-window counter, not a log.
    assert db.scalar(
        select(func.count()).select_from(RateLimit).where(RateLimit.bucket == bucket)
    ) == 1


def test_a_new_window_resets_the_budget(db):
    bucket = "token:some-user"
    first = 2_000_000.0
    for _ in range(2):
        assert check_rate_limit(db, bucket=bucket, limit=2, window_seconds=60.0, now=first) is False
    assert check_rate_limit(db, bucket=bucket, limit=2, window_seconds=60.0, now=first) is True

    # One full window later -> a different window_key -> a fresh budget.
    later = first + 60.0
    assert int(later // 60.0) != int(first // 60.0)
    assert check_rate_limit(db, bucket=bucket, limit=2, window_seconds=60.0, now=later) is False


def test_two_independent_sessions_share_one_budget(db):
    """Simulates two workers/replicas: separate OrmSessions on the same database must draw
    from a single shared budget, not one each (the whole point of moving off the in-process
    deque that forced --workers 1)."""
    bucket = "pin:9.9.9.9"
    now = 3_000_000.0

    other = SessionLocal()
    try:
        # Worker A takes one hit, worker B takes the second -- together they reach the cap.
        assert check_rate_limit(db, bucket=bucket, limit=2, window_seconds=60.0, now=now) is False
        assert check_rate_limit(other, bucket=bucket, limit=2, window_seconds=60.0, now=now) is False

        # The third hit from EITHER worker is refused: the budget is shared, not per-session.
        assert check_rate_limit(other, bucket=bucket, limit=2, window_seconds=60.0, now=now) is True
        assert check_rate_limit(db, bucket=bucket, limit=2, window_seconds=60.0, now=now) is True

        assert _count(db, bucket, int(now // 60.0)) == 2
    finally:
        other.rollback()
        other.close()
