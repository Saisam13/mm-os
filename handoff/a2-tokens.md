# A2 · Tokens, registry and control plane

## Delivered

- `backend/app/routers/tokens.py` — `POST /api/token/service`. Requires `current_user` +
  `current_employee`, looks up the service by slug and the user's `Grant` for it (rejecting
  an expired grant), mints via `security.mint_service_token` with the grant's role, and
  returns `{access_token, token_type, expires_in, launch_url}` with the token in the URL
  fragment. Audits `token.issue` (with `jti` in metadata) on success and `token.denied` on
  refusal. Rate-limited 60/minute per user via an in-memory sliding window.

- `backend/app/routers/agent.py` — service-to-MM-OS, all behind `require_service_key`:
  - `GET /revocations?since=` (mounted at `/api/agent/revocations` — see Contract
    objections) scoped to the calling service plus global (`service_id IS NULL`) rows,
    with `poll_after_seconds` normally `settings().revocation_poll_seconds`, dropped to 5
    for ten minutes after an `admin_kill` revocation exists in scope.
  - `POST /heartbeat` — strips any field that looks like a credential (name-based match,
    `key_present` explicitly excluded) from both the top level and the `llm` sub-object,
    audits `heartbeat.key_rejected` with the dropped field names (never values) when it
    finds one, upserts `llm_registrations` (provider defaults to `unreported` when no
    `llm` block is sent), and accumulates `llm_usage_daily` by `(service_id, day)`.
  - `GET /config` — `{llm_enabled, config_version, poll_after_seconds}`.
  - `config_version` is derived by counting `audit_log` rows with
    `action IN ('llm.enable','llm.disable')` for that service — see Assumptions for why
    there's no dedicated column.
  - `purge_expired_revocations(db)` deletes rows past `purge_after`; a daemon thread calls
    it hourly (skipped when `settings().environment == "test"`). Tested directly rather
    than via a wall-clock wait.

- `backend/app/routers/platform.py` — all behind `require_admin`, mounted at `/api/admin`:
  services (list/create/patch/roles/rotate-key), grants (list/create/delete/bulk — delete
  writes a `revocations` row in the same transaction, same for the `kill` route), LLM
  (`GET /llm` overview + 30-day usage, `POST /llm/{slug}/toggle`), `GET /audit` with
  actor/action/date filters and keyset cursor pagination, and
  `POST /users/{id}/kill` (subject-level global revocation plus best-effort jti-level
  revocations for tokens issued to that user within the last TTL window, read back from
  `audit_log`).

- `backend/tests/test_security.py` — 9 tests against `app/security.py` using a reference
  verifier (`verify_as_service`) that mirrors the exact order in docs/04-auth-flow.md:
  `aud` mismatch, expired token, tampered signature, unknown `kid`, hand-built `alg: none`,
  hand-rolled RS256->HS256 confusion (bypassing python-jose's own guard against using a
  PEM as an HMAC secret, since a real attacker would too), subject deny-list, jti
  deny-list, and a JWKS sanity check.

- `backend/tests/test_platform.py` — 16 tests: the token handoff (success, no grant,
  unknown slug, expired grant), grant deletion -> immediate appearance in
  `/api/agent/revocations`, cross-service revocation isolation, `kill` writing a
  revocation and dropping `poll_after_seconds` to 5, key rotation invalidating the old key
  immediately, every owned `/api/admin/*` route returning 403 for a signed-in non-admin
  and 401 with no session, LLM toggle bumping `config_version` in both directions, toggle
  off reflected on `GET /api/agent/config`, heartbeat stripping a key-shaped field without
  storing it (plus the `unreported` default and usage accumulation), and grants/bulk
  filtering by band while skipping an existing grant.

## Deviations

- `POST /api/token/service` returns `403 grant_not_found` uniformly whether the service
  slug doesn't exist, the service is inactive, or the grant is missing/expired — the brief
  and docs/03 only describe the grant case, but collapsing all three avoids leaking which
  slugs exist to a user probing without a grant.
- `revoked_jti` in `GET /api/agent/revocations` is a flat list of jti strings (not
  objects), and a revocation row is reported under `revoked_subjects` xor `revoked_jti`
  based on whether its `jti` column is set — docs/03's example shows `revoked_jti: []`
  with no populated shape to match against.

## Contract objections

1. **`main.py` mounts `agent.router` at prefix `/api/agent` for every route in that file,
   but docs/03-api-contract.md shows `GET /api/revocations` (no `/agent`) while showing
   `POST /api/agent/heartbeat` and `GET /api/agent/config` *with* it** — the doc is
   internally inconsistent, and `main.py` (frozen) can only apply one prefix to the whole
   router. I followed the frozen code, since I can't edit it: revocations lives at
   `GET /api/agent/revocations`. Whoever owns `mmos-client-py` (A4) needs to poll that
   exact path, not the bare one in the doc. Fixing this cleanly needs either a `main.py`
   change (mount agent.router with no prefix and give heartbeat/config their own explicit
   `/api/agent/...` paths) or a docs correction — both out of my ownership.

2. **`HTTPException(status_code, detail={"error": ..., "message": ...})` — the pattern
   already established in frozen `deps.py` — does not produce the flat
   `{"error","message","request_id"}` shape docs/03 documents.** FastAPI's default
   handler wraps it as `{"detail": {"error": ..., "message": ...}}`, and `main.py` (frozen)
   registers no exception handler to flatten that. This isn't unique to my routers — it's
   every error response in the app, because it comes from `deps.py` + `main.py` both being
   frozen. My tests assert on `response.json()["detail"]["error"]` to match actual
   behaviour. A1's and A3's error-handling code and tests should account for the same
   wrapping. Fixing it needs a `main.py` exception handler (frozen) or a different
   `deps.py` convention (frozen) — I did not touch either, per the guardrails.

3. `Revocation.purge_after` is `nullable=False` in `models.py` with no Python-side
   default, even though docs/02's SQL DDL gives it `DEFAULT (now() + interval '2 hours')`.
   I supply `revoked_at + timedelta(hours=2)` explicitly everywhere I create a
   `Revocation` row, matching the documented interval, but this lives in three call sites
   in `platform.py` rather than one shared default — worth adding to the model if A1's
   migration pass touches it.

## Assumptions

- **`config_version` has no column anywhere in `models.py`** (frozen) and I was told not
  to add one without recording it here. I derive it by counting `audit_log` rows with
  `action IN ('llm.enable','llm.disable')` scoped to the service. This is monotonic,
  durable across restarts, and needs no schema change, but it does mean `config_version`
  is not a value you can reset independently of the audit trail — please confirm this is
  acceptable, or tell me which column to add and I'll do it in the next pass.
- **The heartbeat's own `llm.enabled` field is ignored for setting the DB flag.** The data
  model comment says `enabled` is "the kill switch MM OS owns"; letting a service's
  heartbeat overwrite it would let a service silently re-enable itself after an admin
  disabled it. `enabled` is only ever set by `POST /api/admin/llm/{slug}/toggle`.
- **`POST /api/admin/llm/{slug}/toggle` audits `llm.enable` when turning it on and
  `llm.disable` when turning it off.** The brief's literal text only names `llm.disable`
  (illustrated with a `{"enabled": false}` example body), but the route accepts both
  directions and `config_version` needs to bump symmetrically either way.
- **`kill`'s "jti-level" revocation** is read back from recent `token.issue` audit rows
  for that user (within one token TTL) rather than from a live jti table, since none
  exists. This is best-effort defence in depth on top of the subject-level (global)
  revocation, which is the one that actually guarantees the block.
- **Rate limiting (60/min/user) is in-process, in-memory** (a `dict[str, deque[float]]` in
  `tokens.py`). Correct for a single worker; a multi-worker/horizontally-scaled deployment
  would need a shared store (Redis) instead. No new dependency was added for this.
- **`POST /api/admin/grants/bulk`** filters by `band` and `department` as an AND when both
  are supplied (docs/03 only shows the `band`-only example). Existing grants for matching
  users are silently skipped, not upserted/overwritten.
- **`GET /api/admin/audit` cursor** is an opaque base64 of `"{created_at.isoformat()}|{id}"`,
  keyset-paginated on `(created_at, id)` descending — no format was specified beyond
  "cursor pagination".
- The non-admin/no-session 403/401 sweep tests (`test_every_owned_admin_route_...`,
  `test_admin_routes_require_a_session_at_all`) only cover the `/api/admin/*` routes this
  agent owns (`services`, `grants`, `llm`, `audit`, `users/{id}/kill`) — A1's
  `employees`/`users` admin routes in `people.py` are still stubs as of this run, so they
  aren't and can't be exercised here.

## Not done

- Nothing marked `needs_postgres` — everything I own runs on SQLite via the shared
  harness. No JSONB containment operators or other Postgres-only features were needed.
- I did not add coverage for `POST /api/admin/services/{slug}/roles` beyond the happy
  path (no test for the duplicate-role-key 409), nor for `PATCH /api/admin/services/{slug}`
  beyond what the 403 sweep exercises — these aren't in the brief's acceptance list and I
  kept tests targeted rather than exhaustive.

## How to verify

```bash
cd "C:/Users/Anura/OneDrive/Desktop/MM OS/backend"
.venv/Scripts/python.exe -m pytest tests/test_security.py tests/test_platform.py -q
# 25 passed

.venv/Scripts/python.exe -m pytest -q
# 33 passed (includes the 8 orchestrator-owned harness smoke tests)
```

No Docker, no Postgres, no `.env`, no real secrets touched. All work is inside
`backend/app/routers/{tokens,agent,platform}.py` and
`backend/tests/test_security.py` / `backend/tests/test_platform.py`.
