# A1 · Identity and People

Post-handoff note (orchestrator, 24 Aug 2026): after this file was first written, the
orchestrator (a) added the CSP header to `middleware.py` (closing `docs/11-security-review.md`
finding 4 — frozen-spine, not touched here), (b) bumped `python-jose`, `fastapi`
(which pulls a major-version `starlette` bump), `cryptography`, and `python-multipart` for real
CVEs found by the same review (`backend/requirements.txt` is orchestrator-owned; nothing here
changed a pin), and (c) landed `docs/11-security-review.md` itself. All 75 of this repo's
backend tests, including every one in this file, pass unmodified on the bumped versions.

## Delivered

- **`backend/alembic/`** — `alembic.ini`, `alembic/env.py` (pulls the URL from
  `MMOS_DATABASE_URL` via `app.config.settings()`, never duplicates it), `alembic/script.py.mako`,
  and one hand-written initial migration `alembic/versions/0001_initial_schema.py`. It mirrors
  `backend/app/models.py` column-for-column and layers in the CHECK constraints and partial
  indexes from `docs/02-data-model.md` that `models.py` doesn't itself declare (the partial
  index on `sessions`, the `audit_log` DESC/composite indexes, `employees.manager_id`).

- **`backend/app/routers/auth.py`**
  - `GET /api/auth/google/start` — PKCE + `state` packed into a short-lived (10 min),
    HMAC-signed cookie (`mmos_oauth`); `hd` sent as a hint on the authorize URL.
  - `GET /api/auth/google/link/start` — **new**, requires an authenticated session. Starts
    the same OIDC dance with no `hd` hint, tagging the oauth cookie `purpose=link` plus the
    linking user's id.
  - `GET /api/auth/google/callback` — single callback for both flows (Google only allows one
    registered redirect URI), branching on the oauth cookie's `purpose`. Always: exchanges the
    code, fetches Google's JWKS, verifies the `id_token`'s **signature** plus `aud`/`iss`/`exp`
    (via `jose.jwt.decode`) and `email_verified`. `hd` is checked conditionally — see
    `## Deviations`. Both Google calls go through `httpx.post`/`httpx.get` so tests mock them;
    no live Google call anywhere.
  - `POST /api/auth/pin` — 5 attempts / 15 min lock via `users.failed_pin_attempts` /
    `locked_until`; one generic error for wrong code, wrong PIN, and "still locked." Checks
    `pin_hash` directly rather than `auth_type == 'local_pin'` — see `## Deviations`.
  - `POST /api/auth/logout` — revokes the session row, clears the cookie.
  - Every branch audited: `login.google`, `login.google.denied`, `login.google.linked`,
    `login.pin`, `login.pin.failed`, `logout`, all with `client_ip(request)`.
  - Cookie helper omits the `Domain` attribute entirely when `MMOS_COOKIE_DOMAIN` is empty
    (session cookie and the internal oauth-state cookie alike).

- **`backend/app/routers/me.py`** — `GET /api/me` in the exact shape from `docs/03`. Grants are
  filtered server-side to live (unexpired) grants on active services; the client is never sent
  a service it lacks a grant for.

- **`backend/app/routers/people.py`** — `GET/POST/PATCH /api/admin/employees`,
  `POST /api/admin/employees/import` (dry run by default, `?commit=true` to apply — reuses
  `app.seed`'s diff engine so the CLI and the admin upload share one implementation),
  `GET /api/admin/users`, `PATCH /api/admin/users/{id}` (deactivating flips `is_active`, revokes
  every live session, and inserts a `revocations` row, all in one transaction), and
  `POST /api/admin/users/{id}/pin` (issue/reset/clear; the raw PIN is returned once; no longer
  gated on `auth_type` — see `## Deviations`).

- **`backend/app/seed.py`** — `python -m app.seed --xlsx <path> [--commit]`. Dry-run diff
  (new/changed/missing/conflicting), second-pass `manager_id` resolution from division+band,
  the ERP-access prose columns printed as a **proposed grants report** (never written as
  grants), idempotent seeding of the 5 services + roles and the one platform admin, and — per
  the owner's ruling — every new employee is seeded `auth_type='local_pin'` regardless of
  whether they have a Work Email.

- **Per-IP rate limit on `POST /api/auth/pin`** (`backend/app/routers/auth.py`), closing
  `docs/11-security-review.md` finding 2 (HIGH — "no throttle beyond per-account lockout, and
  employee codes are guessable"). `_pin_rate_limited()` is the same in-process sliding-window
  pattern as `routers/tokens.py`'s existing 60/min/user limiter, keyed by `client_ip(request)`
  (never a re-implementation of IP extraction) instead of by user, since the caller isn't
  authenticated yet at this point. Checked as the very first thing in `pin_login`, before any
  DB lookup or attempt-counting, so a throttled request never touches `failed_pin_attempts`
  and never distinguishes a valid employee code from an invalid one (no query has run either
  way). No audit row is written on the throttled path, matching `tokens.py`'s own limiter
  exactly — otherwise a sustained flood past the limit would still cost one `audit_log` insert
  + commit per request, turning the fix itself into a write-amplification DoS. Both defences
  now coexist as designed: per-IP bounds the attacker's overall rate, per-user still locks an
  individual account after 5 wrong PINs.

- **`backend/tests/test_identity.py`** — 30 tests: 30 pass, 1 (`needs_postgres`) self-skips.
  Covers every acceptance bullet in the brief, the linking flow, both `hd` branches, and the
  three throttle scenarios (burst gets throttled; a throttled attempt leaves
  `failed_pin_attempts` unchanged; a legitimate user on a different IP is unaffected). An
  autouse fixture (`_reset_pin_rate_limiter`) clears the limiter's module-level state around
  every test — unlike `tokens.py`'s limiter, which is naturally isolated per test because it's
  keyed by a fresh random user id each time, this one is keyed by IP and most tests share the
  same TestClient-reported address, so without the reset, throttle tests could leak state into
  unrelated ones later in the same run.

## Deviations

- **The employee sheet has 73 rows, not 74.** The brief, `docs/02`, and `docs/09`'s definition
  of done all say 74. Confirmed by opening
  `C:\Users\Anura\OneDrive\Desktop\Erp Imp\Employee_Role_Access_Mapping.xlsx` directly (read-only,
  never copied): 73 data rows, 49 `gmail.com` addresses, 23 `m-mines.com`, 1 blank. **The owner
  has ruled the docs are wrong** (`handoff/ORCHESTRATOR.md` "Owner decisions taken mid-run") —
  every count here uses 73.

- **Auth model rewritten mid-run on an explicit owner ruling — this modifies the locked
  `docs/04-auth-flow.md` "Google Workspace OIDC, locked to `hd=m-mines.com`" decision.** My
  original implementation classified `auth_type` by email domain at import time (corporate →
  `google`, everything else → `local_pin`). The owner rejected that shape entirely in favor of:

  1. **All 73 employees get a local PIN account on import, corporate addresses included.**
     `seed.py` no longer looks at the email at all when deciding `auth_type` — every new
     employee is `local_pin` with a placeholder `pin_hash` and `pin_set_at IS NULL` ("PIN not
     yet issued"). Employee-code + PIN is the universal day-one path.
  2. **Google sign-in stays open to any address, personal `gmail.com` included** — subject to
     the conditional `hd` rule below.
  3. **New: a self-service Google-linking flow** (`GET /api/auth/google/link/start` +
     the shared `/google/callback`). It attaches a verified Google identity to **the currently
     authenticated user, and only ever that user** — the target is resolved by reading the live
     `mmos_session` cookie inside the callback (`current_session`/`current_user` called
     directly), never from the `id_token`'s claims or anything else the client sent. On success:
     `login_email` is set to the verified address, `auth_type` flips to `'google'`, and
     **`pin_hash` is left untouched** so PIN login keeps working afterward.
  4. **`pin_login`'s success check now keys off `pin_hash` being present and correct, not
     `auth_type == 'local_pin'`** — otherwise a user who links Google would lose PIN login the
     moment `auth_type` flips, which is exactly what the owner ruled against.
  5. **`hd == google_hosted_domain` is now conditional, enforced only for auto-provisioning.**
     In `_complete_google_login`: if the verified email matches an existing user's
     `login_email`, the sign-in succeeds regardless of domain (that link was established from
     an authenticated PIN session, which is what makes trusting a personal address safe here).
     If no user matches, `hd` is checked before falling through to `unknown_user` — MM OS still
     never auto-provisions an account on login either way, but a non-corporate identity that
     nobody has linked gets the more specific `hd_mismatch` (matching the original architecture
     decision's own acceptance test), while a corporate identity that simply isn't provisioned
     yet gets `unknown_user`. Tested both ways: `test_google_login_allows_linked_personal_gmail_regardless_of_hd`
     and `test_google_login_rejects_unknown_gmail_address_via_hd_mismatch`.
  6. **`login_email` uniqueness on linking is enforced with a generic `409
     google_account_already_linked`**, checked proactively before touching the row (not left to
     the DB's unique-constraint error), and the message never names or otherwise identifies
     whose account the email is already on (`test_google_link_rejects_email_already_linked_to_another_user`
     asserts the address string itself doesn't appear in the response).
  7. **No `google_sub` column was added** — matching is on the verified email only, per
     instruction. See `## Contract objections` for why I think this is an acceptable, if
     imperfect, trade-off rather than something that needs the frozen schema changed.

  Trade-off the owner explicitly accepted (recorded in `handoff/ORCHESTRATOR.md`, repeating it
  here since it's security-relevant and belongs next to the code that implements it): for
  anyone signing in with a personal Google account, MFA is whatever that account's own 2FA is —
  it cannot be enforced from the Workspace admin console — and offboarding must be done by
  deactivating the user in MM OS, since disabling a corporate mailbox will not lock them out.

- `me.py`'s `health` field is a static `"unknown"` (commented in code) — no agent currently owns
  live health polling, so guessing `"up"` would be dishonest telemetry.
- `PATCH /api/admin/users/{id}` only accepts `is_active` and `is_platform_admin` in this pass —
  enough for the deactivation acceptance test. There is still no route to change `auth_type` or
  `login_email` directly (distinct from the self-service link flow above) — see `## Not done`.

## Contract objections

1. **`pin_required` CHECK vs. the "PIN not set" seeding rule.** `docs/02-data-model.md` says
   rows with no Work Email become `auth_type='local_pin'` users with **no PIN set**. But
   `models.py`'s own `pin_required` CHECK forbids `auth_type='local_pin' AND pin_hash IS NULL` —
   the frozen schema and the documented seeding behavior directly contradict each other. I could
   not edit `models.py`, so the workaround (used in `seed.py` and `people.py`) is: local_pin users
   always get an unguessable, never-issued placeholder `pin_hash`, and **`pin_set_at IS NULL`**
   is the real "PIN not set" signal that the admin UI and the CLI both check. This now applies to
   *every* seeded employee, not just the ones without a Work Email (see `## Deviations`).
2. **`revocations.purge_after` has no default in `models.py`**, though `docs/02` gives it
   `DEFAULT (now() + interval '2 hours')`. It's `NOT NULL` with nothing to fall back on. Every
   `Revocation(...)` I construct (in `people.py` and the migration's column default) supplies
   `purge_after` explicitly so this is never hit.
3. **`Session.token_hash`** (models.py) vs. **`sessions.refresh_token_hash`** (docs/02) — naming
   only, no functional difference. Noted inline in the migration.
4. `models.py` also carries `users.failed_pin_attempts` / `users.locked_until` (needed for the
   PIN lockout this brief requires) and `llm_registrations.disabled_reason`, none of which are in
   `docs/02`'s DDL. Not a problem — just flagging the drift since the migration is hand-written
   from `models.py`, with docs/02's constraints/indexes layered on top where `models.py` is silent.
5. **No `google_sub` column, as instructed — matching the link on email only.** I want to name
   the resulting weakness rather than let it pass silently: `users.login_email` is not
   immutable, and Google account holders can (rarely) change the address associated with a
   `sub`. If that ever happened, a future Google sign-in with the changed address would look
   like "unknown email" rather than "same person, new address," and re-linking would be required.
   I judged this an acceptable trade-off given the instruction and the fact that `email_verified`
   is checked on every sign-in, but a `google_sub` column would close it properly if the owner
   reconsiders — raising it here rather than adding the column myself.

## Assumptions

1. **Manager-resolution heuristic** (division + band, "second pass," per the brief). Band rank:
   `NON L`=`Ops`=0, `L1J`=1, `L1S`=2, `L2`=3, `L3`=4, `L4`=5, `L5`=6 — `"Ops"` and the `L1J`/`L1S`
   split appear in the real sheet but not in docs/02's parenthetical band list, so this ordering
   is my own call. A manager is assigned only when **exactly one** colleague in the same division
   sits at the next band up; ties and "nobody higher" are reported, never guessed. Against the
   real sheet this resolved only **11 of 73** — most bands have several peers per division at the
   same level, so the sheet's org shape is genuinely too flat/ambiguous for this heuristic to do
   more than a first pass. A human finishes the rest in the admin UI.
2. **Platform admin seeding.** `itadmin@m-mines.com` is not in the spreadsheet at all, so
   `seed_platform_admin()` invents a synthetic `Employee` the first time it runs:
   `employee_code="MM-ITADMIN"`, dept "Information Technology", division "Corporate", band "L3",
   title "Platform Administrator". **Confirmed by the owner** (`handoff/ORCHESTRATOR.md`) as a
   role-based service identity, kept exactly as built, separate from any person's employee row.
3. **Placeholder service `base_url`s.** The brief only gave `erpnext`'s real URL. `itemcode`,
   `att`, `servicedesk`, `twenty` are seeded with `https://<slug>.m-mines.com`, matching the shape
   used in docs/03's own examples, until the owning infra/service agent supplies real hostnames.
4. **Resolved: PIN-first for everyone, self-service Google linking.** This assumption started
   as "should a non-corporate email really get `auth_type='google'`?" — I initially answered it
   myself (domain-based classification). **The owner has since ruled on it directly**, and the
   ruling is now what's built, not a standing assumption: every employee gets a `local_pin`
   account regardless of email; Google sign-in is open to any address; a self-service link flow
   attaches a verified Google identity to the authenticated user only; `hd` is enforced only when
   auto-provisioning would otherwise be implied (no existing `login_email` match). Full detail in
   `## Deviations`. Net effect on the real sheet: 73 of 74 seeded users start as `local_pin` (the
   74th is the platform admin, seeded directly as `google`); every one of the 73 needs a PIN
   issued via `POST /api/admin/users/{id}/pin` before they can log in at all, and may
   additionally self-link a Google account (corporate or personal) at any time afterward.
5. **Google `id_token` signature is fully verified** against Google's live JWKS (fetched via
   `httpx.get`, mocked in tests), for both the login and link flows. The owner confirmed this was
   the right call when ruling on the auth model.
6. `POST /api/admin/employees/import?commit=true` recomputes the diff from the freshly uploaded
   file server-side rather than trusting a diff the client saw in an earlier dry-run response —
   the two calls must upload the same file.
7. The link flow's oauth-state cookie additionally carries the linking user's id (`uid`), checked
   against whoever the live session resolves to at callback time, purely as defense-in-depth
   against the signed-in session changing mid-flow (`link_session_mismatch`, `409`). The actual
   authorization decision is still "whoever the live session says it is right now" — the stored
   id is a consistency check, not the resolution mechanism, so this doesn't contradict "never
   resolve the target user from anything in the callback."
8. **The PIN throttle is in-process and in-memory** — a plain `dict[str, deque[float]]` inside
   one Python process, exactly like `routers/tokens.py`'s existing limiter. `docs/11-security-review.md`
   finding 3 (MEDIUM) already covers this for both routes: it is fully effective under the
   current deploy shape (`deploy/Dockerfile` runs `uvicorn` with no `--workers` flag,
   `deploy/docker-compose.yml` runs exactly one `api` container), but the moment MM OS scales
   to more than one worker or replica, each process keeps its own counter and every limit —
   this one and `tokens.py`'s — silently becomes N times more permissive with no error and no
   test that would catch it. Not something to fix in this router; flagging so it reads
   consistently with A2's own note rather than looking like a new, unrelated gap. A shared
   store (Redis) is the eventual fix, already named as future work in both B3's review and A2's
   handoff.
9. **Throttle threshold: 60/min, not the 20/min `docs/11-security-review.md` suggested.**
   B3's finding 2 write-up floats "e.g. 20/minute/IP" as a illustrative, not mandated, number.
   The coordinator's instruction was explicit: mirror `tokens.py`'s established limiter
   including its 60/min constant, because consistency between the two routes mattered more
   here than hand-tuning a tighter number for a login endpoint specifically. I followed that
   instruction as given. Worth a second look if IT ever wants the PIN route tighter than the
   token-mint route — they don't have to be the same number, they're just built the same way
   right now.

## Not done

1. **`alembic upgrade head` / `downgrade base` against a real Postgres — never run.** No Postgres
   exists on this machine (sprint amendments #3/#5). Validated instead with
   `alembic upgrade head --sql` and `alembic downgrade 0001:base --sql` (offline SQL rendering,
   no connection needed) — both render cleanly. Covered by
   `tests/test_identity.py::test_alembic_migration_renders_offline_without_error` (passes) and
   `::test_alembic_migration_head_and_downgrade_against_real_postgres`
   (`@pytest.mark.needs_postgres`, self-skips unless `MMOS_TEST_POSTGRES_URL` is set).
2. **The real-spreadsheet dry-run/commit/idempotency acceptance bullets were verified manually
   against a scratch SQLite database** (same JSONB/UUID bridge as `tests/conftest.py`, run outside
   the repo, never checked in), not against Postgres. Results: dry run → 73 new / 0 changed /
   0 missing / 0 conflicting / 69 proposed-grant rows; `--commit` creates 74 users total — 73
   `local_pin` (every real employee) + 1 `google` (the platform admin); a second `--commit` →
   0 new / 0 changed (1 "missing" appears on the second run — correctly: it's the synthetic
   IT-admin row `seed_platform_admin` created, which isn't in the sheet). The automated
   `test_seed_*` tests use synthetic in-memory sheets per guardrail #6, never the real file.
3. **No admin route to directly set a user's `auth_type` or `login_email`** outside the
   self-service link flow. An admin cannot pre-link an employee's Google account on their
   behalf — only the employee themselves, from an authenticated session, can. This is arguably
   correct given the owner's "prove control of both" design, but it does mean IT cannot
   bulk-link corporate addresses even if they wanted to; each of the 73 has to do it themselves
   once they have a PIN. Left as-is rather than adding an admin-side variant that wasn't asked
   for.
4. `GET /api/admin/employees` / `/users` pagination cursor is a plain `employee_code >` cursor,
   not a generic opaque one — fine while the sort order is fixed, would need revisiting if
   sorting becomes configurable.

## How to verify

All commands run from `backend/`.

```bash
# Identity test suite — expect "30 passed, 1 skipped"
.venv/Scripts/python.exe -m pytest tests/test_identity.py -q

# Whole backend suite (identity + every other agent's tests) — expect "75 passed, 1 skipped"
# as of the dependency bump + CSP header that landed after this handoff (see top of file).
#
# ORCHESTRATOR CORRECTION: the OperationalErrors this note originally told you to re-run
# through were a real harness bug, not machine load, and they are fixed. Two causes, both in
# backend/tests/conftest.py: every pytest process shared ONE SQLite file (so a second run's
# drop_all/create_all tore down the first's tables), and app/db.py's db_healthy() opens a
# second connection that /healthz hits while a test's write transaction is open, which on
# SQLite's default rollback journal blocks the reader until the 5s busy timeout expires. The
# database and signing key are now per-process, and connections open with WAL plus a 15s busy
# timeout. Verified with four full suites running simultaneously: 75 passed each, zero lock
# errors. So do NOT re-run to make this go away — if you see an OperationalError now, it is
# real and worth diagnosing.
.venv/Scripts/python.exe -m pytest tests/ -q

# Alembic, offline (no Postgres needed) — prints full SQL, exit code 0
MMOS_DATABASE_URL="postgresql+psycopg://x:x@localhost/x" .venv/Scripts/python.exe -m alembic upgrade head --sql
MMOS_DATABASE_URL="postgresql+psycopg://x:x@localhost/x" .venv/Scripts/python.exe -m alembic downgrade 0001:base --sql

# Real dry-run import (needs a live Postgres reachable via MMOS_DATABASE_URL; on this
# machine it fails at the connection step with a clean OperationalError, which is expected)
.venv/Scripts/python.exe -m app.seed --xlsx "C:\Users\Anura\OneDrive\Desktop\Erp Imp\Employee_Role_Access_Mapping.xlsx"
# Expected once a real Postgres is reachable: "Read 73 data row(s) ..." then
# "new: 73 / changed: 0 / missing: 0 / conflicting: 0" and a 69-line proposed grants report.
# Add --commit to apply (every one of the 73 lands as auth_type='local_pin'); re-running
# --commit should then report "new: 0 / changed: 0".
```

PowerShell equivalents for the alembic lines (this machine's primary shell):

```powershell
$env:MMOS_DATABASE_URL = "postgresql+psycopg://x:x@localhost/x"
.venv\Scripts\python.exe -m alembic upgrade head --sql
.venv\Scripts\python.exe -m alembic downgrade 0001:base --sql
```
