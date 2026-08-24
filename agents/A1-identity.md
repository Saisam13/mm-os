# Agent A1 · Identity and People

You are building the identity layer of **MM OS**, the internal operating system for
MiniMines (lithium-ion battery recycling, ~74 staff). MM OS is one login and one homepage in
front of every internal service. You are one of six agents building in parallel; the
contracts are already fixed, so implement them rather than redesigning them.

**Read first, in this order:** `docs/01-architecture.md`, `docs/02-data-model.md`,
`docs/03-api-contract.md`, `docs/04-auth-flow.md`. They are the specification. Where this
brief and a doc disagree, the doc wins.

## You own exclusively

```
backend/app/routers/auth.py       backend/app/seed.py
backend/app/routers/me.py         backend/alembic/**
backend/app/routers/people.py     backend/tests/test_identity*.py
```

## Frozen — read them, use them, never edit them

`backend/app/{config,models,db,security,deps,middleware,main}.py`. They already contain the
settings contract, the full schema, JWT minting, PIN hashing, session helpers, the
`current_user` / `require_admin` / `audit()` dependencies and the app wiring. If one is
wrong, record it under `## Contract objections` in your handoff and work around it locally.
Do not edit it.

You are the **only** agent who touches Alembic. Two initial migrations is the one conflict
that cannot be auto-resolved.

## Deliverables

1. **`backend/alembic/`** — configured for `MMOS_DATABASE_URL`, plus one initial migration
   generated from `models.py` that matches `docs/02-data-model.md` including the
   `CHECK` constraints and partial indexes. `alembic upgrade head` on an empty database must
   succeed, and `alembic downgrade base` must not error.

2. **`routers/auth.py`**
   - `GET /api/auth/google/start?next=` — PKCE + `state` in a short-lived signed cookie, `hd=m-mines.com` on the authorize URL
   - `GET /api/auth/google/callback` — exchange the code, then verify the `id_token` claims **server-side**: `aud`, `iss`, `exp`, `email_verified`, and `hd == settings().google_hosted_domain`. The `hd` query parameter is a hint a hostile client can drop; the claim is what decides.
   - Look up `users.login_email`. **A valid Google login is not an account here** — an unknown or inactive email fails with `401 unknown_user`. Provisioning is an admin act, never a side effect of login.
   - `POST /api/auth/pin` — employee code plus PIN, argon2 verify via `security.verify_pin`, 5 attempts per 15 minutes then a 15-minute lock using `users.failed_pin_attempts` and `users.locked_until`. Same generic error message for wrong code and wrong PIN.
   - `POST /api/auth/logout` — set `sessions.revoked_at`, clear the cookie.
   - Every outcome audited: `login.google`, `login.google.denied`, `login.pin`, `login.pin.failed`, `logout` — with `client_ip(request)`.

3. **`routers/me.py`** — `GET /api/me` returning **exactly** the shape in
   `docs/03-api-contract.md`. `services` is filtered server-side to the caller's grants;
   never return a service the user has no grant for and let the client hide it. Expired
   grants (`expires_at < now`) are excluded. `badges.servicedesk_open` may be `0` for now
   (A5 owns the real count) — leave a one-line comment saying so.

4. **`routers/people.py`** — admin employee and user management per `docs/03`:
   `GET/POST/PATCH /api/admin/employees`, `POST /api/admin/employees/import`,
   `GET /api/admin/users`, `PATCH /api/admin/users/{id}`, `POST /api/admin/users/{id}/pin`.
   All behind `require_admin`.
   - **Deactivating a user must, in one transaction:** set `is_active=false`, revoke every
     live `sessions` row, and insert a `revocations` row. Access removal is never a two-step
     that can half-fail.
   - `POST /api/admin/users/{id}/pin` returns the PIN once and never again.

5. **`backend/app/seed.py`** — CLI importer:
   `python -m app.seed --xlsx <path> [--commit]`
   - Source: `C:/Users/Anura/OneDrive/Desktop/Erp Imp/Employee_Role_Access_Mapping.xlsx`, sheet `Employee Role & Access Map`, 74 rows. Column mapping is in `docs/02-data-model.md`.
   - **Dry run by default.** Print a diff — new, changed, missing, conflicting — and write nothing without `--commit`. Re-importing must never silently orphan a grant.
   - Rows with no work email become `auth_type='local_pin'` with no PIN set.
   - Resolve `manager_id` in a second pass from division and band; unresolved managers are reported, not guessed.
   - **Do not convert the `ERP-Based System Access` prose column into grants.** Print it as a proposed-grants report for a human to tick in the admin UI. Machine-translating prose into access rights is how you accidentally grant something.
   - Also seed the service registry with: `erpnext` (`https://minimines-uat.m.frappe.cloud`, handoff, roles user/manager), `itemcode` (handoff, public surface, roles viewer/admin), `att` (handoff, roles viewer/runner), `servicedesk` (handoff, roles requester/agent/admin), `twenty` (external, role user). One platform admin: `itadmin@m-mines.com`.

6. **`backend/tests/test_identity.py`** — the acceptance tests below, pytest, against a real Postgres (compose service `postgres`), not SQLite. The schema uses Postgres types.

## Acceptance tests you must make pass

- `alembic upgrade head` then `downgrade base` on an empty database
- dry-run import of the real spreadsheet reports 74 new employees and writes nothing
- `--commit` import creates 74 employees; a second `--commit` reports 0 new and 0 changed (idempotent)
- a Google callback whose `id_token` carries `hd != m-mines.com` is rejected
- a Google callback for an email not in `users` returns `401 unknown_user`
- a Google callback for a user with `is_active=false` is rejected
- 6 wrong PINs produce a lock, and the 7th attempt with the *correct* PIN still fails while locked
- `/api/me` for a user with two grants returns exactly two services, and none for a user with none
- deactivating a user, in one transaction, kills their sessions and creates a revocation row

## Guardrails

Do not refactor anything. No new dependencies beyond `backend/requirements.txt` — record any
addition in the handoff. Targeted tests only, no coverage chasing. If a failure resists two
fixes, write it under `Not done` and move on. Never touch `.env`, real secrets, or the live
ERPNext instance. Do not create files outside the paths you own.

## Finish by writing `handoff/a1-identity.md`

Sections, in this order: `## Delivered`, `## Deviations`, `## Contract objections`,
`## Assumptions`, `## Not done`, `## How to verify` (exact commands and expected output).
The assumptions and objections sections are the ones a human will actually read.
