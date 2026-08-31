# C4 — Workspace design language (SHELL)

Adopts the fork's workspace *expression* (services sidebar, calm main area, rounded
cards, soft shadows, generous spacing, subtle transitions) as the MM OS product design
language — recolored to the MiniMines brand. **Petrol `#005D7F` is the accent, not the
fork's sky-blue.** Roboto / Roboto Condensed kept. `brand/BRAND.md` and
`brand/UI-DECISIONS.md` honored (petrol primary, cool blue-tinted neutrals, orange
reserved for action, labels-and-data copy only). Shell only — admin pages get restyled
in a following pass, so the token/system additions are clean and reusable.

## Design tokens introduced (`styles/tokens.css`)
Additive — nothing existing was renamed or removed, so the admin pass keeps its classes.
- **Soft shadow scale:** `--shadow-sm`, `--shadow` (existing), `--shadow-md`, `--shadow-lg`
  — cool-slate tinted (navy rgba); redefined darker under both dark-mode blocks.
- **Radius scale:** `--r-sm` `--r` (existing) + `--r-md` (10), `--r-lg` (14), `--r-xl` (20),
  `--r-2xl` (26) for controls → cards → hero panels.
- **Motion:** `--ease` (cubic-bezier .4,0,.2,1), `--dur` (.18s), `--dur-slow` (.3s).

## Component classes introduced (`styles/components.css`)
Real classes, no inline-style soup (the fork abused inline styles). `.ws` layout,
`.ws-side`(+`.collapsed`), `.ws-side-hd`, `.ws-list`, `.ws-svc`(+`.active`), `.ws-main`,
`.ws-reveal`, `.ws-appbar`, `.ws-frame`, `.ws-embed`(+`.max`), `.ws-center`, `.ws-empty`,
`.ws-launch`, `.btn-icon`, `.btn-launch` (dark-mode petrol text handled like `.btn-p`).
Entry refresh: `.entry-hero`, `.entry-panel`, `.entry-brand`, `.entry-choice`,
`.choice-btn`, `.entry-back`, `.entry-title`. Light/dark preserved via the token system.

## Dashboard `/dashboard` (new — `pages/Dashboard.tsx`)
Workspace: left **sidebar** of the user's services (ServiceMark + name + role), main area,
**sidebar collapse** toggle (+ reveal button), **full-screen** toggle for the active app.
Selection driven by `?app=<slug>`.
- **Embed gating preserved (not regressed):** uses `canEmbed()` from
  `lib/useLaunchService.ts` unchanged — `launch_mode === 'embed'` **and** the http-from-https
  mixed-content guard. Embeddable → iframe; **not** embeddable → a clean "opens in its own
  window" launch panel with a Launch button (new tab), never a blank frame. Empty state when
  no app is selected / no services.
- **Iframe security:** same configuration as `ServiceOpenPage.tsx` — **no `sandbox`
  attribute** (internal, backend-vetted `embed` targets on a VPN-only deployment). The fork's
  looser `sandbox="allow-scripts allow-same-origin ..."` is deliberately **not** adopted.

## Structure — both surfaces kept
- **Dashboard** embeds frameable services in place.
- **Services page** (`pages/ServicesPage.tsx`) restyled; every launch now opens a **new tab**
  (`launch(s, { newTab: true })`) — the deliberate contrast with the Dashboard.

## Files changed
- `styles/tokens.css`, `styles/components.css` — design system.
- `pages/Dashboard.tsx` — **new** workspace page.
- `pages/EntryPage.tsx` — restyled to the branded workspace look; PIN + Google behavior
  unchanged (User/Admin choice still only steers redirect + Google `next`). Font-Awesome
  `<i>` icons (never actually loaded) replaced with inline SVGs.
- `pages/ServicesPage.tsx` — new-tab launch; chip simplified to "New tab".
- `App.tsx` — `/dashboard` route added.
- `routes/Guards.tsx` — non-admin default redirect → `/dashboard`.
- `components/TopNav.tsx` — **Dashboard** + **Services** nav items; logo → `/dashboard`;
  palette gains a Dashboard entry and routes service picks to `/dashboard?app=<slug>`.
  Service Desk quick-launch + admin entries unchanged.
- `lib/useLaunchService.ts` — added optional `{ newTab }` to `launch()`; default behavior
  intact. `canEmbed`, `TOKEN_HANDOFF_ENABLED` untouched.
- `api/mock.ts` — **dev fixture only:** Item Code Studio `launch_mode` `handoff` → `embed`
  so the embed path is exercisable in the mock (no real backend/contract change).
- `ServiceOpenPage.tsx` — untouched, route kept working.

## Verification
- `npx tsc --noEmit` → exit 0 (`TSC_EXIT_0_OK`).
- `npm run build` → success (`tsc -b && vite build`, ✓ 66 modules, built in 660ms).
- Dev server with `VITE_USE_MOCK=true`, admin persona (`?as=admin`), verified in-browser
  (DOM/console; the pane could not composite for pixel screenshots):
  - Dashboard renders with sidebar (ERPNext, ICS, ATT, Service Desk, Twenty) + app bar.
  - Embeddable service (Item Code Studio) embeds: `iframe.ws-frame`, `src=itemcode…`,
    `sandbox=NONE`.
  - Non-embeddable (ERPNext) shows the launch panel with a `target=_blank` Launch button,
    no iframe.
  - Sidebar collapse + reveal and full-screen enter/exit toggle their state classes.
  - Empty state ("No app open") when no app selected.
  - Services page: both a third-party (ERPNext) and an embeddable (Item Code Studio) row
    open a new tab via `window.open(_blank, noopener,noreferrer)` — no in-app navigation.
  - Login page renders the logo lockup + User/Admin choice; step two shows Google
    (`next=/dashboard`), employee-code + password PIN, Sign in, Back.
  - No shell console errors.
- `frontend/.env.local` removed; dev server stopped.
