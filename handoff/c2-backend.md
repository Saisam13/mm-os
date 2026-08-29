# C2 · In-house backend completion — rate limiter, LLM control plane, provisioning

Agent C2. L1/L2 in-house backend + integration completion phase (28–29 Aug 2026). All work is
real files on disk; **no git was run** (orchestrator owns version control). The test harness
(`backend/tests/conftest.py`, `test_harness_smoke.py`) was NOT touched.

Final suite: **106 passed, 1 skipped** (`cd backend && .venv\Scripts\python.exe -m pytest tests -q`).
That is the prior 91 passed + 1 skipped plus **15 new tests** across four new files.

## Frozen-spine edits (exact)

Only **one** frozen-spine file was changed: `backend/app/models.py`, and only additively.

1. Import line: added `BigInteger` to the `sqlalchemy` import tuple.
2. New table `RateLimit` (`rate_limits`) — the shared, multi-worker-safe rate-limit counter:
   columns `id` (uuid pk), `bucket` (String(96)), `window_key` (BigInteger), `count` (Integer),
   `created_at`; `UniqueConstraint(bucket, window_key)` = `uq_rate_limit_bucket_window`; and
   `Index("ix_rate_limits_window", "window_key")`.

No other frozen-spine change. The three other tables added this phase (`LlmFeature`,
`LlmFeatureUsageDaily` in `app/llm_control.py`; `PinMustChange` in `app/provision.py`) attach to
the same `Base.metadata` from *new* modules, so models.py itself was not touched for them.

Non-frozen support edit: `backend/alembic/env.py` now `import app.llm_control` and
`import app.provision` so `target_metadata` is complete for migration 0002 / `alembic check`.
(The `RateLimit` table needs no extra import there — it lives in models.py, already imported.)

## Gaps closed this phase

| Gap | What | Files |
|---|---|---|
| BE-6 | Removed the `--workers 1` pin — DB-backed limiter makes scaling safe | `deploy/entrypoint.sh`, `deploy/docker-compose.coolify.yml`, `docker-compose.yaml`, `deploy/.env.production.example`, `docs/10-runbook.md` §16 |
| Demo opt-in | Confirmed `--demo` is a no-op unless `MMOS_ENABLE_DEMO_SEED=1`; added proof | `app/seed.py` (already gated), `tests/test_seed_demo_optin.py` (new) |
| Mgmt layer | Provisioning can grant full IT-admin-equivalent access | `app/provision.py`, `routers/people.py`, `scripts/provision_people.py`, `tests/test_provisioning.py` (new) |
| Tests | Focused coverage of the new surface | `tests/test_ratelimit.py`, `tests/test_llm_control.py`, `tests/test_provisioning.py`, `tests/test_seed_demo_optin.py` (all new) |
| Docs | Service-facing LLM contract | `docs/15-llm-control-plane.md` (new), pointer added in `docs/05` |

### The `--workers 1` removal (BE-6)

The pin existed because the PIN-login and service-token limiters were in-process deques — one
budget per worker, so a second worker N-times-weakened every limit. `app/ratelimit.py` moved that
state into the shared `rate_limits` table (fixed-window counter, atomic conditional `UPDATE`,
over-budget hits write nothing). All serving entry points now leave uvicorn at its default (1
worker) but **no longer forbid scaling**; the runbook §16 bullet and the `.env` checklist line were
rewritten to say scaling is safe and Redis is no longer a prerequisite. MM OS's own revocation
deny-list was always served from the `revocations` table, never per-worker.

### Management layer = full IT-admin power (owner decision, 28 Aug 2026)

`provision_by_code(..., platform_admin=True)` grants the SAME access as the itadmin layer (act +
approve + see everything), **not** a view-only role. Mechanism, forced by the frozen `no_pin_admins`
CHECK ("a PIN user on a shared terminal must never hold admin rights"): an admin can never be
`local_pin`, so the flag flips the user to `auth_type='google'` with their corporate `login_email`,
sets `is_platform_admin=True`, and **still issues a one-time must-change PIN** — PIN login works
because it keys off `pin_hash`, not `auth_type`. A head with no `work_email` returns status
`no_email` rather than tripping the CHECK at commit. Surfaced through `POST /api/admin/provision`
(`"platform_admin": true`) and `scripts/provision_people.py --platform-admin`. This deliberately
gives heads IT-level power.

## LLM control-plane contract (summary)

MM OS governs policy/enablement/usage for every AI feature and **holds no provider API key** — keys
stay in the service; key-shaped fields are stripped and audited (`heartbeat.key_rejected`), and no
control-plane table has a secret column (only `key_present`, a boolean). Service-facing, service-key
auth: `GET /api/agent/llm/policy` (kill switch + per-feature allow-lists + monotonic
`config_version` to poll), `POST /api/agent/llm/register` (declare features), `POST /api/agent/llm/usage`
(per-feature daily metering). Effective feature enablement = `service.enabled AND feature.enabled`.
Admin side in `routers/platform.py` (`/api/admin/llm...`); full contract in `docs/15-llm-control-plane.md`.

## Provisioning + PIN-change mechanism

`issue_one_time_pin` sets `pin_hash` + `pin_set_at` and adds a `PinMustChange` row. `POST /api/auth/pin`
returns `must_change: true` while that row exists; `POST /api/auth/pin/change` (requires the current
PIN as proof) rotates the PIN and clears the flag. `scripts/provision_people.py` imports named people
from the sheet in place and issues PINs a handful at a time — no employee names/emails enter the repo.

## Needs live (cannot be done on the build machine)

- **Apply migration 0002 on real Postgres.** SQLite tests cover the ORM; run `alembic upgrade head`
  against the VPS Postgres and confirm `rate_limits`, `llm_features`, `llm_feature_usage_daily`,
  `pin_must_change` exist. (JSONB allow-lists on `llm_features` are Postgres-only — proven only there.)
- **Register the real services' AI features** via `POST /api/agent/llm/register` from each deployed
  service (Item Code Studio, ATT, OCR, Purchase), then verify `/api/admin/llm/features`.
- **Run real provisioning for named people** once the owner names the batch:
  `provision_people.py --codes ... --commit`, and `--platform-admin` for the management heads
  (confirm each head has a `work_email` on file first).
- **Optionally scale** — raising `--workers`/replicas is now safe; no code change needed.
