# A3 · Shell frontend

## Delivered

React 18 + TypeScript + Vite + React Router 6, plain CSS with custom properties, matching
the `ATT_Platform/frontend` house pattern (`react-router-dom@6.30.0`, `vite@5.4.19`,
`typescript@5.8.3`, `@vitejs/plugin-react@4.4.1`). No other dependency.

- **`frontend/package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`** — `vite.config.ts`
  sets `build.target: 'esnext'` (see Assumptions) and proxies `/api` to `localhost:8000` in dev.
- **`frontend/src/styles/tokens.css`** — the demo's `:root` token block lifted verbatim (light
  values, the `prefers-color-scheme: dark` block, and the `[data-theme="dark"]` block), plus
  direction B's density variables folded in as flat values (`--pad`, `--row`, `--fs`, `--gap`,
  `--h1`, `--h2`, `--wide`) since only B is built. No component hardcodes a colour.
- **`frontend/src/styles/base.css`, `components.css`** — direction B only: `.topnav` (60px navy
  sticky bar, flat text items, 3px petrol underline on `.sel`), `.svc` rows, `.card`/`.tabs`/
  table/`.chip`/`.panel` (drawer)/`.ovl`+`.pal` (command palette)/`.matrix` (access grid)/
  `.confirm-scrim`/`.empty`, all ported from `demo/console-directions.html`. `.rail*`, `.cmdtop*`
  and the direction picker were **not** ported — grepped for confirmation, see How to verify.
- **`frontend/src/api/`** — `types.ts` (contract shapes), `contract.ts` (the `MmosApi`
  interface), `client.ts` (real fetch client, `credentials:'include'`), `mock.ts` (dev-only
  fixture, three personas via `?as=prashanth|empty|admin`), `index.ts` (the single dev/prod
  switch: `import.meta.env.DEV && VITE_USE_MOCK==='true'` gates a dynamic `import('./mock')`;
  confirmed absent from the production bundle, see How to verify).
- **`frontend/src/auth/AuthContext.tsx`** — fetches `/api/me` once, holds it in context; any
  401 clears it, which `routes/Guards.tsx` turns into a redirect to `/`.
- **`frontend/src/routes/Guards.tsx`** — `ProtectedLayout` (renders `TopNav` + outlet, redirects
  signed-out visitors to `/`) and `AdminGuard` (redirects a non-admin to `/services`).
- **`frontend/src/components/`** — `TopNav`, `CommandPalette`, `ServiceMark`, `Panel` (drawer),
  `ConfirmDialog`, `ReasonDialog`, `EmptyState`, `Spark` (inline SVG sparkline, no chart dep).
- **`frontend/src/pages/`** — `EntryPage` (Google button, employee-code+PIN form, public
  service directory), `ServicesPage`, `ProfilePage`; **`pages/admin/`** — `AdminTabs`,
  `PeoplePage` (search/filter, edit drawer, PIN issue/reset/clear, deactivate with a dynamic
  grant-count confirmation), `AccessPage` (matrix, per-person drill-down, role meanings inline,
  expiry/history, add-grant and bulk-grant dialogs, and a pending-requests card that states the
  contract gap below rather than fabricating data), `ServicesAdminPage` (registry CRUD, roles,
  rotate-key with a one-time reveal), `LlmPage` (`/ai`, outside the admin tabs — its own top-nav
  destination), `AuditPage`.
- **`frontend/src/lib/`** — `initials.ts` (in-house mark derivation), `format.ts`,
  `serviceKind.ts`, `useLaunchService.ts` (mint-or-redirect + error surface, shared by
  `ServicesPage` and the palette), `a11y.ts` (keyboard activation for clickable table rows).
- **`frontend/public/manifest.webmanifest` + `public/icons/icon.svg`** — PWA install, no
  service worker (no API-response caching, per the brief).
- **`frontend/README.md`**, **`.env.example`**, **`.claude/launch.json`** (a `mmos-frontend`
  dev-server entry, added since none existed).

## Deviations

- **UI-DECISIONS.md's Console direction reserves top-nav space for exactly four destinations**
  (Services, Service Desk, Access, AI services), but the brief's Admin section asks for five
  screens (People, Access, Services registry, LLM, Audit). People, the service registry and
  Audit have no designed chrome of their own, so they're grouped as tabs under **Access**
  (`AdminTabs.tsx`), reusing the site's own tab idiom from Service Desk's four views rather
  than inventing new chrome. **AI services** stays the standalone 4th nav destination exactly
  as locked, since it maps 1:1 to the approved-as-designed LLM page.
- **"Service Desk" is a launch shortcut, not a page.** The brief's own Deliverables list for
  A3 has no Service Desk views (My requests / department queue / IT console / approvals) —
  those are A5's `servicedesk/**`. The top-nav "Service Desk" item mints a token and navigates
  there exactly like a Services-page row, with the open-count badge from `/api/me`'s
  `badges.servicedesk_open`. It's hidden entirely if the signed-in user has no `desk` grant.
- **In-house vs. third-party is inferred, not given.** Neither `/api/public/services` nor the
  per-item shape in `/api/me` carries an explicit flag. `session_owner` (public endpoint) and
  `launch_mode` (`/api/me`, matching `Service.launch_mode`'s check constraint in
  `backend/app/models.py`: `handoff|embed|external`) are used: `external`/`service` = third-party
  (colour+initial fallback tile, own sign-in), everything else = in-house (Roboto Condensed
  initials on petrol). See `src/lib/serviceKind.ts`.
- Token/number formatting uses a compact "4.1 M" style for large token counts (matching the
  demo) and plain comma-grouped counts for requests — not literally in either doc, just visual
  parity with `demo/console-directions.html`.

## Contract objections

1. **The public services endpoint the brief told me to flag is still missing.**
   `docs/03-api-contract.md` documents `GET /api/public/services` (names + launch URLs only,
   no session), but it is wired nowhere: not in frozen `backend/app/main.py`'s router list, and
   not implemented in `me.py`, `people.py`, `auth.py`, or `platform.py` as they stand now. The
   entry page (`EntryPage.tsx`) calls it and shows a plain empty/error state if it 404s; nothing
   is fabricated. Whoever ends up owning it should mount it under a prefix `main.py` already
   wires (`me.router` is at `/api`, so `@router.get("/public/services")` there would resolve
   correctly) — I can't add it myself since `main.py`/router ownership are outside `frontend/**`.

2. **Every real error arrives as `{"detail": {...}}`, not the flat shape docs/03 documents** —
   confirmed directly in `backend/app/deps.py` (frozen) and independently flagged in
   `handoff/a2-tokens.md`'s own Contract objections. I did not touch `deps.py` or `main.py`.
   As a frontend-side mitigation (not a backend fix), `src/api/client.ts`'s error parsing now
   unwraps `body.detail` when present before constructing `ApiRequestError`, so the real client
   works correctly whether or not B1 has added the app-wide flattening handler yet.

3. **A2's now-implemented `backend/app/routers/platform.py` and A1's `people.py` return shapes
   that diverge from `docs/03-api-contract.md` in several concrete ways I had no way to see
   while building against the frozen doc** (my brief: "develop against a mock returning the
   exact payloads from docs/03-api-contract.md" — I did; A2/A1 wrote the real routers in
   parallel and reading their code now shows drift docs/03 doesn't warn about):
   - `GET /api/admin/services` returns `{"services": [...]}`, not a bare array, and each
     `roles[]` entry is `{key, name, is_default}` — **no `description`** (`platform.py`
     `_service_out`, line ~99-116). This breaks "role meanings shown inline" (a locked
     UI-DECISIONS.md requirement) once wired to the real API: `ServiceRole.description` exists
     in `models.py` but is never serialized out.
   - `GET /api/admin/grants` returns `{"grants": [...]}` of **flat** objects —
     `{id, user_id, service_slug, role, reason, expires_at, created_at}` (`_grant_out`,
     line ~120-129) — with **no `granted_by`, no nested `user`/`service`/`role` names**. The
     per-person drill-down's "who granted it" (also locked in UI-DECISIONS.md) has no data
     source as currently shaped; names/roles would need a client-side join against
     `/api/admin/employees` + `/api/admin/services`, which is possible but not what I built
     against.
   - `GET /api/admin/employees` and `GET /api/admin/users` are **two separate collections**
     (`people.py` `_employee_out` / `_user_out`), not one joined row. `_user_out` does carry
     `employee_code`/`full_name` denormalized, which makes a client-side join workable.
   - `GET /api/admin/llm` returns `{"registrations": [...]}` with `slug` but no `name`, and a
     `usage` field (not `usage_30d`) of `{day, requests, input_tokens, output_tokens}`.
   - `POST /api/admin/grants/bulk` returns `{"created": N, "skipped": N}`, not `{"count": N}`.
   - `DELETE /api/admin/grants/{id}` returns `{"ok": true}`.

   I did **not** rewrite `src/api/client.ts`/`types.ts`/`mock.ts` to match these once I found
   them late in verification — the coordinator's instruction at this point was "verification
   and handoff, not new features," and reconciling a frozen-doc vs. sibling-router drift I
   didn't cause is squarely B1's integration job per `docs/09-build-agents.md` ("I reconcile
   objections between runs"). My code is internally consistent and fully verified against
   `docs/03-api-contract.md` as written; it will need a follow-up pass against whichever shape
   wins once reconciled. I did not touch `platform.py` or `people.py` (not mine to edit).

4. **No endpoint anywhere for Service Desk's pending access requests.** UI-DECISIONS.md's
   Access page requires them "fed from Service Desk, decided in place"; `AccessPage.tsx` renders
   the card with an honest empty state naming this gap rather than inventing data.

5. **No endpoint for a user's own session list or a true sign-out-everywhere.**
   `POST /api/auth/logout` (confirmed in `routers/auth.py` via `handoff/a1-identity.md`) revokes
   only the calling session. `ProfilePage.tsx`'s "Sign out everywhere" is honestly labelled as
   ending the current session, with a plain note that per-session detail isn't exposed.

6. `GET /api/admin/audit` (confirmed in `platform.py`) filters only by `actor`/`action`/
   `from`/`to` — no `target_id`. `AccessPage.tsx`'s per-person History section fetches a page
   and filters by `target_id` client-side; this is a read-only convenience filter, not the
   "never filter client-side" rule (which is specifically about `/api/me`'s access-control list).

## Assumptions

- **Admin nav placement** (People/Services-registry/Audit as tabs under "Access"; LLM as the
  standalone "AI services" destination) — see Deviations. A human should confirm this is what
  was meant, since UI-DECISIONS.md doesn't say it outright.
- **`launch_mode`/`session_owner` → in-house vs. third-party** inference (see Deviations) —
  reasonable given `models.py`'s check constraint, but never stated as such in any doc.
- Third-party fallback tile colours (`erpnext` `#2490EF`, `twenty` `#1A1A1A`) are hardcoded in
  `ServiceMark.tsx` since no field in either API shape carries a brand colour; unknown
  third-party slugs fall back to a neutral tile so a new one is never markless.
- `ServiceMark` looks for `/service-marks/{slug}.svg` in the app's own `public/` (not
  `brand/service-marks/`, which is outside `frontend/**` and currently empty anyway) and falls
  back on a 404 — whoever adds real marks should drop SVGs into `frontend/public/service-marks/`.
- Mock personas (`?as=prashanth|empty|admin`, persisted in `localStorage`) are a build/test aid
  only, dead-code-eliminated from production along with the rest of `mock.ts`.
- "Bulk grant by band" doesn't collect a `reason` in the dialog even though `GrantBulk.reason`
  is accepted server-side (optional) — a minor omission, not a break.
- The People drawer's PIN control always requires the admin to type a PIN; `people.py`'s real
  `POST /users/{id}/pin` also supports omitting `pin` to have the server generate and return
  one, which the UI doesn't expose. Worth adding, not done now.

## Not done

- **No live Google sign-in could be exercised — no OIDC credentials exist yet** (sprint rule).
  The button is wired to `GET /api/auth/google/start?next=/services` per docs/03 and confirmed
  against A1's actual `routers/auth.py`; the callback round-trip is untested end-to-end.
  Employee-code + PIN sign-in, its error paths (locked/unknown/wrong-PIN), and the resulting
  `/services` render were exercised against the mock and behave correctly (see How to verify).
- No run against a live backend at all, per the sprint rules (no Docker/Postgres expected this
  run). Everything was verified against `src/api/mock.ts` plus static review of A1's/A2's actual
  router code (see Contract objections #3 for what that review found).
- Reconciling `src/api/client.ts`/`types.ts`/`mock.ts` against A1's/A2's real response shapes
  (Contract objections #3) — deliberately left for the integration pass.
- Pending access requests and per-grant "granted by" — UI exists, data does not (Contract
  objections #4 and #3).
- Real per-service brand SVGs — `brand/service-marks/` is empty; fallback tiles carry the load.

## How to verify

```
cd frontend
npm install
npx tsc --noEmit                 # exits 0, clean
npm run build                    # emits frontend/dist (index.html, ~16KB CSS, ~215KB JS)
grep -c "DEV-ONLY FIXTURE" dist/assets/*.js     # 0 — mock is not in the production bundle
grep -c "mmos_mock_persona" dist/assets/*.js    # 0
grep -rn "className=\"rail\|rail-i\|cmdtop\|data-dir" src/   # no matches — only direction B exists
```

`backend/app/main.py` (frozen) mounts `StaticFiles` at `Path(__file__).resolve().parents[2] /
"frontend" / "dist"`, i.e. `<repo>/frontend/dist` — exactly `npm run build`'s `outDir`.

Manual pass, `npm run dev` with `frontend/.env.local` → `VITE_USE_MOCK=true` (`.env.example`
has the flag), verified via the Browser pane against `http://localhost:5173`:

- `/?as=prashanth` (default) → signs in as a 2-grant, non-admin user → `/services` renders
  **exactly two rows** (ERPNext/user, Item Code Studio/viewer) — the literal acceptance line.
- `/?as=empty` → `/services` renders the empty state ("No services yet — raise a request and
  IT will set you up."), no broken page.
- `/?as=admin` → all four top-nav destinations appear, `/admin/access`'s matrix and per-person
  drill-down render (grants, granted-by, expiry, role-meaning `<details>`, audit-derived
  history), `/ai` renders the LLM table with the unreported row muted and a working toggle +
  reason prompt, the command palette opens from both the Search button and Ctrl/Cmd-K and lists
  admin-only entries only for this persona.
- Visiting `/admin/access` or `/ai` directly as the non-admin persona redirects to `/services`
  (admin screens are unreachable, not just hidden).
- Entry-page PIN sign-in: `MM19`/`0000` shows "That PIN is not correct." in place; `MM19`/`1234`
  signs in and lands on `/services`.
- Light vs. dark: `resize_window(colorScheme:'dark')` then reading `getComputedStyle` on
  `:root` shows the token set flip to `--ground:#061A22 --petrol:#4FB8D6 --navy:#03121C
  --orange:#FF8B3D`; `colorScheme:'light'` flips back to `#F0F4FA/#005D7F/#002060/#FF6A00` —
  both follow the machine setting via `prefers-color-scheme`, no manual toggle exists.
- Copy check: `grep -rniE "good (morning|afternoon|evening)|welcome|anything missing|is a
  request away|all (services )?healthy|open to you" src/` — no matches anywhere in the shell.
- Orange usage check: `grep -rn "orange" src/styles/components.css src/components src/pages` —
  every hit is an action/attention surface (`.btn-act`, `.chip.or`, `.step.now`, the sparkline's
  sharp-rise colour, the Service Desk open-count badge, `.btn-danger`) — never decorative.
