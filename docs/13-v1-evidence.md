# 13 · v1 criteria — evidence

Walks the eight criteria in `docs/08-v1-plan.md`'s "Definition of done for v1," one by one.
`docs/08` itself is frozen and unedited. For each: **met / partially met / not met**, the exact
command or file that proves it, and the result actually observed on this build machine
(no Docker, no Postgres, no live VPS — see `docs/09`'s standing amendment). Where a criterion
needs infrastructure this machine doesn't have, that is stated plainly, with the exact command
that will prove it once such infrastructure exists — an unproven tick is not a tick.

All commands run from the repo root; `PY` is `backend/.venv/Scripts/python.exe`.

---

## 1 · Every employee logs in once and sees only what they are granted

**Partially met.**

The pieces are each proven; the whole chain has never run against a live deployment with real
people, because there is no live deployment.

- **The real 73-row sheet imports correctly**, dry-run, proven against the actual file:
  ```
  bash scripts/verify/acceptance.sh local
  ```
  gives `PASS  seed dry-run against the real spreadsheet (73 employees, nothing written)`, and
  directly:
  ```
  PY scripts/verify/_seed_dry_run.py "C:\Users\Anura\OneDrive\Desktop\Erp Imp\Employee_Role_Access_Mapping.xlsx"
  ```
  gives `new: 73 / changed: 0 / missing: 0 / conflicting: 0`. Committing (`--commit`, exercised
  manually by A1 against a scratch database, not the real one — see `handoff/a1-identity.md`
  `## Not done` #2) produces 73 `local_pin` users plus 1 `google` platform admin, 74 total.
- **PIN login and Google login both produce a session and the documented `/api/me` shape**:
  `backend/tests/test_identity.py` (27 of 28 tests pass; the 28th is
  `@pytest.mark.needs_postgres` and self-skips). Google's token exchange is mocked at the
  `httpx` boundary — no live Google call exists in this sandbox, since no OIDC credentials
  have been issued yet (`docs/09`'s standing amendment).
- **`/api/me` only ever returns live, unexpired grants on active services** — filtered
  server-side, never client-side (`backend/app/routers/me.py`, confirmed by reading it plus
  `backend/tests/test_identity.py`'s grant-filtering tests).
- **The shell renders exactly the tiles a person is granted, nothing more** — proven against
  A3's mock, not a live backend (no OIDC credentials to sign in for real):
  `frontend/src/api/mock.ts`'s `?as=prashanth` persona renders `/services` with exactly two
  rows (ERPNext/user, Item Code Studio/viewer), the literal acceptance line from
  `agents/A3-shell.md` — see `handoff/a3-shell.md`, "How to verify."

**What is not proven:** an actual person, on the real VPN, signing in with a real Google
account or a real IT-issued PIN, and seeing real tiles from the real 73-row import. That needs
a live deployment with Google OIDC credentials and at least one real login — it becomes
provable the first time `docs/10-runbook.md` section 1's "First deploy" checklist is actually
run end to end.

---

## 2 · Every service in the registry is reached through MM OS, and each verifies tokens

**Partially met.**

- **`mmos-client-py` verifies tokens correctly**, the exact ordered checklist in
  `docs/04-auth-flow.md`:
  ```
  backend/.venv/Scripts/python.exe -m pytest packages/mmos-client-py/tests -q
  ```
  gives **15 passed**, covering valid / expired / tampered / alg-confusion / revoked /
  MM-OS-unreachable / JWKS-unknown-kid cases.
- **Proven live, not just unit-tested, once**, by A4: `examples/echo-service` accepted a
  token minted through the real handoff, rejected one minted for the wrong `aud`, and
  correctly enforced the 60-second revocation SLA against the real background poller thread
  (`handoff/a4-integration.md`, "How to verify" — the revocation run was executed live during
  that build, not simulated).
- **Service Desk's real (`AUTH_MODE=http`) path was verified at the ASGI/middleware level**
  (`servicedesk/app/mmos_seam.py` wires the real `mmos_client.core.MMOS` instance; B1 confirmed
  exactly one `/_mmos/accept` and `/_mmos/session` route pair exists, and that an
  unauthenticated request gets the real kit's flat `401 {"error":"missing_token"}`) **but has
  never round-tripped a real signed JWT minted by one live MM OS process and verified by one
  live Service Desk process** — `handoff/b1-assembly.md` `## Not done` #2, unchanged since.
  Every Service Desk test in this repo runs `AUTH_MODE=stub`.
- **ERPNext and Twenty are `launch_mode="external"`** (`app/seed.py`'s `SERVICES` list) — by
  design they don't call back into MM OS's agent surface at all; "each verifies tokens" doesn't
  apply to them the same way, since MM OS only hands off a launch URL, never mints a
  service-audience token for a service that never asked for one.
- **Item Code Studio and ATT (the two real retrofits)** are B2's work
  (`agents/B2-retrofit.md`); `handoff/b2-retrofit.md` did not exist in this repo as of this
  review, so their state is unknown to B3 and not assessed here.

**What is not proven:** a genuine two-process integration run (real MM OS talking to a real
Service Desk, or a real Item Code Studio / ATT) with an actually-issued token. Needs a live
deployment; `handoff/b1-assembly.md`'s "Deferred ideas" already names the two-process
integration harness that would close this properly.

---

## 3 · Removing a grant removes access within 60 seconds, provably

**Met**, for the mechanism; the wall-clock 60-second claim across two independently-running
processes is proven once (by A4) rather than repeated on every build.

- ```
  PY -m pytest backend/tests/test_platform.py -k revocation -q
  ```
  covers `test_grant_deletion_writes_revocation_and_appears_immediately` and
  `test_revocations_scoped_per_service_never_leak` (cross-service isolation).
- ```
  bash scripts/verify/verify-security.sh
  ```
  re-proves the same chain independently of the pytest suite, plus the cross-service isolation
  check, against a fresh scratch database each run.
- ```
  bash scripts/verify/verify-offboard.sh
  ```
  proves the stronger case (a full user deactivation, not just one grant), including that a
  *second* client presenting the same now-revoked cookie is also rejected — not just the
  client that triggered the deactivation.
- **Emergency kill drops the poll interval to 5 seconds for 10 minutes**:
  `test_kill_writes_subject_revocation_and_drops_poll_interval`
  (`backend/tests/test_platform.py`).
- **The real 60-second SLA against two live, separately-running processes** was proven once,
  live, by A4: revoke, wait the real 60 seconds, and the echo-service's next request returns
  `401 {"error":"revoked"}` (`handoff/a4-integration.md`, "How to verify"). Not re-run here —
  nothing about the wiring has changed since.

---

## 4 · An automation request completes the full approval chain and produces an immutable snapshot

**Met.**

```
PY -m pytest servicedesk/tests -q
```
gives **31 passed**, including
`test_operator_to_it_proposal_to_hod_approval_to_build_to_deployed` (`test_full_flow.py`) — the
full acceptance chain (operator, it_review, proposal, manager_review, approved, in_build,
deployed, closed) with the exact `events` row sequence asserted — and
`test_only_computed_approver_may_decide` and
`test_requester_cannot_decide_even_if_somehow_the_approver_sub` (`test_proposal_and_decision.py`),
which prove a decision snapshot is immutable across a later proposal revision and that
self-approval is blocked even against a manually corrupted row. Approver escalation itself
(`test_approver.py`) covers operator-to-HOD, a HOD raising their own request escalating past
themselves to Apex, Apex-with-nobody-above simply raising, and the `is_approver` override —
four tests, all passing.

**Not proven live**: email notification via real Workspace SMTP (no SMTP server reachable in
this sandbox — `handoff/a5-servicedesk.md` `## Not done`), and the same two-process caveat as
criterion 2 (Service Desk's `AUTH_MODE=http` path has not round-tripped a real MM OS token).
Neither affects the state-machine/approval/snapshot claim this criterion is actually about.

---

## 5 · The LLM panel shows every AI-using service, and the kill switch demonstrably stops calls

**Partially met.** The mechanism is proven in isolation; the full "an admin flips a switch and
a real LLM call that was about to happen gets refused" path has never run end to end against a
real service making a real call.

- **The panel's data source**: `GET /api/admin/llm` (`backend/app/routers/platform.py`) —
  `test_llm_toggle_bumps_config_version`,
  `test_llm_toggle_off_then_agent_config_reports_disabled`,
  `test_heartbeat_without_llm_block_shows_as_unreported`
  (`backend/tests/test_platform.py`), all passing — a service that has never reported an `llm`
  block shows as visibly `unreported`, never fabricated as blank.
- **The kill switch mechanism**: `packages/mmos-client-py/tests` covers `llm_guard()` starting
  default-open and closing after a heartbeat reports it disabled (15 tests, all passing).
- **A key cannot be smuggled through a heartbeat**, even under a field name the stripping
  regex doesn't catch, because the handler only ever reads `provider`/`model`/`key_present` out
  of the incoming object — traced in `docs/11-security-review.md`, "Verified — not findings."
- **Frontend**: `LlmPage.tsx` renders the table with a working toggle against A3's mock
  (`handoff/a3-shell.md`, "How to verify," the `/?as=admin` persona) — not against a live
  backend.

**What is not proven**: the kill switch stopping an actual, real LLM API call mid-flight
against a real provider. `llm_guard()`'s cached-flag design means the stop takes effect on a
service's next heartbeat (default every 300 seconds, documented in `docs/10-runbook.md`
section 10) — this delay is real and by design, not a bug, but "demonstrably stops calls" in
the fullest sense needs a live service making live calls, which does not exist in this build.

---

## 6 · `audit_log` answers "who granted what, to whom, when" for the whole period

**Met**, for the mechanism and the query surface; "for the whole period" depends on retention,
which is a deployment fact stated in the runbook, not something a test proves.

- `GET /api/admin/audit` returns nested `actor:{id,name}` and `service:{slug,name}`, not bare
  ids: `test_audit_entries_expose_actor_and_service_names`
  (`backend/tests/test_b1_seams.py`), passing. This is what B1 added specifically to make the
  answer to "who granted what, to whom, when" legible without a second lookup.
- Filterable by actor/action/date range with keyset pagination
  (`backend/app/routers/platform.py::list_audit`); every grant create/delete, service create/
  key-rotation, user activate/deactivate/PIN-set/reset, LLM enable/disable, and employee import
  writes a row (`backend/app/deps.py::audit()`, called from every mutating admin route —
  confirmed by grepping every router under `/api/admin` for a call to `audit(...)`).
- `AuditPage.tsx` renders it against A3's mock (`handoff/a3-shell.md`) — not against a live
  backend.
- **Retention**: `docs/10-runbook.md` section 13 states `audit_log` is kept forever (nothing
  deletes it) — this is a fact about the schema and code (no delete or purge job anywhere
  touches this table, confirmed by grepping for `delete` against `AuditLog`/`audit_log` across
  `backend/app`), not something that needs a live deployment to prove.

---

## 7 · Nothing is reachable from the public internet

**Not proven — and identified as at risk.**

This is the criterion this review found the most consequential open question against. See
`docs/11-security-review.md` finding 1 in full: `deploy/docker-compose.yml`'s `api` service
publishes `ports: "8000:8000"` on all host interfaces, and Docker's own iptables integration is
well documented to bypass `ufw`'s filtering for a published port unless the operator has
separately added `DOCKER-USER` rules — none exist anywhere in this repo. Combined with
`backend/app/deps.py::client_ip()` trusting a self-supplied `X-Forwarded-For` header whenever
one is present (proven mechanically by `scripts/verify/verify-security.sh`), a direct
connection to port 8000 could defeat `NETWORK_MODE=private`'s CIDR allowlist entirely.

**This was not tested against a real VPS** — there is none reachable from this build machine.
The exact live test that proves or disproves it, already written and not invented for this
document (`deploy/COOLIFY.md` section 6):

```bash
# from a machine OUTSIDE MMOS_ALLOWED_CIDRS, over the public internet, after a real deploy
curl -s -H "X-Forwarded-For: 10.8.0.1" https://os.m-mines.com/api/me -o /dev/null -w "%{http_code}\n"
```

A result of `403` means the gate holds for the normal HTTPS path through Traefik. That alone
does **not** prove criterion 7, because it doesn't test whether port 8000 itself is separately
reachable — run the same curl directly against the VPS's public IP on port 8000 from outside
the VPN as well; if that also returns `403` for a spoofed header, and a connection to that port
from an address outside `MMOS_ALLOWED_CIDRS` is refused outright once the fix in finding 1 is
applied, criterion 7 is met. Until both of those are run for real against the live VPS, this
criterion should be treated as **unverified, not passing**, not as a formality.

---

## 8 · A restore from backup has been performed into a scratch database and verified

**Not met.** No Postgres is reachable from this build machine, so no backup has ever been
taken, let alone restored. `scripts/backup.sh` and `scripts/restore.sh` (A6) pass `bash -n` and
were reviewed line by line; `scripts/verify/verify-backup.sh` (B3) confirms that plus which
Postgres client tools exist, and SKIPs the actual round trip with that exact reason:

```
bash scripts/verify/verify-backup.sh
```
gives `PASS scripts/backup.sh -- bash -n`, `PASS scripts/restore.sh -- bash -n`, then `SKIP` on
every tool-presence and round-trip check with "not installed on this host."

**The exact procedure that will prove this**, once there is a live deployment with at least
one real nightly backup (the same text lives in `docs/10-runbook.md` section 14, not
duplicated in full here):

```bash
BACKUP_PASSPHRASE=<real> POSTGRES_PASSWORD=<real> \
  scripts/restore.sh /var/backups/mmos/mmos_mmos_<timestamp>.dump.enc
psql -h <pghost> -U mmos -d mmos_restore_<timestamp> -c "SELECT count(*) FROM employees;"
psql -h <pghost> -U mmos -d mmos_restore_<timestamp> -c "SELECT count(*) FROM audit_log;"
dropdb -h <pghost> -U mmos mmos_restore_<timestamp>
```

or, automated: run
`PGHOST=<host> POSTGRES_PASSWORD=<real> BACKUP_PASSPHRASE=<real> scripts/verify/verify-backup.sh mmos`,
which performs the same dump, encrypt, decrypt, restore, row-count-compare sequence and prints
one PASS/FAIL line per step.

---

## Summary

| # | Criterion | Status |
|---|---|---|
| 1 | Every employee logs in once, sees only their grants | Partially met — logic proven, no live login yet |
| 2 | Every service reached through MM OS, verifies tokens | Partially met — proven for echo-service live; Service Desk and the retrofits not round-tripped live |
| 3 | Grant removal blocks access within 60s, provably | **Met** |
| 4 | Automation request completes chain, immutable snapshot | **Met** |
| 5 | LLM panel and kill switch demonstrably stops calls | Partially met — mechanism proven, no live call stopped |
| 6 | `audit_log` answers who/what/whom/when | **Met** (mechanism); retention confirmed by code, not by a live period |
| 7 | Nothing reachable from the public internet | **Not proven — at-risk finding**, needs a live VPS test |
| 8 | Restore from backup performed and verified | **Not met** — never performed, no Postgres available |

Two criteria met outright, three partially met (each with the exact live step that would close
the gap), two not met or not proven — one of which (7) is the most important criterion in the
list to get wrong quietly, which is exactly why it is reported here as unproven rather than
assumed.

---

# Orchestrator addendum — Docker installed, criteria re-tested

Written after this document was first produced. Docker Desktop was installed on the build
machine, so `scripts/verify/acceptance.sh full` ran for the first time and several statements
above are now out of date. **The acceptance script now reports 21 passed, 0 failed, 0 skipped.**

## Criterion 8 — restore from backup: now **MET**

The section above says "Not met. No Postgres is reachable from this build machine." That is no
longer true. Performed on 24 Aug 2026 with A6's real scripts, inside the `postgres` container:

- `scripts/backup.sh` produced `mmos_mmos_20260824T113154Z.dump.enc` — 27KB, mode `0600` — and
  correctly warned that `OFFSITE_DEST` was unset, so the dump stayed local. `docs/06` requires
  off-VPS storage, so **that part remains not met** and is a VPS configuration step.
- `scripts/restore.sh` restored it into scratch database `mmos_restore_20260824T113231Z`. Its
  default is a scratch target and it requires two independent confirmations before it will touch
  a live database — the correct design for the one script here that can destroy production.
- Verified inside the restored database: **11 tables, 28 indexes, `alembic_version` = 0001**, and
  a probe row (`MM-RESTORE`) inserted beforehand with `gen_random_uuid()` so the test proved
  **data and `pgcrypto`**, not merely schema.
- Scratch database dropped; the stack was brought down and port 8000 released.

Reproduce with `bash scripts/verify/acceptance.sh full` on a Docker host, then the two commands
in `## 8` above with `PGHOST=localhost` inside the container.

## What the first real Docker run changed

Three defects were found that no SQLite-based testing could have surfaced, all fixed:

1. **`deploy/Dockerfile` shipped no migrations** — it copied `backend/app` but not
   `backend/alembic/` or `alembic.ini`, so `alembic upgrade head` in the container failed and
   schema changes could not have been applied on the VPS at all. `/healthz` nevertheless
   reported `{"ok":true,"db":"up"}` the whole time, because `db_healthy()` only issues
   `SELECT 1` and needs no tables.
2. **The migration and `models.py` disagreed** on four indexes (`ix_employees_manager_id`, the
   partial `ix_sessions_user_live`, and two `created_at DESC` audit indexes) — A1's objection 4,
   confirmed. All four are now declared in `models.py`, and **`alembic check` is a permanent
   step in the acceptance script** so a hand-written migration can never silently diverge again.
3. **No `.dockerignore` existed** — ~240MB of build context, and a real build failure when
   content-hashed `frontend/dist` filenames changed under buildkit's snapshot.

## Criterion 7 — still the one to watch

`ports: 8000:8000` on all interfaces, with Docker's iptables integration bypassing `ufw`,
remains **not proven and at risk**, exactly as recorded above. Installing Docker locally did not
change it: it can only be settled on the VPS. `deploy/COOLIFY.md` §6 has the curl that settles
it, and the fix is to drop the `ports:` mapping and let Coolify's Traefik reach the container
over the internal network.
