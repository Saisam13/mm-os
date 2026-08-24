# Service Desk

MiniMines' support and automation-request service. Own FastAPI service, own database
(`servicedesk`), own container — not part of the MM OS codebase. Full spec: `docs/07-service-desk.md`.

## Run

```bash
cd servicedesk
../backend/.venv/Scripts/python.exe -m pip install -r requirements.txt   # first time only
../backend/.venv/Scripts/python.exe -m app.seed                          # ensures the schema exists (dev/sqlite)
../backend/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8010 --app-dir .
```

Frontend, in a second shell (dev server with API proxy — see `frontend/vite.config.js`):

```bash
cd servicedesk/frontend
npm install
npm run dev
```

For production, `npm run build` in `frontend/` produces `frontend/dist`, which
`app/main.py` mounts and serves from the same port as the API — the same pattern
`backend/app/main.py` uses for the MM OS shell.

## Migrate

```bash
cd servicedesk
../backend/.venv/Scripts/python.exe -m alembic upgrade head
```

`alembic/env.py` reads `DATABASE_URL` from the same `Settings` the app uses, so this runs
unchanged against SQLite (dev/test, used throughout this repo's own test suite) or Postgres
(production) — `app/models.py` only uses portable SQLAlchemy types (`Uuid`, `JSON`), never
the Postgres-only `UUID`/`JSONB` types the frozen MM OS `backend/app/models.py` needs shims
for.

## Seed

There is no data seed — Service Desk starts empty; `app/seed.py` only ensures the schema
exists for local/dev use. The only "seed" people in this repo are `app.org_chart.SEED_PERSONAS`
(operator → supervisor → HOD → Apex), used by the tests, `app/org_chart.py`'s default
approver-lookup fixture, and the `/_dev/token` manual-testing endpoint below.

## Manually verifying it (no live MM OS to sign in through)

```bash
curl -X POST http://localhost:8010/_dev/token -H 'Content-Type: application/json' \
     -d '{"persona":"operator","roles":["requester"]}'
```

Returns `{"token": "..."}` — use it as `Authorization: Bearer <token>`, or open the frontend
and pick a persona on the sign-in screen it shows (`frontend/src/DevSignIn.jsx`). This
endpoint 404s the instant `AUTH_MODE` is anything but `stub` (see `.env.example`), so it does
not exist against a real deployment.

## Tests

```bash
cd servicedesk
../backend/.venv/Scripts/python.exe -m pytest -q
```

31 tests, all passing, on SQLite. `tests/conftest.py` is this service's own harness — not
shared with `backend/tests/conftest.py`, which is MM OS's and frozen.

## State machines

Exactly as specified in `docs/07-service-desk.md`, enforced in `app/state_machine.py`
(`SUPPORT_TRANSITIONS`, `AUTOMATION_TRANSITIONS`) and by the API surface in
`app/routers/tickets.py`, `proposals.py`, `decisions.py`. An illegal move is `409
invalid_transition`, naming the current and attempted state.

**Support**

```
open ──▶ in_progress ──▶ waiting_on_requester ──▶ resolved ──▶ closed
   └──────────────▶ rejected (with reason)          ▲
                                                    └── reopened within 7 days
```

**Automation request**

```
draft
  └▶ submitted ──▶ it_review ──▶ proposal_ready ──▶ manager_review ──┬▶ approved ──▶ in_build ──▶ deployed ──▶ closed
                       │              ▲                             ├▶ changes_requested ──┐
                       │              └─────────────────────────────┘                      │
                       └▶ rejected (IT: not feasible)                └▶ rejected (manager: not funded)
```

v1 never persists a `draft` row: `POST /api/tickets` for an automation request creates it
directly in `submitted`, with the approver already computed — see
`handoff/a5-servicedesk.md` for how the two genuinely ambiguous branches in this diagram
(`changes_requested`'s loop-back target, and whether `rejected` hangs off
`changes_requested` or off `manager_review` directly) were resolved, and why.
