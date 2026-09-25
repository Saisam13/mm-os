# Bulk access: state and deploy steps (25 Sep 2026)

Brief: `handoff/NEXT-bulk-access.md`. Decisions: `docs/16-decisions.md` D-2026-09-25-2.
**Nothing is committed yet** (commit only when the owner asks).

## Built and verified locally
- Per-person accounts from one workbook: `backend/app/people_sheet.py`,
  `GET /api/admin/people/template.xlsx`, `POST /api/admin/people/import` (dry run by default,
  `skip` = unticked changes). UI: Admin → People → Bulk upload (`PeopleUpload.tsx`).
- Clean-up rules: `backend/app/departments.py` (canonical departments, `MM` + number IDs,
  email typos, shared-mailbox detection lives in people_sheet `_mark_duplicates`).
- First sign-in: `backend/app/onboarding.py`, migration `0004_personal_emails`,
  `GET/POST /api/auth/onboard`, `/welcome` page, shell gate on `needs_onboarding`.
- Lowest roles: `ServiceRole.is_default`; Item Code role file gains `public` (view only).
- Mail tiles on Services (`/api/me` → `mail`), new tab (Gmail cannot be framed).
- Shared engine: `roles_io.assign_roles()` used by role files and the sheet.
- `deploy/entrypoint.sh`: MMOS_MIGRATE_ON_BOOT accepts true/1/yes and logs why it skipped.
- Item Code v2 (`cu-itemcode`, branch `mmos-retrofit`, uncommitted): `public` role in
  `core/rbac.py`, Create hidden without `item.create` (`web/app.js`), MASTER.md §6,
  `tests/test_access_public.py`.
- Tests: MM OS backend 207 passed + 2 pre-existing failures; Item Code 176 + 3 new passed;
  `tsc` + `vite build` clean; browser-checked on a local SQLite API with fake people.

## The access sheet for review (personal data, NOT in the repo)
`C:\Users\Anura\Downloads\MM OS access sheet.xlsx`, built by a scratchpad script from the
form responses: 57 people (3 `NA` rows and 1 test row left out, one double submission merged).
Department defaults are proposals in yellow. Review notes in the last column.

## Deploy order (owner)
1. Item Code v2: commit + deploy `mmos-retrofit` with the `public` role FIRST.
2. MM OS: commit + push `deploy-snapshot`, deploy in Coolify. Migration 0004 must run: check
   the boot log for `[boot] alembic upgrade head` or `[boot] skipping migrations: ...`; if it
   skipped, run `python -m alembic upgrade head` in the mmos container terminal.
3. Admin → Roles → Item Code → load the committed role file → dry run → apply (adds `public`;
   existing associates/admin keep their roles; people without an Item Code role get `public`).
4. Admin → Roles → Make default: Service Desk `requester`, Spoke Daily Input `viewer`,
   OCR `viewer` (new databases get these from the seed; the live one needs the clicks).
5. Admin → People → Bulk upload the reviewed sheet → dry run → apply.
