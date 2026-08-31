# C5 — Admin restyle (Pass 2)

Pass 2 of the workspace redesign. The admin area now reads as one system with the
shell (C4). No new palette, no inline-style soup — the restyle was delivered by
**evolving the shared, token-based component classes** the admin pages already
consume toward the workspace expression (soft shadows, larger radii, motion).
This keeps every admin page and the shell in lockstep from one place.

## Approach
The admin pages (`AdminTabs`, `PeoplePage`, `AccessPage`, `AccountsPage`,
`AuditPage`, `LlmPage`, `ServicesAdminPage`) and `ProfilePage` already used the
`.card` / `.btn-q` / `.btn-act` / `.field` / `.chip` / `table` / `.tabs` / `.panel`
/ `.confirm-box` system. Rather than reinvent per page, the shared classes were
lifted to the C4 language. **No admin TSX was changed** — behavior and markup are
byte-for-byte intact; only their styling moved forward.

## Shared class changes (`styles/components.css`) — affect the shell too
- **`.card`** — radius `--r` → `--r-lg` (14px), added `box-shadow: var(--shadow-sm)`
  and `overflow: hidden` so it lifts off `--ground` and clips edge-to-edge
  tables/iframes to the radius. *Shell impact:* also used by `ServicesPage`,
  `ProfilePage`, `EntryPage`, `ServiceOpenPage` (the iframe card now has rounded,
  clipped corners + a soft lift — improvement, not a regression).
- **`.tabs` / `.tab`** — flat underline → **segmented control**: pill container on
  `--surface-2` at `--r-lg`, selected tab is a raised `--surface` pill
  (`--shadow-sm`) at `--r-md`, with motion transitions. *Only `AdminTabs` uses
  these classes* (verified — other "tab" hits are the "New tab" label), so no
  shell surface changes.
- **`.confirm-box` / `.confirm-scrim`** — radius `--r-lg`, `box-shadow: --shadow-lg`,
  plus a soft `pop-in` / `scrim-in` entrance. Used by `ConfirmDialog`,
  `ReasonDialog`, and the Accounts add / bulk-import dialogs.
- **`.panel`** (drawer) — `--shadow` → `--shadow-lg`; transition now uses the motion
  tokens (`transform var(--dur-slow) var(--ease)`). Used by People / Access /
  Accounts / Services drawers.
- **Controls** — `.btn-act`, `.btn-q`, and `.field input/select/textarea` gained
  `--dur`/`--ease` transitions so hover/focus feels like the workspace.

## `styles/base.css`
- Reduced-motion guard extended to also kill `animation` (covers the new
  dialog entrance keyframes).

## Verification
- `npx tsc --noEmit` → `TSC_EXIT_0_OK` (exit 0).
- `npm run build` → `tsc -b && vite build`, `✓ 66 modules transformed`,
  `✓ built in 779ms`.
- Dev server with `VITE_USE_MOCK=true`, admin persona
  (`localStorage mmos_mock_persona=admin`), driven via DOM (pane can't composite
  pixels — verified through computed styles + DOM):
  - `/admin/accounts` — card `border-radius 14px` + `box-shadow` + `overflow hidden`;
    tab bar `inline-flex` segmented, selected pill on `--surface` with shadow.
    **Add account** dialog opens (radius 14, shadow-lg, all 6 fields). **Bulk
    import** opens; typed a 2-row roster → "2 rows parsed" → **Preview** → dry-run
    card (radius 14) with 2 rows + "Confirm & apply" (preview→commit intact).
    **Customize drawer** opens (shadow-lg, `transform .3s cubic-bezier` motion) with
    approval / head / PIN / deactivate controls.
  - `/admin/people` (8 rows, 3 filters), `/admin/access` (2 cards, 8-row matrix +
    role chips), `/admin/audit` (4 rows), `/admin/services` (6 rows, Register
    button), `/ai` (4 rows, On/Off toggles), `/profile` (3 cards, kv list,
    sign-out-everywhere) — all render in the new style, card radius 14.
  - No console errors across the sweep.
- `frontend/.env.local` removed; dev server stopped.

## Re-check for the shell owner
Because the restyle is in shared classes, re-glance the shell surfaces that use
`.card`: `ServicesPage`, `ProfilePage`, `EntryPage`, and especially
`ServiceOpenPage` (its iframe now sits in a rounded, `overflow:hidden` card). The
command palette (`.pal`) and `.ovl` were left untouched.
