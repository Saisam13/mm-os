"""Engine for the passwordmanager database — mirrors servicedesk/app/db.py's shape.

This shell defines no models and creates no tables: there is no vault schema yet (see
SECURITY.md). The engine exists only so `/healthz` can report DB connectivity the same way
every other MM OS service does, and so a future run can add a vault schema here without
touching config.py or main.py again.
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .config import settings

_cfg = settings()

_connect_args = {"check_same_thread": False} if _cfg.database_url.startswith("sqlite") else {}
engine = create_engine(_cfg.database_url, connect_args=_connect_args, future=True)


@event.listens_for(Engine, "connect")
def _sqlite_fk_pragma(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
    if _cfg.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def db_healthy() -> bool:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
