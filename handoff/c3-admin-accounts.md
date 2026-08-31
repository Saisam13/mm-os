# C3 — Functional-account "add & customize" admin surface

Adds the operational UI + API for managing the FUNCTIONAL-MAILBOX accounts MM OS now
provisions (purchase.c2@, central.stores@, sales@ ...). Additive only; no frozen-spine edit.

## Shared-core refactor (behavior-preserving)
The per-row provisioning core moved out of `scripts/provision_functional.py` into
`backend/app/provision.py` so the CLI loader and the new API endpoint share ONE implementation
and can never drift:

- New in `app/provision.py`:
  - `provision_account(db, *, employee_code, login_email, department, role="requester",
    approval_level=None, platform_admin=False, commit=True, reset=False, pin_length=6) -> AccountResult`
  - `AccountResult` dataclass (same attribute names the CLI report/PIN-writer already consume),
    plus helpers `label_from_email`, `_ensure_functional_employee`, `_ensure_functional_user`,
    and constants `DEFAULT_FUNCTIONAL_ROLE`, `FUNCTIONAL_JOB_TITLE = "Functional Mailbox"`.
- `scripts/provision_functional.py` now keeps only roster-CSV concerns (`load_roster`, report,
  PIN CSV). `process_row(...)` is a thin wrapper that calls `provision_account`; `RowResult` is a
  local alias of `AccountResult`. **Behavior is identical — `test_provision_functional.py` stays
  green untouched.**

## Endpoints (routers/people.py, all under /api/admin, require_admin)
- `GET  /accounts?dept=` — list functional accounts (Employee.job_title == "Functional Mailbox").
  Personal employees stay on the People page and never appear here.
- `POST /accounts` — create/customize ONE. Body `{email, department, role?, approval_level?,
  platform_admin?, employee_code?, reset?}`. Idempotent on email (re-post updates in place).
  Returns `{account, pin, created}`; `pin` is the one-time must-change PIN, present only when one
  is issued (new account, or `reset:true`). No `employee_code` in the body → derived from the
  mailbox local-part, uniquified.
- `POST /accounts/bulk` — Body `{rows:[...], dry_run}`. `dry_run:true` reports would-create/
  would-update and writes nothing (rolls back); `dry_run:false` applies and returns `pins[]`.
  CSV is parsed on the FRONTEND and sent as JSON rows (no multipart upload).
- `POST /accounts/{id}/reset-pin` — reissue a one-time must-change PIN (via `issue_one_time_pin`).
- `PATCH /accounts/{id}` — set/clear approval_level, toggle platform_admin, activate/deactivate,
  edit department/label. `{id}` is the user id.

## Blank-vs-set field behavior
- **Create/bulk** (`provision_account`): a blank `approval_level` never overwrites one already on
  file; a falsey `platform_admin` never demotes an existing admin — same contract the roster
  loader documents.
- **PATCH**: only keys PRESENT in the body change; an ABSENT key is untouched. To CLEAR
  `approval_level`, send it explicitly as `null` or `""`.
- **platform_admin toggle on**: satisfies models.py `no_pin_admins` the same way provisioning
  does — flips `auth_type='google'`, sets `login_email` (from the user's or employee's email),
  keeps the PIN. A head with no email available → 422 `admin_no_email`.

## Frontend surface
- New tab **Accounts** in `AdminTabs`, route `/admin/accounts` (`pages/admin/AccountsPage.tsx`).
- List filterable by department; columns email, department, approval level, "head" badge, status
  (+ "PIN pending" chip when must_change).
- **Add account** dialog → `createAccount`, reveals the one-time PIN once (with copy).
- **Bulk import** dialog: paste roster CSV, parsed client-side, **dry-run preview** (would-create/
  update counts + rows) then Confirm commits and shows the PIN list with a "Copy all" affordance.
- **Per-account drawer**: set/clear approval level, make/remove management head, reset PIN (shown
  once), deactivate/reactivate.
- API wired through `contract.ts` / `client.ts` / `mock.ts` (dev mock keeps a small in-memory
  functional-account store, seeded with two, so `VITE_USE_MOCK` demos still work).
- Types added to `api/types.ts`: `FunctionalAccount`, `AccountRosterRow`, `AccountBulkRow`,
  `AccountBulkPin`, `AccountBulkResult`, `AccountCreateResult`.

## Tests
`backend/tests/test_admin_accounts.py` (synthetic data only): create + idempotency-on-email,
bulk dry-run-vs-commit, bulk idempotency, set/clear approval level (absent key never clobbers),
platform-admin toggle (no_pin_admins not tripped), deactivate, reset-pin, list excludes personal
employees + dept filter, non-admin 403.

## Frozen-spine tension deferred
None required a model change. Functional accounts are identified purely by the existing
`Employee.job_title == "Functional Mailbox"` marker the CLI already sets — no new column. If a
first-class "account kind" flag is ever wanted, that would be a models.py change and belongs to
the live phase, not here.

## Remaining for the live phase
- `role` is recorded on `Employee.notes` only (no Grant is created — a department name is not a
  service slug; unchanged from the CLI's deliberate decision). Granting each functional mailbox
  its actual services still goes through the existing Access page / `POST /api/admin/grants`.
- Everything is SQLite-tested; the Postgres `no_pin_admins`/uniqueness behavior is exercised by
  the CHECK constraints but not proven against a real server here.
