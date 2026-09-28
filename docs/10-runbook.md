# 10 · Runbook

Written for the person on call at 2am who did not build this. Every entry is commands and
expected output, not prose. `PY` below is always `backend/.venv/Scripts/python.exe` on this
Windows build machine, or `backend/.venv/bin/python` on the deployed Linux host — **never bare
`python`**. Run everything from the repo root unless a command says otherwise.

See `docs/11-security-review.md` for *why* each of these procedures is shaped the way it is —
this file is only *how*.

## 0 · What exists where

| Thing | Lives at |
|---|---|
| MM OS app | one container, `deploy/Dockerfile` + `deploy/docker-compose.yml`, Coolify-managed |
| Postgres | the `postgres` service in the same compose file, no host port published |
| Signing key | `deploy/secrets/mmos_signing_key.pem`, mounted as a Docker secret, never an env var |
| Service Desk | a **separate** Coolify app, own container, own Postgres database (`deploy/COOLIFY.md` §7) |
| Logs | `docker compose -f deploy/docker-compose.yml logs api` (stdout/stderr only — no log file inside the container); Coolify also keeps its own copy in its dashboard |
| Backups | `/var/backups/mmos/*.dump.enc` on the VPS (or wherever `BACKUP_DIR` points), plus `OFFSITE_DEST` if configured — **verify `OFFSITE_DEST` is actually set**, `scripts/backup.sh` only warns if it isn't, it does not fail |
| Audit trail | `audit_log` table, queried live via `GET /api/admin/audit` (the Audit tab in the admin UI) — kept forever (no retention job deletes it); backups are the only thing that could lose it |
| Revocation deny-list | `revocations` table, purged automatically once `purge_after` passes (2h after the block no live token could still carry it) — this table being empty is normal, not a sign nothing was ever revoked |

## 1 · First deploy

```bash
cp deploy/.env.example deploy/.env         # fill in every value; never commit deploy/.env
scripts/gen-signing-key.sh deploy/secrets/mmos_signing_key.pem
# note the printed MMOS_SIGNING_KEY_ID -- put it in deploy/.env / Coolify's env vars
docker compose -f deploy/docker-compose.yml up -d
curl -sf http://localhost:8000/healthz
# expect: {"ok":true,"version":"1.0.0","db":"up"}
curl -sf http://localhost:8000/.well-known/jwks.json
# expect: {"keys":[{"kty":"RSA","kid":"mmos-...","use":"sig","alg":"RS256","n":"...","e":"..."}]}
```

Then, once, seed the real employee sheet:

```bash
docker compose -f deploy/docker-compose.yml exec api \
  python -m app.seed --xlsx /path/inside/container/Employee_Role_Access_Mapping.xlsx
# dry run first -- read the diff. Expect "new: 73 / changed: 0 / missing: 0 / conflicting: 0"
# on a genuinely first import. Add --commit only after the diff looks right:
docker compose -f deploy/docker-compose.yml exec api \
  python -m app.seed --xlsx /path/inside/container/... --commit
```

Full step-by-step for the Coolify dashboard itself (creating the app, environment variables,
Google OIDC console setup, database bootstrap) is in `deploy/COOLIFY.md` — this section is only
the command sequence, not the UI clicks.

**Full v1 deploy checklist**, in order, per `docs/08-v1-plan.md`'s M0/M6 milestones:

1. WireGuard up, split-horizon DNS for `os.m-mines.com`, DNS-01 certificate issued
   (`deploy/NETWORK.md` §2-4).
2. This section (Postgres + API up, `/healthz` and JWKS answer).
3. Employee sheet seeded (above).
4. Google OIDC credentials created and `MMOS_GOOGLE_CLIENT_ID`/`_SECRET` set
   (`deploy/COOLIFY.md` §5).
5. Grant review: translate the ERP-access prose column (printed by the seed dry run as
   "proposed grants," never auto-applied) into real grants via the admin UI.
6. PINs issued for the ~50 staff with no corporate mailbox (§6 below).
7. VPN peers created for everyone (`deploy/NETWORK.md` §2).
8. 30-minute floor training, MM OS set as the browser homepage on office machines.
9. A real restore-from-backup test, once (§8 below) — `docs/08`'s definition-of-done #8.

## 2 · Roll back

MM OS is one image; rolling back means redeploying the previous image tag in Coolify (or
`git checkout` the previous commit and rebuild — the orchestrator owns version control, ask
them for the exact prior commit if you're not sure which one). There is no in-place schema
downgrade path exercised in production — Alembic *can* downgrade
(`alembic downgrade -1`), but this has only been rendered offline (`--sql`), never run against a
real database (see `## Not done` in `handoff/a1-identity.md`). If a bad deploy included a
migration, prefer restoring from the last backup taken *before* that deploy over trying to
downgrade forward-compatible data.

```bash
docker compose -f deploy/docker-compose.yml down
# redeploy the previous image/commit via Coolify, or:
docker compose -f deploy/docker-compose.yml up -d --build
curl -sf http://localhost:8000/healthz
```

## 3 · Read logs / restart cleanly

```bash
docker compose -f deploy/docker-compose.yml logs -f api        # follow
docker compose -f deploy/docker-compose.yml logs --tail=200 api # last 200 lines
docker compose -f deploy/docker-compose.yml restart api         # restart just the API,
                                                                  # Postgres stays up
```

A clean restart is safe at any time: shell sessions are opaque DB rows (not JWTs), so they
survive an API restart untouched; in-flight service tokens (15-minute TTL) keep verifying
against the same key on disk; the in-memory deny-list and rate-limit counters reset to empty,
which is safe (a freshly-restarted process has never seen a revocation to forget, and an
empty rate-limit counter is the same as one that's just been idle). **After a restart, every
`mmos-client-py` service's cached `llm_enabled` flag resets to `True` (open) until its next
heartbeat** (default every 5 minutes) — if LLM was deliberately disabled on a service before
the restart, re-run the toggle (§7) after confirming the restart, or expect up to 5 minutes of
LLM access being open again on that service.

## 4 · Onboard an employee

**A. Already in the spreadsheet, sheet re-imported** — nothing more to do; they exist as a
`local_pin` user. Skip to issuing a PIN (§6) or let them self-link Google (§C).

**B. Brand new hire, not yet in the spreadsheet:**

```bash
# via the admin UI: People tab -> "+ Employee", fill in the required fields
# (employee_code, full_name, hr_department, division, job_title, band), save.
# Or via the API directly:
curl -X POST https://os.m-mines.com/api/admin/employees \
  -H 'Content-Type: application/json' -H "Cookie: mmos_session=<your admin session cookie>" \
  -d '{"employee_code":"MM74","full_name":"...","hr_department":"...","division":"...","job_title":"...","band":"L1J"}'
```

This creates the `Employee` row only — **not** a `User` row (`POST /api/admin/employees` doesn't
create login credentials, per `backend/app/routers/people.py`). Import them properly through
`app.seed`'s importer on the next sheet refresh, or use the admin UI's "issue PIN" flow, which
requires a `User` row to already exist — if it doesn't, re-run the importer against an updated
sheet that includes this row so the standard `local_pin` account gets created the same way
everyone else's did.

**C. Grant access and (optionally) let them self-link Google:**

```bash
# Grants: admin UI Access tab -> pick person -> add grant, or bulk-grant by band/department.
curl -X POST https://os.m-mines.com/api/admin/grants \
  -H 'Content-Type: application/json' -H "Cookie: mmos_session=<admin session>" \
  -d '{"user_id":"<uuid>","slug":"itemcode","role":"viewer"}'
```

Google linking is **self-service only** — IT cannot pre-link an account on someone's behalf
(`handoff/a1-identity.md` `## Not done` #3, an intentional design choice: it proves control of
both accounts). Tell the new hire: sign in with your employee code + PIN once, then
"Link Google account" from the profile page (`GET /api/auth/google/link/start`). Works with a
personal `gmail.com` address too, by design.

**D. VPN peer:**

```
Coolify -> wg-easy admin -> New peer, named "<employee_code>-laptop" (and "-phone" if needed —
one peer per device, but always the person's code as the prefix, never a nickname). Hand the
config to them in person or via a password-manager secure note. Never a plain email
attachment (deploy/NETWORK.md §2).
```

## 5 · Offboard an employee — exact order

**This order matters.** Disabling only the Google account is not enough — a linked personal
Gmail address, or someone who never linked Google at all, keeps PIN access until the MM OS user
itself is deactivated (this is the accepted trade-off recorded in
`docs/11-security-review.md`).

1. **Deactivate the MM OS user** (this is the step that actually removes access — do it
   first, don't wait on the other two):
   ```bash
   curl -X PATCH https://os.m-mines.com/api/admin/users/<user_id> \
     -H 'Content-Type: application/json' -H "Cookie: mmos_session=<admin session>" \
     -d '{"is_active": false}'
   ```
   This flips `is_active`, revokes every live session, and writes a global revocation row —
   **all in one transaction** (`backend/app/routers/people.py::update_user`). Nothing here can
   half-succeed.
2. **Disable their Google account** in the Workspace admin console (belt-and-braces; step 1
   already blocks MM OS regardless of whether this is done, but the Google account itself may
   still reach other Workspace services).
3. **Delete their VPN peer(s)** in `wg-easy` — every peer whose name starts with their
   employee code, per `deploy/NETWORK.md` §2. **Delete, don't disable** — you cannot delete
   what you cannot attribute later, and a disabled-but-present peer is exactly the kind of
   thing the monthly audit (§9) exists to catch if this step gets skipped.
4. **Verify with a real attempt**, don't just trust the API responses:
   ```bash
   # Read-only check against the live database -- confirms all three:
   # user.is_active is False, no live sessions remain, an unexpired global revocation exists.
   scripts/verify/verify-offboard.sh --code MM19 --database-url "$MMOS_DATABASE_URL"
   ```
   Then actually try to sign in as them (PIN, and Google if they had linked one) and confirm
   both are refused. If they held a grant on Service Desk or another service, confirm a
   previously-open browser tab for that service also gets logged out within
   `MMOS_REVOCATION_POLL_SECONDS` (60s default) of the deactivation.

**Note on Service Desk specifically:** its own session cookie (`servicedesk_mmos_at`) is the
same MM OS-issued JWT re-verified on every request — there is no separate "log this person out
of Service Desk" step. Once the subject is on the deny-list, Service Desk's own deny-list poller
picks it up on its own 60-second cycle, same as any other service.

## 6 · Issue or reset a PIN — including for the ~50 staff with no corporate mailbox

This is exactly the same flow either way — there is no separate "no mailbox" path, which is the
point of the PIN-first design (`handoff/ORCHESTRATOR.md` "Owner decisions taken mid-run").

```bash
# Admin UI: People tab -> pick the person -> "Issue PIN" (or "Reset PIN" if one already exists).
# Or via the API:
curl -X POST https://os.m-mines.com/api/admin/users/<user_id>/pin \
  -H 'Content-Type: application/json' -H "Cookie: mmos_session=<admin session>" \
  -d '{}'
# Response: {"pin": "482913"}  -- shown ONCE. It is never retrievable again -- write it down
# now, hand it to the person directly (in person, or a password-manager secure note, never
# a plain chat message or email), and only then close this terminal.
```

To set a *specific* PIN instead of a random one: `-d '{"pin": "1234"}'` (4-8 digits).

To clear a PIN without issuing a new one (e.g. someone is leaving temporarily and you want to
force a re-issue later without deactivating them): `-d '{"clear": true}'`. This does **not**
disable their account — `auth_type='local_pin'` structurally requires a `pin_hash`
(`models.py`'s `pin_required` CHECK), so "cleared" means an unusable random placeholder is
written and `pin_set_at` is nulled — the admin UI reads `pin_set_at IS NULL` as "no real PIN
issued," which is the correct signal to check, **not** `pin_hash IS NULL` (it is never null).

A PIN locks itself out after 5 wrong attempts for 15 minutes
(`MMOS_PIN_MAX_ATTEMPTS`/`MMOS_PIN_LOCKOUT_MINUTES`). To unlock someone early without waiting:
issue them a fresh PIN (above) — that also resets `failed_pin_attempts`/`locked_until` to zero.

## 7 · Register a new service end to end

```bash
# 1. Register it
curl -X POST https://os.m-mines.com/api/admin/services \
  -H 'Content-Type: application/json' -H "Cookie: mmos_session=<admin session>" \
  -d '{"slug":"newsvc","name":"New Service","base_url":"https://newsvc.m-mines.com","launch_mode":"handoff"}'

# 2. Add its roles
curl -X POST https://os.m-mines.com/api/admin/services/newsvc/roles \
  -H 'Content-Type: application/json' -H "Cookie: mmos_session=<admin session>" \
  -d '{"key":"viewer","name":"Viewer","description":"Read-only access"}'

# 3. Issue its service key (shown ONCE -- store it in the new service's own Coolify env,
#    never in git, never in a chat message)
curl -X POST https://os.m-mines.com/api/admin/services/newsvc/rotate-key \
  -H "Cookie: mmos_session=<admin session>"
# {"service_key": "mmk_..."}

# 4. The service integrates packages/mmos-client-py (see packages/mmos-client-py/README.md
#    and docs/05-service-integration.md), configured with this slug/os_url/service_key.

# 5. First grant, so at least one person can actually open it:
curl -X POST https://os.m-mines.com/api/admin/grants \
  -H 'Content-Type: application/json' -H "Cookie: mmos_session=<admin session>" \
  -d '{"user_id":"<uuid>","slug":"newsvc","role":"viewer"}'
```

Verify the new service is alive from MM OS's side: `GET /api/agent/config` with its service
key should return `{"llm_enabled":true,"config_version":0,"poll_after_seconds":60}` — and its
own `/_mmos/health` should answer `{"ok":true,"slug":"newsvc",...}`.

**If IT itself needs to administer this service** (e.g. an agent console, an admin panel):
platform admin does **not** carry any access into a service's own roles by design
(`docs/11-security-review.md` "platform_admin correctly no longer bypasses..."). Grant the
platform admin account (`MM-ITADMIN` / `itadmin@m-mines.com`) the relevant role explicitly, the
same as step 5 above, using its own user id.

## 8 · Rotate the signing key without downtime

The signing key rotation itself is **not zero-downtime for signed-in sessions and live service
tokens** — `scripts/gen-signing-key.sh`'s own refusal-without-`--force` exists precisely because
overwriting the key invalidates every one of them at once. What *can* be done without downtime
is publishing the new key's JWKS entry ahead of switching signing over to it (overlapping
publication, per `docs/04-auth-flow.md`) — but this build's `security.py::jwks()` only ever
publishes the **one** currently-loaded private key's public half, so true overlapping
publication (old key still verifiable while new key starts signing) is not implemented as a
distinct step here; treat rotation as a planned, announced, short-downtime event:

```bash
# 1. Generate the new key under a NEW kid (do not overwrite the old file yet)
scripts/gen-signing-key.sh deploy/secrets/mmos_signing_key_new.pem --kid mmos-2027-01

# 2. Swap the file and kid together, then restart -- this is the moment every live
#    session and service token stops verifying, so do it in a low-traffic window and
#    tell people to expect to sign in again.
mv deploy/secrets/mmos_signing_key_new.pem deploy/secrets/mmos_signing_key.pem
# update MMOS_SIGNING_KEY_ID=mmos-2027-01 in Coolify's env vars
docker compose -f deploy/docker-compose.yml up -d --force-recreate api

# 3. Verify
curl -sf https://os.m-mines.com/.well-known/jwks.json
# expect the new kid in "keys"; sign in fresh and confirm a new session works.
```

Old service tokens (15-minute TTL) simply expire naturally within 15 minutes of the swap — no
separate cleanup needed. Old shell sessions need everyone to sign in again.

## 9 · Emergency revoke one user

```bash
curl -X POST https://os.m-mines.com/api/admin/users/<user_id>/kill \
  -H "Cookie: mmos_session=<admin session>"
```

This is stronger than deactivation alone: it writes a global subject-level revocation
**and** best-effort jti-level revocations for any token minted to that user in the last
`MMOS_SERVICE_TOKEN_TTL_SECONDS` (default 15 min), read back from the audit log. It also drops
every service's `poll_after_seconds` to 5 for the next 10 minutes
(`backend/app/routers/agent.py::_poll_after_seconds`), so the deny-list propagates faster than
the normal 60-second cycle during the emergency window. **This does not deactivate the user** —
follow up with §5's deactivation if the intent is a full offboard, not just an emergency session
kill.

## 10 · Emergency disable all LLM across every service

There is **no single "disable everything" endpoint** — toggle each registered service
individually:

```bash
curl -s https://os.m-mines.com/api/admin/llm -H "Cookie: mmos_session=<admin session>" \
  | python -c "import json,sys; [print(r['slug']) for r in json.load(sys.stdin)['registrations']]"
# for each slug printed:
curl -X POST https://os.m-mines.com/api/admin/llm/<slug>/toggle \
  -H 'Content-Type: application/json' -H "Cookie: mmos_session=<admin session>" \
  -d '{"enabled": false, "reason": "emergency disable"}'
```

**Expect up to 5 minutes for this to take effect per service** — each service's `llm_guard()`
only re-checks on its own heartbeat cycle (`heartbeat_seconds`, default 300), it does not make a
network call on the request path (`docs/11-security-review.md`, LLM control-plane section). If
a service has just restarted, its cache defaults back to *enabled* until its first heartbeat
lands, regardless of what was set before the restart — re-confirm the toggle after any restart
during an active incident.

## 11 · What to do when the deny-list poll fails

Every service's `mmos_client._denylist.DenyListPoller` degrades on purpose — a failed poll
**keeps the last known deny-list and keeps serving**, rather than logging the whole company out
because MM OS's control plane restarted (`docs/04-auth-flow.md`'s availability rule). This means
a failed poll is not visible as an outage; it is visible as a **stale** deny-list, which is a
security exposure, not an availability one.

1. Check whether MM OS itself is actually reachable from the affected service:
   ```bash
   curl -sf https://os.m-mines.com/healthz    # from the service's own host/container
   ```
2. Check the affected service's own logs for `mmos: revocation poll failed, keeping last known
   deny-list` (from `_denylist.py`'s logger) — this fires on every failed poll and names the
   underlying exception.
3. If MM OS is down: see §12. Once it's back, the poller picks up on its normal schedule with
   no manual restart needed (it's a background thread, not a one-shot).
4. If MM OS is up but a specific service can't reach it: check that service's `MMOS_SERVICE_KEY`
   is still valid (has it been rotated since?) and that network routing between the two hasn't
   changed. A revoked/rotated key returns `401 service_key_invalid` from `/api/agent/revocations`
   — the poller logs this as a generic poll failure, so check the response manually if the
   generic log line doesn't say why:
   ```bash
   curl -s https://os.m-mines.com/api/agent/revocations?since=2020-01-01T00:00:00Z \
     -H "Authorization: Bearer $MMOS_SERVICE_KEY"
   ```
5. **While the poll is failing, that service's deny-list is frozen at whatever it last
   successfully fetched.** If you are mid-emergency-revoke (§9) and a service's poller has been
   down for a while, that service will not honor the revocation until its poller recovers —
   treat this as a reason to also block the person at the network layer (VPN peer deletion,
   §5 step 3) rather than relying on the deny-list alone during an active incident.

## 12 · When things are down

**MM OS itself is down:**
```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs --tail=100 api
curl -sf http://localhost:8000/healthz     # from the VPS itself, bypassing the network gate's
                                            # own private-mode check is not needed here --
                                            # /healthz is always open (middleware.py ALWAYS_OPEN)
```
Every registered service keeps working with its last-known deny-list and cached `llm_enabled`
flag (see §11) — existing sessions/tokens on those services are unaffected until they expire.
New sign-ins to MM OS itself, and new service-token minting, are unavailable until it's back.

**Postgres is down:** `GET /healthz` reports `{"ok":true,...,"db":"down"}` (it still answers —
the process is up even if the DB isn't). Check `docker compose ... logs postgres` and the
`mmos_pgdata` volume. Nothing writes without it; existing service tokens keep verifying (JWKS
and revocation-list state are cached client-side) until their 15-minute TTL or until a poll for
fresh revocations is needed and fails (§11).

**Frappe Cloud (ERPNext) is down:** this is entirely outside MM OS — ERPNext is `launch_mode`
`handoff`/its own hosted SaaS, and MM OS only hands off a token to it. MM OS itself, and every
other service, are unaffected. Nothing to do on the MM OS side.

**Certificates expired:** Coolify's DNS-01 renewal should auto-renew well before expiry
(`deploy/NETWORK.md` §4) — an actual expiry means the renewal itself silently failed. Check
Coolify's certificate status in its dashboard first; if DNS-01 is broken (API token expired/
revoked at the DNS provider), fix that credential and force a renewal. Do **not** fall back to
HTTP-01 — this deployment has no public port 80 for it to use.

**A laptop is lost:** delete its VPN peer immediately (`deploy/NETWORK.md` §2, `wg-easy`
admin) — this is the fastest real block, faster than trying to figure out who was signed in on
it. Then, if the person is identifiable and it's their only device, consider whether their PIN
should be reset (§6) and whether an emergency kill (§9) is warranted if the laptop was left
signed in to an active session.

## 13 · Where logs, backups and the audit trail live, and how long each is kept

| What | Where | Retention |
|---|---|---|
| Application logs | container stdout/stderr, `docker compose logs`, plus Coolify's own copy | whatever Coolify's log retention is configured to (check its dashboard — not an MM OS setting) |
| `audit_log` table | Postgres, queried via `GET /api/admin/audit` / the Audit admin tab | kept forever — nothing deletes it. Backups (below) are the only thing that could lose it |
| `revocations` table | Postgres | purged automatically ~2h after each row's block window ends (`purge_after`) — an empty table is normal |
| Nightly backups | `$BACKUP_DIR` (default `/var/backups/mmos`) + `$OFFSITE_DEST` if configured | `$RETENTION_DAYS` (default 14) locally; off-site retention is whatever the destination enforces — **confirm `OFFSITE_DEST` is actually set in production**, `scripts/backup.sh` only warns if it's empty, it does not fail the run |

## 14 · Restore from backup into a scratch database

```bash
# One-off, or the quarterly test below -- always into a SCRATCH database by default:
BACKUP_PASSPHRASE=<real> POSTGRES_PASSWORD=<real> \
  scripts/restore.sh /var/backups/mmos/mmos_mmos_<timestamp>.dump.enc
# creates and restores into mmos_restore_<UTC now>, never touches the live "mmos" database

psql -h <pghost> -U mmos -d mmos_restore_<timestamp> -c "SELECT count(*) FROM employees;"
psql -h <pghost> -U mmos -d mmos_restore_<timestamp> -c "SELECT count(*) FROM audit_log;"
# compare against what you'd expect from the live system on that backup's date

dropdb -h <pghost> -U mmos mmos_restore_<timestamp>   # once satisfied
```

**Quarterly restore-test procedure** (put this in an actual calendar, not memory — same
warning `deploy/NETWORK.md` gives the VPN-peer audit):

1. Pick the most recent nightly backup.
2. Run the restore above.
3. Compare row counts on `employees` and `audit_log` (and any table you know should be
   growing) against expectations for that date.
4. Drop the scratch database.
5. If the restore failed, or the counts don't add up, the backup is not a backup — fix the
   pipeline before the next quarter, not after the next real incident.

`scripts/verify/verify-backup.sh [database]` automates the mechanical parts of this (syntax
checks on `backup.sh`/`restore.sh` always; a real dump → encrypt → decrypt → restore →
row-count-compare round trip if `PGHOST` is reachable and `POSTGRES_PASSWORD`/
`BACKUP_PASSPHRASE` are set) — run it as part of the quarterly test, not instead of the manual
row-count sanity check above.

**Status as of this handoff: a restore has never been performed for real** — there is no
Postgres reachable from the build machine this was written on. `docs/08`'s definition-of-done
#8 ("a restore from backup has been performed into a scratch database and verified") is
therefore **not met yet** — this is the exact procedure to run once there is a live deployment
with at least one real nightly backup to restore. See `handoff/b3-hardening.md` `## Not done`.

## 15 · Monthly VPN-peer-versus-active-employee audit

Full checklist and the diff commands are in `deploy/NETWORK.md` §5. Summary: export the
`wg-easy` peer list, export `employees` where `status='active'`, every peer's employee-code
prefix must appear in the active list (delete any that don't — immediately, not just disable),
and every active employee who should have VPN access should have at least one peer. Record the
audit date and who ran it somewhere durable (a shared doc or ticket — this manual step is not
itself an MM OS audit-log event).

## 16 · Known limits (read before scaling anything)

- **Rate limiting is in-process and in-memory** (`POST /api/token/service`, 60/min/user). This
  is fully effective at the current single-worker, single-replica deployment
  (`deploy/Dockerfile`'s `CMD` has no `--workers` flag; `docker-compose.yml` runs one `api`
  container). The moment either changes, every limit silently becomes N times more permissive
  with no error and no warning. See `docs/11-security-review.md` finding #3 before adding a
  second worker or replica.
- **`GET /api/agent/org/chain` has no per-endpoint service ACL** — any service holding a valid
  service key can walk any subject's manager chain (minimum-disclosure fields only). See
  `docs/11-security-review.md` finding #5.
- **`POST /api/auth/pin` has no per-IP throttle**, only per-account lockout — see
  `docs/11-security-review.md` finding #2 before assuming it's DoS-proof.
