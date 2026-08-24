# Orchestrator · run 1 setup

Written before the six A agents launched, 24 Aug 2026. Two changes were made that no build
agent is allowed to make, so nobody needs to raise them as contract objections.

## 1 · One frozen-spine fix — `backend/app/models.py`

`User.grants` had no `foreign_keys`, and `grants` carries **two** foreign keys to `users`
(`user_id` and `granted_by`). SQLAlchemy therefore raised `AmbiguousForeignKeysError` on the
first mapper configuration — on Postgres as much as on SQLite. Nothing that touches the ORM
could have started.

```python
grants: Mapped[list["Grant"]] = relationship(
    back_populates="user", cascade="all, delete-orphan", foreign_keys="Grant.user_id"
)
```

`Grant.user` already declared `foreign_keys=[user_id]`; only the collection side was missing.
No column, constraint or API shape changed, so `docs/02-data-model.md` still holds.

## 2 · The test harness — `backend/tests/conftest.py`

There is no Docker and no Postgres on the build machine. The suite runs on SQLite, which needs
two bridges against the frozen models: `JSONB` has no SQLite compiler (rendered as `JSON`), and
SQLite returns naive datetimes while `app/deps.py` compares expiry against an aware UTC `now`
(results are tagged UTC through the pysqlite `colspecs`).

`backend/tests/test_harness_smoke.py` proves it: 8 tests, all passing, covering schema
creation, UUID round-trip, UTC-aware timestamps, JSONB round-trip, `/healthz`, and a
signed-in cookie reaching a guarded route.

Both files are orchestrator-owned and read-only to build agents.

## Standing limits for run 1

- `docker compose up`, `pgcrypto`, JSONB operators and the Alembic migration against a real
  server **cannot be proven here**. Mark such tests `@pytest.mark.needs_postgres` and list
  them under `## Not done`.
- Google OIDC credentials do not exist yet. Build to the env contract in `app/config.py`; fake
  the token exchange at the `httpx` boundary.
- `backend/requirements.txt` is orchestrator-owned. New dependencies go in `## Assumptions`,
  not into the file. `backend/requirements-dev.txt` holds `pytest`.
- No worktrees this run: all six agents worked in the one tree on exclusive paths. Baseline
  commit `844bc72` is the rollback point.

## Assumptions closed by the orchestrator during run 1

**A6's base-image tags — confirmed to exist** (24 Aug 2026, checked against the Docker Hub
registry API, which A6 could not reach):

| Tag | Exists | Last pushed |
|---|---|---|
| `python:3.12.7-slim-bookworm` | yes | 2024-10 |
| `node:20.18.1-bookworm-slim` | yes | 2025-01-14 |
| `postgres:16.6-bookworm` | yes | 2025-02-05 |

So the first VPS build will not fail on a nonexistent tag. All three are, however, **more than
a year old**, which means unpatched CVEs in the base layers. Bumping them is a **B3 hardening**
task, not a run-1 fix: pin to the newest patch release of the same minor line, then rebuild and
re-run CI. Do not unpin them to floating tags.

## Owner decisions taken mid-run (24 Aug 2026)

### The employee sheet has 73 rows, not 74

`docs/02-data-model.md`, `docs/09`'s definition of done and the A1 brief all say 74 employees.
The file has **73 data rows**. Verified directly against
`Erp Imp/Employee_Role_Access_Mapping.xlsx`: 73 rows, 49 `gmail.com` addresses, 23
`m-mines.com`, 1 blank. Every count in run 1 uses 73. The docs are wrong, not the importer.

### Auth: PIN-first for everyone, plus self-service Google linking

A1 found that 49 of 73 "Work Email" values are personal `gmail.com` addresses, so a literal
reading of `docs/02` would have provisioned 49 people as `auth_type='google'` and left them
permanently unable to pass the `hd=m-mines.com` check. The owner's ruling:

- **All 73 employees get a local PIN account.** Employee-code + PIN is the universal day-one
  path; nobody waits on a mailbox. `pin_set_at IS NULL` means "PIN not yet issued by IT".
- **Google sign-in stays open to any address**, including personal ones.
- **A link-your-Google-account flow** attaches a verified Google identity to the **currently
  authenticated** user only — the person proves control of the MM OS account with their PIN,
  then control of the Google account through OIDC. `login_email` is set, `auth_type` flips to
  `'google'`, and `pin_hash` stays so PIN login continues to work.
- **The `hd` check becomes conditional**: still enforced for **auto-provisioning**, so no
  stranger can create an account, but bypassed when the verified email already matches an
  existing user's `login_email`.

**This modifies the locked "Google Workspace OIDC, locked to `hd=m-mines.com`" decision**, and
the trade-off is deliberate and accepted: for anyone signing in with a personal Google account,
MFA is whatever that account's own 2FA is — it cannot be enforced from Workspace admin — and
offboarding must be done by deactivating the user in MM OS, since disabling a corporate mailbox
will not lock them out. The owner's stated intent is that corporate Google accounts arrive
later and become the primary path.

### Platform admin stays a service account

`MM-ITADMIN` / "IT Administrator" / Information Technology / Corporate / "Platform
Administrator" / band L3, as A1 invented it. Confirmed by the owner: a role-based identity
separate from any person's employee row, so it survives staff changes and reads honestly in the
audit log.

---

# Run 1 complete · seam inventory for B1

All six agents finished. Verified by the orchestrator, not taken on report:

| Suite | Result |
|---|---|
| `backend/tests` | 60 passed, 1 skipped (`needs_postgres`) |
| `servicedesk/tests` | 31 passed |
| `packages/mmos-client-py/tests` | 15 passed |
| `packages/embed/test/smoke.js` | 5 passed |
| `frontend` | `tsc --noEmit` exit 0, `npm run build` OK |
| `servicedesk/frontend` | `npm run build` OK |
| Frozen spine vs `844bc72` | only the documented `models.py` FK fix |

**There are no branches to merge** — the six worked in one tree on exclusive paths. B1's job is
therefore seams, then `scripts/verify/acceptance.sh`.

## A · Must fix, blocking

1. **Error envelope, app-wide.** `deps.py` raises `HTTPException(detail={...})`, so FastAPI
   returns `{"detail": {...}}` while `docs/03` documents a flat
   `{error, message, request_id}`. Raised independently by A2, A3 and A5. B1 is the only agent
   permitted to touch the spine: add one exception handler in `main.py` and make the wire shape
   match the doc. Then reconcile the consumers — A3 added a defensive unwrap in `client.ts`,
   A5's tests assert the nested path, A4's `install()` already flattens.

2. **Revocations path.** `docs/03` shows `GET /api/revocations`; `main.py`'s prefix actually
   puts it at `/api/agent/revocations`. A2 followed the code. Confirm A4's poller targets the
   real path — if it does not, the 60-second revocation SLA silently never fires, which is the
   single most security-relevant seam in the build.

3. **The A4 ↔ A5 auth seam.** A5 built `mmos_seam.py` as a stand-in before A4's kit existed and
   enumerated the divergences honestly. This is **not** a drop-in swap:
   - cookie name: A5 `servicedesk_session` vs A4 `{slug}_mmos_at`;
   - handoff shape: A5 one call (`POST /_mmos/accept`) vs A4 two (`GET /_mmos/accept` →
     `POST /_mmos/session`);
   - `servicedesk/app/main.py` never constructs `MMOS()` or calls `.install(app)` — the real
     auth wiring is entirely undone;
   - **behavioural, not cosmetic:** A4's `require_role` gives `platform_admin` **no** bypass of
     a service's own role check, while A5's `can_see_full()` / `_is_agent()` do.
   Adopt A4's kit as the standard, since it is the shared library every future service imports.
   The `platform_admin` question needs a deliberate answer rather than a merge: the locked
   decision is that private-ticket visibility is enforced **in the query**, so a platform admin
   should not silently gain private ticket bodies. Access to the agent console is a separate
   question from visibility of private content.

4. **Admin API shape drift** (found by A3 reading the now-real routers against `docs/03`):
   `/api/admin/services` wraps in `{services:[...]}` and its `roles[]` omits `description`;
   `/api/admin/grants` is flat with no `granted_by` and no nested names; employees and users are
   two separate collections rather than one joined row; `/api/admin/llm` uses
   `{registrations:[...]}`/`usage` not `usage_30d`; bulk-grant returns `{created,skipped}` not
   `{count}`. Resolve **in favour of the locked UI capabilities**, not whichever is less work:
   `brand/UI-DECISIONS.md` § Access page requires **role meanings shown inline** (so
   `description` must be served) and **who granted it and when** (so `granted_by` must be
   served). Those two are product requirements, not preferences.

## B · Missing endpoints that locked v1 decisions require — in scope for B1

5. **`GET /api/public/services`** — names and launch URLs **only**, no session, no roles, no
   health. The locked entry-page decision depends on it; nothing serves it today, so A3's entry
   page correctly shows an honest empty state rather than inventing data.

6. **A manager-chain lookup for services** (A5's objection). Service Desk cannot compute
   approvers: `/api/admin/employees` requires `is_platform_admin`, and there is no way for a
   service to walk another user's chain. Add a narrow, service-authenticated endpoint returning
   **only** what approval routing needs — minimum disclosure, not a directory dump. Note A1's
   finding that only **11 of 73** managers could be resolved from the sheet, because the org is
   genuinely flat, so approver routing must degrade gracefully rather than assume a chain exists.

## C · Defer to the v1 backlog — explicitly not B1

- Pending access requests on the Access page (needs the Service Desk ↔ MM OS integration).
- A user's own session list and a true sign-out-everywhere; `logout` revokes only the current session.
- A `target_id` filter on `GET /api/admin/audit`; A3 filters a fetched page client-side.
- Base-image bumps for CVEs — **B3 hardening**.
- `login_email` is not immutable and there is no `google_sub` column, so a changed Google-side
  address reads as an unknown email rather than the same person. Accepted trade-off; revisit
  only if that actually happens.
- Notifying anyone but the acting user: no `requester_email` on the ticket schema and no
  directory lookup for an arbitrary subject.

## D · Standing facts B1 must not re-derive

- The sheet has **73** employees. Seeding produces **73 `local_pin` + 1 `google`** (the
  `MM-ITADMIN` service account) = 74 users. Any assertion expecting 74 employees is wrong.
- Auth is **PIN-first for everyone** with self-service Google linking; the `hd` check survives
  **only for auto-provisioning**. See "Owner decisions taken mid-run" above.
- No Docker and no Postgres on this machine. Docker acceptance runs in **CI only**. The Alembic
  migration has never been executed against a real server.

---

# Orchestrator work after B3's review

## CSP added to `middleware.py` (frozen spine, third and final spine edit)

`docs/06` asks for `default-src 'self'; connect-src 'self'; frame-ancestors 'none'`. Applied as
written, with two exceptions the doc did not anticipate — neither of which widens script
execution (`script-src` stays `'self'`):

- **Google Fonts must be reachable.** Roboto and Roboto Condensed are the brand faces, loaded
  from `fonts.googleapis.com` (stylesheet) and `fonts.gstatic.com` (font files). A literal
  `default-src 'self'` would have silently broken the brand typography.
- **Inline `style` attributes are allowed.** The shell uses ~26 of them for values computed at
  render time (service-mark colours, sparkline geometry), so `style-src` carries
  `'unsafe-inline'`.

**Worth doing later:** self-hosting the two font families would let the CSP return to a literal
`default-src 'self'` and remove an outbound dependency that a VPN-only, network-restricted
deployment may not even be able to reach. Not done now because it changes A3's frontend rather
than one header.

Total frozen-spine edits across the whole build: **three** — `models.py` (FK fix), `main.py`
(B1's error-envelope handler), `middleware.py` (this CSP).

## Dependency bumps (`requirements.txt` is orchestrator-owned)

Applied to `backend/requirements.txt` and, where pinned, `servicedesk/requirements.txt`:

| Package | Was | Now | Why |
|---|---|---|---|
| `python-jose[cryptography]` | 3.3.0 | **3.5.0** | PYSEC-2024-232/233, PYSEC-2025-185 — this library mints and verifies every service token |
| `fastapi` | 0.115.6 | **0.141.1** | the only way to clear 9 `starlette` advisories; pulls `starlette` 0.41.3 → 1.6.0, a **major** bump |
| `cryptography` | 44.0.0 | **50.0.0** | 7 advisories incl. GHSA-537c-gmf6-5ccf |
| `python-multipart` | 0.0.20 | **0.0.32** | 6 advisories |

All suites re-run after the bumps: backend 75 passed / 1 skipped, servicedesk 31, client library
15. The `starlette` major bump was attempted separately from the other three so a breakage would
have been attributable; nothing broke. Warning count dropped from 14 to 1 (the `jose` bump
cleared the deprecated `utcnow` calls); the remaining one is a `httpx`/`httpx2` deprecation
notice in the test client, cosmetic.

`ecdsa` 0.19.2 remains, pulled in transitively by `python-jose`. With the `cryptography`
backend it is not on the RSA signing path, and upstream has stated the side-channel class will
not be fixed — so this is accepted, not outstanding.

## Correction to B3's frontend finding

B3 recommended `react-router-dom@6.30.6` as a non-breaking fix. **It is not a fix.** The two
advisories (GHSA-wrjc-x8rr-h8h6, GHSA-337j-9hxr-rhxg) cover `6.0.0 – 7.17.0`, and npm reports
the only remediation as `react-router-dom@7.18.2`, flagged `isSemVerMajor`. Verified directly
against `npm audit --json`, not inferred.

**Neither advisory is reachable in this app as built**, which is why this is a backlog item and
not an emergency:

- The *SSR hydration* `deserializeErrors()` injection needs server-side rendering. The shell is
  a client-only SPA — no `hydrateRoot`, no `renderToString`, no `StaticRouter`.
- The *open redirect via backslash* needs a user-controlled navigation target. Every
  `navigate()` call uses a literal path, and the only dynamic `to={}` reads from a hardcoded
  `TABS` array in `AdminTabs.tsx`.

`6.30.6` is still pinned (exact, no caret) because it does fix the **original** CVE-2025-68470
that 6.30.0 carried; these two advisories are a later bypass of that fix. Migrating to React
Router 7 is a deliberate major upgrade touching every route, and belongs in the v1 backlog with
its own testing — not bolted onto the end of a build.

## A fragility in the test harness, found and fixed

While re-verifying after the dependency bumps, `scripts/verify/acceptance.sh` reported
**4 failed**, then **1 failed**, then passed — the classic signature of a flaky harness rather
than a real regression, and it was worth chasing rather than re-running until green.

**Cause: my own harness design.** `backend/tests/conftest.py` pointed every pytest process at
**one shared SQLite file** on a fixed path, and its session-scoped `_schema` fixture calls
`drop_all` then `create_all`. So two pytest processes in flight at once — which happens easily,
because `acceptance.sh` itself invokes pytest six times and I had also started a second
acceptance run before the first finished — meant one session tore the other's tables down
mid-query. It surfaced as 12 SQLAlchemy errors in `test_b1_seams.py`, a file that passes
perfectly well on its own.

**Fix:** the SQLite database and the test signing key are now **per-process**
(`mmos_test_<pid>.db`, `mmos_test_signing_key_<pid>.pem`), disposed and deleted at session end.

**Proof, rather than assertion:** three pytest processes run simultaneously —
the full suite, `test_b1_seams.py` and `test_security.py` — all pass (75/1, 12, 9). Before the
fix, that combination is what produced the errors.

Worth remembering: **a failure that disappears on re-run is a bug in the harness, not luck.**
Had this been left, CI would have failed intermittently for reasons nobody could reproduce, and
the natural response — re-run until green — would have trained everyone to ignore real failures.

---

# First real Docker run — 21/21, and three defects only it could find

Docker Desktop was installed by the owner, so `scripts/verify/acceptance.sh full` ran for the
first time. Final state: **21 passed, 0 failed, 0 skipped.** Nothing is now reported as
unproven. Three real defects surfaced on the way, none of which any amount of SQLite testing
would have caught.

## 1 · The image shipped without its migrations

`deploy/Dockerfile` copied `backend/app` but **not** `backend/alembic/` or `alembic.ini` —
A6 wrote it before A1's migration existed. So `alembic upgrade head` inside the container
failed with `No config file 'alembic.ini' found`, meaning **schema changes could not be applied
on the VPS at all**.

What made it dangerous rather than merely broken: `/healthz` returned `{"ok":true,"db":"up"}`
throughout, because `db_healthy()` only issues `SELECT 1`, which needs no tables. A green health
check over an empty database is exactly the failure that looks fine until the first login.
Fixed by copying both into the image.

## 2 · The migration and the models disagreed — `alembic check` now guards it

With the migration finally runnable, it applied cleanly: **11 tables, `pgcrypto` present**. But
`alembic check` failed. The drift was indexes only, all in one direction — four the migration
created and `models.py` never declared, exactly as A1 predicted in its objection 4 (it layered
`docs/02`'s indexes on top of the models):

- `ix_employees_manager_id`
- `ix_sessions_user_live` — **partial**, `WHERE revoked_at IS NULL`
- `ix_audit_created` — `created_at DESC`, where the model declared plain `created_at`
- `ix_audit_actor_created` — `(actor_user_id, created_at DESC)`

Harmless in themselves, but they meant `alembic check` could never pass, so nobody could ever
use it to detect *real* drift, and a future autogenerate would have tried to drop them. All four
are now declared in `models.py`, which becomes the single source of truth: `alembic check`
reports **"No new upgrade operations detected"**, and the 75 SQLite tests still pass.

`alembic check` is now a permanent step in `acceptance.sh`. A hand-written migration with
nothing comparing it to the models is a standing hazard.

**Frozen-spine edits, final total: four.** `models.py` (the FK fix, and these indexes),
`main.py` (B1's error envelope), `middleware.py` (the CSP).

## 3 · No `.dockerignore` existed

Every `docker build` shipped ~240MB of context: `backend/.venv` 123M, `frontend/node_modules`
73M, `servicedesk/frontend/node_modules` 41M, plus `.git`. It also caused a real build failure —
`invalid file request frontend/dist/assets/index-C0Zf7F_1.js` — because `frontend/dist` was in
the context and its filenames are content-hashed, so an earlier `npm run build` in the same
acceptance run changed them under buildkit's snapshot.

Beyond speed, the host's `node_modules` and `dist` entering the context risked the image's own
`frontend-build` stage reusing stale host artifacts instead of a clean install. `.dockerignore`
now excludes those, and also `deploy/.env`, `deploy/secrets` and `*.pem`, so secrets cannot enter
a build context even by accident.

## Backup restore — performed, not just documented

`docs/09` requires a restore to have been carried out once. Done, with A6's real scripts, inside
the `postgres` container:

- `scripts/backup.sh` produced a 27KB encrypted dump, mode `0600`, and warned correctly that
  `OFFSITE_DEST` was unset (`docs/06` requires off-VPS storage).
- `scripts/restore.sh` restored into a **scratch** database — its default, and it demands two
  independent confirmations before it will touch live data, which is the right design for the
  one script here that can destroy production.
- Verified in the restored database: **11 tables, 28 indexes, `alembic_version` = 0001, and the
  seeded probe row present**. A row was inserted first with `gen_random_uuid()` on purpose, so
  the test proved data and `pgcrypto`, not just schema.
- Scratch database dropped, stack brought down, port 8000 released.

**Windows-only gotcha worth knowing:** run from Git Bash, `docker compose exec -e BACKUP_DIR=/tmp/...`
has its POSIX path rewritten by MSYS, so the container ends up with a literal `/C:/Users/...`
directory. Not a fault in the scripts — it cannot happen on the Linux VPS — but set
`MSYS_NO_PATHCONV=1` when driving these from Git Bash.

## Local test artifacts, deliberately created

`deploy/.env` (a generated 32-character throwaway `POSTGRES_PASSWORD`) and
`deploy/secrets/mmos_signing_key.pem` (via `scripts/gen-signing-key.sh`). Both confirmed
invisible to git — `git status` on `deploy/` reports nothing. Neither is a real credential and
neither is the VPS password.

## Still open, and needing the VPS rather than this machine

- **B3's HIGH finding stands:** `docker-compose.yml` publishes `8000:8000` on all interfaces and
  Docker's iptables integration bypasses `ufw` for published ports, which could make
  "not internet-facing" false. Drop the `ports:` mapping and let Coolify's Traefik reach the
  container over the internal network. `deploy/COOLIFY.md` §6 has the exact curl to confirm.
- `OFFSITE_DEST` must be set for backups to leave the VPS, and `rsync` is not in the postgres
  image — the scheduler needs it on the host.
- `init.sql`'s per-service passwords are still placeholders.
