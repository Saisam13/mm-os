# MM OS — shell frontend

React 18 + TypeScript + Vite + React Router 6. Plain CSS with custom properties
(`src/styles/tokens.css`, lifted from `demo/console-directions.html`). No UI kit, no state
library — `fetch` and React context.

## Run it

```
npm install
cp .env.example .env.local     # then edit as below
npm run dev                    # http://localhost:5173
```

`npm run build` emits `frontend/dist`, which `backend/app/main.py` serves at `/` (one
container, one port). `npx tsc --noEmit` type-checks without emitting.

## Pointing at an API

Controlled by `.env.local` (gitignored; see `.env.example`):

- `VITE_USE_MOCK=true` — serves fixture data from `src/api/mock.ts` instead of calling a
  server. This is the default for local frontend work while the backend is still being
  built. The mock is dev-only: `src/api/index.ts` only reaches it when
  `import.meta.env.DEV` is true, so it's dead-code-eliminated out of `npm run build`.
  Three personas, switchable with a query param (persisted in `localStorage` so it
  survives navigation): `?as=prashanth` (default — signed in, 2 grants, not admin),
  `?as=empty` (signed in, 0 grants — the empty-state path), `?as=admin` (platform admin,
  every admin screen reachable).
- `VITE_USE_MOCK=false` (or unset) — calls a real backend. Leave `VITE_API_BASE` blank to
  call same-origin `/api` (the Vite dev server proxies `/api` to `http://localhost:8000`,
  see `vite.config.ts`), or set it to point at a different host.

## Where the tokens live

MM OS never stores a long-lived credential in the browser beyond the session. The
`mmos_session` cookie is `HttpOnly`, set by the backend on `/api/auth/*`, and sent
automatically (`credentials: 'include'` in `src/api/client.ts`) — the frontend never reads
or writes it directly. A **service token** (minted by `POST /api/token/service` when a
tile is clicked) is short-lived (15 minutes), travels only in the URL **fragment** on the
way to the target service, and is never persisted by this app — `useLaunchService.ts`
mints it and immediately hands the browser off via `window.location.href`. Nothing token-
shaped is written to `localStorage`; the only `localStorage` keys this app uses are the
dev-mock persona switch above, which does not exist in a production build.

## Layout

```
src/api/           types, the MmosApi interface, the real client, the dev mock, the switch
src/auth/          AuthContext — fetches /api/me once, holds it, a 401 anywhere clears it
src/routes/        ProtectedLayout / AdminGuard route guards
src/components/    TopNav, CommandPalette, ServiceMark, Panel (drawer), dialogs, EmptyState
src/pages/         EntryPage, ServicesPage, ProfilePage, pages/admin/* (People, Access,
                   Services registry, LLM, Audit)
src/styles/        tokens.css (brand custom properties), base.css, components.css
src/lib/           initials, formatting, service-kind inference, the launch-service hook
```

Only direction B (top nav, calm) from `demo/console-directions.html` is built — see
`brand/UI-DECISIONS.md` § Console direction. There is no left rail and no command-first
landing; the command palette is reachable from the Search button and Ctrl/Cmd-K.
