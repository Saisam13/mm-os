# Changelog

Notable changes to MM OS and the services on its control plane. Newest first.

The format is loosely [Keep a Changelog](https://keepachangelog.com/). Engineering decisions
that outlive the change that prompted them are recorded separately, in
[docs/16-decisions.md](docs/16-decisions.md), and linked from the entry that made them.

---

## 2026-09-07 — the sign-in bounce

**Reported:** "Project module is opening and even when I'm trying to log in through the link
from the console it is still going to MM OS home page and we are not able to log in." Then:
"same with service desk."

Two unrelated faults with one symptom. Both are fixed; one needs a DNS change that only the
domain owner can make.

### Fixed

- **Project Module could never complete a handoff.** `GET /_mmos/accept` answered
  `307 -> {os}/launch/purchase`. Its root layout is a server component, so it cannot see the
  request path, and it ran its "no verified user -> redirect to MM OS" guard on the accept
  page too — the one page whose entire job is to *create* the session. The handoff token
  arrives in the URL **fragment**, which a browser never sends to the server, so the layout
  saw an anonymous request and bounced it back; MM OS minted a fresh token; repeat forever.
  The accept page's client JS never ran.
  Middleware — which does know the path, and already held the public allowlist — now marks
  those requests with `x-mmos-public`, and the layout skips its guard on them. The header is
  stripped from every inbound request before being re-set, so it cannot be forged.
  *(`project-purchase-analytics` `105dced`.)* See [D-2026-09-07-1](docs/16-decisions.md).

- **Service Desk's registered URL pointed at nothing.** `base_url` was
  `https://servicedesk.m-mines.com`. That hostname now resolves to a Hostinger shared-hosting
  box (403 over http, TLS handshake failure over https), not the VPS — so every launch URL
  MM OS minted led nowhere. Service Desk's own auth was healthy throughout; a forged token
  returned `bad_signature`, not `unknown_kid`, proving its key set was loaded.
  The seed default is now the Coolify hostname verified to serve the container. It stays an
  env var (`MMOS_SVC_SERVICEDESK_URL`) so it can go back to the pretty domain the day DNS is
  fixed. `ATT_URL`, `OCR_URL` and `PURCHASE_URL` were also switched from `http://` to
  `https://` while they were in hand.

- **Deny-list polling was broken in Project Module.** It fetched `/api/revocations`; MM OS
  mounts that router at `/api/agent`, so the request fell through to the SPA catch-all and
  `res.json()` choked on `index.html`. Nobody could be revoked out of that service.

### Changed — so the next repoint does not do this again

- **`issuer` is now a constant, not `MMOS_URL`.** `iss` is an identity, not an address: MM OS
  stamps `https://os.m-mines.com` whichever hostname you reached it on. Deriving it from the
  URL meant that repointing a service at a new hostname silently invalidated every token, with
  nothing in the logs to say why — a trap sitting directly in the path of the fix for the
  outage above. Changed in both clients (`mmos-client-py`, and Project Module's TypeScript
  equivalent). See [D-2026-09-07-2](docs/16-decisions.md).

- **The session cookie can survive MM OS's iframe.** It was `SameSite=Lax`. MM OS embeds
  services in an iframe on its own origin and points that iframe at
  `/_mmos/accept#token=…`; a Lax cookie is not sent in a cross-site frame at all, so the
  session would be set and then ignored on the very next request — indistinguishable, from
  the user's side, from a broken login. Now `None`+`Secure`. CSRF is unaffected: the mutating
  surface is Next Server Actions (guarded by Next's own Origin/Host check), `/api/cron/*`
  (its own shared token), and MM OS-token-bearing routes. See [D-2026-09-07-4](docs/16-decisions.md).

- **`/_mmos/health` no longer lies.** It reported `ok` straight through the outage, while
  nobody could sign in. It now probes the JWKS endpoint the same way verification does, and
  reports `degraded` with the reason — including the "200 but it's HTML" case a parked host
  or a SPA catch-all produces. `os_url` and `issuer` are echoed so a wrong pointer is
  readable rather than inferred; the service key never is.

### Added

- **`GET /api/admin/services/reachability`** — asks every registered `base_url` the question
  a browser following a launch link would ask, and names what it finds: dead host, parked
  host answering 200 with HTML, crossed registry rows (the URL serves a *different* slug), or
  a service that is up but cannot itself reach MM OS. This is the check that would have
  caught the outage in minutes instead of days. See [D-2026-09-07-3](docs/16-decisions.md).

- **`scripts/repoint_services.py`** — reports, and with `--apply` corrects, stale `base_url`
  rows. `seed_services()` is create-only by design, so a URL that has gone stale in the live
  database cannot be fixed by redeploying; this is the tool for it. It refuses to repoint a
  service at a URL that is not itself reachable.

### Still open — needs the domain owner

- **The per-service A records are gone; a wildcard is absorbing them.** Every
  `*.m-mines.com` name resolves to `72.62.225.9`, a Hostinger shared-hosting box — including
  `random-nonexistent-xyz.m-mines.com`, which is what proves it. A wildcard `*` A record (the
  kind hPanel creates automatically when a domain is attached to a shared-hosting plan) is
  answering for every subdomain, because the specific records that used to point
  `os`, `servicedesk`, `desk`, `itemcode`, `att`, `twenty`, `crm` and `passwordmanager` at the
  VPS no longer exist. The VPS is `200.234.36.153` and is healthy. Checked against 8.8.8.8, so
  this is the authoritative zone (GoDaddy nameservers), not a local cache.

  **The fix is to re-create the specific A records**, one per subdomain, at
  `200.234.36.153` — a specific record wins over a wildcard, so the wildcard itself can stay
  and the shared-hosting site is unaffected. Deleting the wildcard alone would not help.
  Then re-add each domain in Coolify so it re-issues certificates (https currently fails the
  TLS handshake outright, since the shared box holds no certificate for these names).
  `GET /api/admin/services/reachability` will confirm when it has taken. Until then
  everything runs on Coolify's `*.sslip.io` hostnames.
