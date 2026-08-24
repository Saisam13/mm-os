"""Shared test harness. ORCHESTRATOR-OWNED — build agents must not edit this file.

There is no Postgres and no Docker on the build machine, so the whole suite runs on SQLite.
Two things have to be bridged for that to work against the frozen `app/models.py`:

  * `JSONB` has no SQLite compiler          -> rendered as `JSON`
  * SQLite hands back naive datetimes, while `app/deps.py` compares session expiry against
    an aware `datetime.now(timezone.utc)`   -> results are tagged UTC

Anything that is genuinely Postgres-only (JSONB containment operators, `pgcrypto`, the Alembic
migration against a real server, `docker compose up`) cannot be proven here. Mark those tests
`@pytest.mark.needs_postgres` and record them under `## Not done` in your handoff.

Use these fixtures rather than building your own engine:

    db                  a Session on a clean database, one per test
    client              TestClient(app) with get_db overridden onto `db`
    make_employee       Employee factory, unique code/email per call
    make_user           User factory (auth_type "google" or "local_pin")
    make_service        Service factory, returns (service, {role_key: ServiceRole})
    make_grant          Grant factory
    sign_in             puts a real Session row + session cookie on `client`
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── environment: must be set before anything under app/ is imported ───────────
_TMP = Path(tempfile.gettempdir()) / "mmos-test"
_TMP.mkdir(parents=True, exist_ok=True)

# Per-process paths. The acceptance script runs pytest several times, and CI or a developer can
# easily have two runs in flight at once; a single shared SQLite file meant one session's
# drop_all/create_all tore down another's tables mid-query, producing SQLAlchemy errors that
# looked like real failures and vanished on re-run.
_DB_PATH = _TMP / f"mmos_test_{os.getpid()}.db"
_KEY_PATH = _TMP / f"mmos_test_signing_key_{os.getpid()}.pem"

os.environ.setdefault("MMOS_DATABASE_URL", f"sqlite+pysqlite:///{_DB_PATH.as_posix()}")
os.environ.setdefault("MMOS_SIGNING_KEY_PATH", str(_KEY_PATH))
os.environ.setdefault("MMOS_ENVIRONMENT", "test")
os.environ.setdefault("MMOS_NETWORK_MODE", "public")   # NetworkGate off; test it explicitly instead
os.environ.setdefault("MMOS_COOKIE_SECURE", "false")   # TestClient speaks http
os.environ.setdefault("MMOS_COOKIE_DOMAIN", "")        # host-only cookie, so testserver keeps it
os.environ.setdefault("MMOS_GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("MMOS_GOOGLE_CLIENT_SECRET", "test-client-secret")

import pytest  # noqa: E402
from sqlalchemy import DateTime, delete  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.dialects.sqlite.base import SQLiteDialect  # noqa: E402
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


# The pysqlite driver overrides DateTime in its own colspecs, so subclass whatever is
# actually in force rather than the base sqlite DATETIME.
_DateTimeImpl = SQLiteDialect_pysqlite.colspecs.get(
    DateTime, SQLiteDialect.colspecs.get(DateTime)
)


class _UtcDateTime(_DateTimeImpl):
    """SQLite stores no offset; app code compares against aware UTC. Tag it on the way out."""

    def result_processor(self, dialect, coltype):
        inner = super().result_processor(dialect, coltype)

        def process(value):
            dt = inner(value) if inner is not None else value
            if isinstance(dt, datetime) and dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        return process

    def bind_processor(self, dialect):
        inner = super().bind_processor(dialect)

        def process(value):
            if isinstance(value, datetime) and value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return inner(value) if inner is not None else value

        return process


SQLiteDialect.colspecs = {**SQLiteDialect.colspecs, DateTime: _UtcDateTime}
SQLiteDialect_pysqlite.colspecs = {**SQLiteDialect_pysqlite.colspecs, DateTime: _UtcDateTime}

from sqlalchemy import event  # noqa: E402

from app import models  # noqa: E402

from app.db import SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_pin, new_session_token, session_expiry  # noqa: E402


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """WAL plus a generous busy timeout.

    `app/db.py`'s `db_healthy()` opens a *second* connection to the same file, and `/healthz`
    calls it while a test's write transaction is still open. On SQLite's default rollback
    journal that is a writer blocking a reader, and the default 5-second busy timeout can be
    exceeded on a loaded machine -- surfacing as `OperationalError: database is locked`, which
    reads exactly like a flaky test. WAL lets the reader proceed against the last committed
    snapshot instead of waiting.
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=15000")
    cur.close()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "needs_postgres: requires a real Postgres server; skipped on the build machine"
    )


@pytest.fixture(scope="session", autouse=True)
def _schema():
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    yield
    models.Base.metadata.drop_all(engine)
    engine.dispose()
    for leftover in (_DB_PATH, _KEY_PATH):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass  # Windows can hold the file briefly; a stale scratch file is harmless.


@pytest.fixture()
def db(_schema):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        for table in reversed(models.Base.metadata.sorted_tables):
            session.execute(delete(table))
        session.commit()
        session.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── factories ────────────────────────────────────────────────────────────────
@pytest.fixture()
def make_employee(db):
    def _make(**kw):
        n = uuid.uuid4().hex[:6]
        emp = models.Employee(
            employee_code=kw.pop("employee_code", f"MM{n[:4]}"),
            full_name=kw.pop("full_name", "Test Person"),
            work_email=kw.pop("work_email", f"test-{n}@m-mines.com"),
            hr_department=kw.pop("hr_department", "Information Technology"),
            division=kw.pop("division", "Corporate"),
            job_title=kw.pop("job_title", "Engineer"),
            band=kw.pop("band", "L3"),
            **kw,
        )
        db.add(emp)
        db.commit()
        return emp

    return _make


@pytest.fixture()
def make_user(db, make_employee):
    def _make(employee=None, **kw):
        employee = employee or make_employee()
        auth_type = kw.pop("auth_type", "google")
        # models.py enforces: google users must have login_email, PIN users must have pin_hash.
        if auth_type == "google":
            kw.setdefault("login_email", employee.work_email)
        else:
            kw.setdefault("pin_hash", hash_pin(kw.pop("pin", "1234")))
        user = models.User(employee_id=employee.id, auth_type=auth_type, **kw)
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture()
def make_service(db):
    def _make(slug=None, roles=("viewer", "admin"), **kw):
        slug = slug or f"svc-{uuid.uuid4().hex[:6]}"
        service = models.Service(
            slug=slug,
            name=kw.pop("name", slug.upper()),
            base_url=kw.pop("base_url", f"https://{slug}.m-mines.com"),
            **kw,
        )
        db.add(service)
        db.commit()
        made = {}
        for key in roles:
            r = models.ServiceRole(service_id=service.id, key=key, name=key.title())
            db.add(r)
            made[key] = r
        db.commit()
        return service, made

    return _make


@pytest.fixture()
def make_grant(db):
    def _make(user, service, role, **kw):
        grant = models.Grant(
            user_id=user.id, service_id=service.id, service_role_id=role.id, **kw
        )
        db.add(grant)
        db.commit()
        return grant

    return _make


@pytest.fixture()
def sign_in(db, client):
    """Create a real Session row and attach its cookie to `client`. Returns the Session."""

    def _sign_in(user):
        raw, token_hash = new_session_token()
        row = models.Session(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=session_expiry(),
        )
        db.add(row)
        db.commit()
        from app.config import settings

        client.cookies.set(settings().cookie_name, raw)
        return row

    return _sign_in
