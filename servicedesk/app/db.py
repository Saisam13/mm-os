"""Engine and session for the servicedesk database. Own database, own engine — never the MM
OS one. Portable across sqlite (dev/test, this machine has no Postgres) and Postgres
(production) because app/models.py uses only portable SQLAlchemy types.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_healthy() -> bool:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
