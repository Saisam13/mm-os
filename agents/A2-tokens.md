# Agent A2 · Tokens, registry and control plane

You are building the trust layer of **MM OS**, the internal operating system for MiniMines
(~74 staff). MM OS hands every service a short-lived token saying who the user is and what
they may do there. You are one of six agents building in parallel; the contracts are fixed.

This is the component where a subtle bug is a **silent security hole** rather than a visible
failure. Write the tests before the implementation.

**Read first:** `docs/03-api-contract.md`, `docs/04-auth-flow.md`, `docs/01-architecture.md`
(the LLM control plane section), `docs/02-data-model.md`.

## You own exclusively

```
backend/app/routers/tokens.py     backend/tests/test_security.py
backend/app/routers/agent.py      backend/tests/test_platform.py
backend/app/routers/platform.py
```

## Frozen — read them, use them, never edit them

`backend/app/{config,models,db,security,deps,middleware,main}.py`. `security.py` already
implements `mint_service_token`, `jwks`, `new_service_key`, `hash_token`. `deps.py` already
implements `require_admin`, `require_service_key`, `audit`, `client_ip`. Use them. If one is
wrong, record it under `## Contract objections` and work around it locally.

**You do not own migrations.** Agent A1 generates the only Alembic migration. The schema in
`models.py` already has every table you need — do not add one. If you genuinely need a
column, put it in the handoff.

## Deliverables

1. **`routers/tokens.py`** — `POST /api/token/service {"slug": "..."}`
   - requires a live session (`current_user`) **and** a matching non-expired grant, else `403 grant_not_found`
   - mints via `security.mint_service_token` with the user's role in *that* service
   - returns `{access_token, token_type, expires_in, launch_url}` where `launch_url` is `{service.base_url}/_mmos/accept#token=...`
   - the token goes in the URL **fragment**, never the query string — fragments are not sent to servers and not logged by proxies
   - audits `token.issue` with the service id, and `token.denied` on refusal
   - rate limit 60/minute per user

2. **`routers/agent.py`** — service-to-MM-OS, authenticated by `require_service_key`
   - `GET /api/revocations?since=` — returns the documented shape, scoped to the calling
     service plus global entries, with `poll_after_seconds` from settings
   - `POST /api/agent/heartbeat` — upserts `llm_registrations` (provider, model,
     `key_present`, `last_seen_at`) and accumulates `llm_usage_daily` by
     `(service_id, day)`. **A heartbeat must never carry an API key; if a field that looks
     like a key is present, drop it and audit `heartbeat.key_rejected`.** Returns
     `{llm_enabled, config_version}`.
   - `GET /api/agent/config` — `{llm_enabled, config_version, poll_after_seconds}`
   - A service that sends no `llm` block shows as `provider='unreported'` — visible on
     purpose, never silently blank.
   - A background task purges `revocations` past `purge_after` hourly.

3. **`routers/platform.py`** — admin, all behind `require_admin`, per `docs/03`
   - services: list, create, patch, `POST /{slug}/roles`, `POST /{slug}/rotate-key` (returns the key once, stores only the hash)
   - grants: list, create, delete, `POST /grants/bulk` filtered by band or department
   - **deleting a grant writes a `revocations` row in the same transaction** — never a two-step
   - `GET /api/admin/llm` — registrations plus 30 days of usage per service
   - `POST /api/admin/llm/{slug}/toggle {"enabled":false,"reason":"..."}` — flips the flag, records `disabled_by`, `disabled_at`, `disabled_reason`, bumps `config_version`, audits `llm.disable`
   - `GET /api/admin/audit` — filter by actor, action, date range; cursor pagination
   - a `kill` route: `POST /api/admin/users/{id}/kill` writing a `jti`-level plus subject-level revocation and dropping `poll_after_seconds` to 5 for ten minutes

4. **`backend/tests/test_security.py`** — written **first**. A token must be rejected when:
   the `aud` is a different service; it has expired; the signature is tampered with; the
   `kid` is unknown; the algorithm is switched to `HS256` or `none` (the classic JWT
   confusion attack — assert this explicitly); the subject is on the deny-list.

5. **`backend/tests/test_platform.py`** — grant deletion writes a revocation atomically;
   `rotate-key` invalidates the old key immediately; a non-admin gets `403` on every
   `/api/admin/*` route; the LLM toggle bumps `config_version`; a heartbeat containing a
   key-shaped field is rejected without storing it.

## Acceptance tests you must make pass

- a token minted for `itemcode` fails verification when presented as `att`
- `alg: none` and `alg: HS256` tokens are rejected
- deleting a grant makes the subject appear in `/api/revocations` immediately
- `/api/revocations` from service A never leaks service B revocations
- heartbeat with `usage` accumulates rather than overwrites the day row
- LLM toggle off, then `GET /api/agent/config` returns `llm_enabled: false`
- every `/api/admin/*` route returns 403 without `is_platform_admin`

## Guardrails

Do not refactor. No schema changes. No new dependencies without recording them. Targeted
tests only. If a failure resists two fixes, write it under `Not done` and move on. Never
touch `.env`, real secrets, or the live ERPNext instance.

## Finish by writing `handoff/a2-tokens.md`

`## Delivered`, `## Deviations`, `## Contract objections`, `## Assumptions`, `## Not done`,
`## How to verify`.
