# Handoff: bulk people + access upload, department-based roles, Google sign-in

Paste everything below the line into a new Claude Code session opened in
`C:\Users\Anura\OneDrive\Desktop\MM OS`. Written 25 Sep 2026.

---

You are picking up MM OS, the MiniMines company portal (single sign-on + service registry +
per-service roles). **Start by planning, not coding.** Read the files listed under "Read first",
then come back to me with a short plan and 2–3 options for each open decision, with your
recommendation. Build only after I pick.

## What I want

1. **One spreadsheet to bulk-upload people with their access.** Each row is a person: name,
   employee ID, department, designation, official email, personal email, and a role per
   service (e.g. Item Code Studio = manager, Service Desk = requester). Give me the template
   (.xlsx, with an instructions tab and dropdowns for department and role) and an upload in
   the MM OS admin UI that shows a dry-run preview before writing anything.
2. **Department-based defaults.** A mapping "department → default role per service", so a
   row that leaves a service blank gets its department's default. It should live in the same
   workbook (a second tab) or in MM OS's existing role files; recommend which.
3. **Google sign-in assigns access by person and department.** When someone opens the link
   and signs in with Google, MM OS matches their Google email (official *or* personal) to
   their row, and they land with exactly the access the sheet gave them.
4. **Unconfigured people get viewer-level access.** Someone who signs in but is not in the
   sheet, or whose department has no mapping, gets the lowest "view only" role, never nothing
   and never more. Careful: Item Code Studio v2 has **no view-only role** (see below), so you
   must propose how "viewer" works there.

## The data I will give you

`C:\Users\Anura\Downloads\Employee Details - MM (Responses).xlsx`, one sheet
`Form responses 1`, 62 rows. Columns: Timestamp, Employee Name, Employee ID, Department,
Designation, Official Email ID, Personal Email ID, Official Contact Number, Personal Contact
Number, Email address. **It contains personal data: read it in place, never copy names,
emails or phone numbers into the repo or git** (`data/` is not gitignored for .xlsx). Phone
numbers are not needed at all.

Known mess, measured already (aggregates only):
- Department has ~39 spellings for ~15 real departments (P-hub / P-HUB / Phub; Stores / STORE
  / Store; Finance / FINANCE / Finance Operations; HR / Human Resource; R&D / Research and
  Development; BD variants; "HR & Stores" is two departments). Propose a canonical list plus an
  alias map, and show me the mapping before using it.
- Official email: 56 `m-mines.com`, 4 `gmail.com`, 1 typo `mimines.com`, 1 blank.
- Personal email typos: `gamail.com`, `gmail .com`, `gmail com`, `m.com`.
- 3 duplicate Employee IDs. Report them; don't guess which row wins.
- The dry run must list every row it would reject or "fix" and why.

## Current state (verified 25 Sep 2026)

- Live MM OS: `https://m-mines.in`, deployed from `Saisam13/mm-os` branch `deploy-snapshot`
  via Coolify (`http://200.234.36.153:8000`, project InternalTools → production → mmos).
  Head is `71574aa` (roles work). Migration `0003` is applied.
- **Roles are done:** services have a permission catalog, roles carry permissions, tokens
  carry a `permissions` claim, and role files (`backend/app/role_files/<slug>.json`, format
  documented at the top of `backend/app/roles_io.py`) are imported at Admin → Roles with a
  dry run. The role file's `assign` block already supports rules by `platform_admin`,
  `is_approver`, `band`, `department`, plus named `people` and a `default`. **Reuse this.**
  Don't build a second assignment engine.
- Item Code Studio roles applied live: 23 associate, 1 admin, **0 managers**. Nobody can
  approve in Item Code except that one admin. Fixing this is a quick win from the sheet.
- Item Code Studio **v2** is live at `https://icg.m-mines.in` (repo `codeunderscrap/itemcode`,
  branch `mmos-retrofit`, local clone `C:\Users\Anura\OneDrive\Desktop\cu-itemcode`). It only
  accepts associate / manager / admin (`core/rbac.py`) and **refuses sign-in for any other
  role**, including `viewer`. It decides permissions from the role name in its own table and
  ignores MM OS's `permissions` claim. Associate is its lowest role, and associates can create
  and edit. A local branch `backup/roles-v1-superseded` holds an older, unused attempt; ignore it.
- Existing bulk tools to build on, not duplicate: `POST /api/admin/accounts/bulk`
  (functional mailbox roster, dry run), `scripts/provision_functional.py`,
  `scripts/provision_people.py`, `app/provision.py`, `POST /api/admin/grants/bulk` (by band /
  department), `app/seed.py` (spreadsheet import + department hints).

## Decisions you must surface, not assume

1. **Account model conflict.** On 31 Aug the owner decided MM OS accounts are **functional
   mailboxes** (purchase.c2@, central.stores@, …), not personal names, and said not to create
   records for name-based logins. This sheet is per-person. Ask whether per-person accounts
   are now wanted, or whether rows map onto functional mailboxes.
2. **Google sign-in and personal Gmail.** Current rule: Google login auto-provisions only
   `hd=m-mines.com`; a personal Gmail can only be *linked* to an existing account after a
   PIN sign-in. Matching "official or personal email from the sheet" would let a personal
   Gmail create or claim an account on first login, which changes security. Give options
   (pre-create from sheet and allow listed Gmail addresses only / keep PIN-then-link /
   corporate only) with trade-offs.
3. **"Viewer" for unconfigured people**, per service. Item Code has no view-only role:
   options include adding a `viewer` role to v2 (a code change in the other repo), giving
   unconfigured people no Item Code grant (public decoder page only), or associate. Say what
   each means for someone who isn't configured.
4. **Where the department → role mapping lives:** sheet tab vs role file `assign.rules`
   vs a new admin screen.
5. **Re-upload semantics:** does a later sheet overwrite hand-edited roles, only fill gaps,
   or show a diff to accept per row? (Role files already have `mode: missing|all`.)

## Rules for this work

- Plan first; build after I choose. Dry run before every write, live or local.
- Never put personal data in git. Tests use fake people.
- Tests: `cd backend && .venv/Scripts/python.exe -m pytest tests -q` (SQLite, no Docker or
  Postgres on this machine). Baseline is 146 passed, 2 failing that were already broken
  before this work (stale `att` slug in seed tests).
- Frontend: `npx tsc --noEmit -p .` and `npx vite build` in `frontend/`. `.claude/launch.json`
  has `mmos-frontend-real-api` (real API on :5174). `frontend/.env.local` forces the mock
  otherwise.
- **Deploy gotcha:** migrations did NOT run on boot even though `MMOS_MIGRATE_ON_BOOT`
  exists in Coolify. After any new Alembic migration the owner must run
  `python -m alembic upgrade head` in the mmos container terminal right after deploying, or
  the site 500s (it did on 25 Sep; I rolled back). Opening that terminal is blocked for the
  agent. Either find out why boot migration is skipped (read-only investigation), or hand the
  owner the exact command.
- Claude cannot type passwords, PINs or API keys into fields. The owner does those.
- Commit only when asked; branch `deploy-snapshot` is what production deploys.

## Read first

- `RESUME.md`, `docs/16-decisions.md` (top entry D-2026-09-25-1: roles and role files)
- `backend/app/roles_io.py`, `backend/app/role_files/itemcode.json`
- `backend/app/routers/auth.py` (Google OIDC + PIN), `backend/app/provision.py`,
  `backend/app/routers/people.py` (accounts bulk)
- `frontend/src/pages/admin/RolesPage.tsx`, `AccountsPage.tsx`, `AccessPage.tsx`
- `cu-itemcode/core/rbac.py`, `cu-itemcode/routes/mmos.py`, `cu-itemcode/docs/v2/MASTER.md` §6

Deliver first: the plan, the options for each decision above, the canonical department list
with its alias map (derived from the sheet, no names), and a mock-up of the template columns.
