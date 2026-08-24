"""Helper for scripts/verify/acceptance.sh's "seed dry-run" local-mode check.

Runs `app.seed`'s real dry-run diff (backend/app/seed.py::main, no --commit) against a
throwaway SQLite database instead of the Postgres `MMOS_DATABASE_URL` normally requires, using
the exact same JSONB/UTC-datetime bridge `backend/tests/conftest.py` (orchestrator-owned)
already applies for the whole backend test suite. Not a new test framework -- this only
reuses that bridge so the real spreadsheet importer's dry-run path is provable on a machine
with no Postgres, which is every build machine per docs/09's sprint amendments.

Never writes to the real database, never calls --commit, never modifies the source xlsx.
Exit code mirrors app.seed.main()'s (0 on a clean dry run).
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

# A scratch db distinct from the real test-suite db (backend/tests/conftest.py points at a
# fixed path) so this can run alongside `pytest` without fighting over the same file.
_scratch = Path(tempfile.gettempdir()) / f"mmos-seed-dry-run-{uuid.uuid4().hex[:8]}.db"
os.environ["MMOS_DATABASE_URL"] = f"sqlite+pysqlite:///{_scratch.as_posix()}"
os.environ.setdefault("MMOS_SIGNING_KEY_PATH", str(Path(tempfile.gettempdir()) / "mmos-seed-dry-run-key.pem"))
os.environ.setdefault("MMOS_ENVIRONMENT", "test")
os.environ.setdefault("MMOS_GOOGLE_CLIENT_ID", "acceptance-script")
os.environ.setdefault("MMOS_GOOGLE_CLIENT_SECRET", "acceptance-script")

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import conftest  # noqa: E402,F401  -- orchestrator-owned; only imported, never edited, for its
                  # JSONB->JSON / naive-to-UTC-datetime SQLite compiler shims (see that file's
                  # own docstring). Importing it does not run any test or fixture.

from app import models  # noqa: E402
from app.db import engine  # noqa: E402
from app.seed import main  # noqa: E402

models.Base.metadata.create_all(engine)

xlsx = sys.argv[1] if len(sys.argv) > 1 else None
argv = ["--xlsx", xlsx] if xlsx else []
try:
    rc = main(argv)
finally:
    try:
        engine.dispose()
        _scratch.unlink(missing_ok=True)
    except OSError:
        pass

raise SystemExit(rc)
