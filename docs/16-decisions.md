# 16 · Engineering decisions

Decisions that outlive the change that prompted them: the ones a future reader would
otherwise undo, because the code looks arbitrary without the reason.

Each entry is dated and numbered. [CHANGELOG.md](../CHANGELOG.md) says *what changed*; this
says *why it will stay that way*. A decision is only recorded here if reversing it would
break something non-obvious — routine choices belong in code comments.

---

## D-2026-09-08-1 · A handoff service is signed in top-level, not framed

**Context.** The workspace shell had drifted so that only `embed`-mode services were minted a
token; `handoff` services were launched like `external` ones, at their bare `base_url`, with
no token. That silently broke sign-in for every standalone MM OS service (`purchase`,
`servicedesk`) — the service bounced the tokenless request back to the MM OS shell.

**Decision.** Every non-`external` service is minted a token. A framable one (`embed`) is
signed in inside the iframe as before; a `handoff` one opens the authenticated
`/_mmos/accept#token=…` URL in a **new top-level tab**.

**Why top-level and not just make everything `embed`.** The accept page sets the service's
session cookie. In an iframe the service is a third party to the MM OS top frame, so that
cookie is a third-party cookie — `SameSite=None; Secure` is necessary (see D-2026-09-07-4)
but not sufficient, because current browsers block third-party cookies outright by default.
A handoff opened top-level is first-party: the cookie is set unconditionally, in every
browser. So `embed` is the right default only for services that genuinely need to live inside
the MM OS chrome and are known to work with partitioned/allowed cookies; `handoff` is the
robust choice for everything else, and is now a real, working path rather than a dead one.

**Consequences.**
- Switching a service between `embed` and `handoff` is a real product choice with a cookie
  trade-off behind it, not a cosmetic one. Embed = inside the chrome, fragile cookie; handoff
  = new tab, reliable cookie.
- The launch URL still comes from the registry `base_url`, so a correct `base_url` in the
  live database remains a precondition — this fix does not remove the need to repoint stale
  rows (D-2026-09-07-3 and `scripts/repoint_services.py`).

---

## D-2026-09-07-1 · A server component must not guard the page that creates the session

**Context.** Project Module is Next.js App Router. Its root layout is an async server
component that verified the MM OS session and redirected anonymous visitors to
`{os}/launch/{slug}`. That is the right guard for every page but one.

MM OS hands off in the URL **fragment** — `{base_url}/_mmos/accept#token=…` — deliberately, so
the token never reaches a server log or a `Referer` header. A fragment is client-side only.
The server rendering `/_mmos/accept` therefore sees an ordinary anonymous request, and the
layout redirected it to MM OS, which minted a fresh token and sent it back. An infinite
bounce, and the accept page's client JS never ran.

**Decision.** The auth guard lives where the request path is known. `middleware.ts` already
holds the public allowlist and already sees the path, so it marks allowlisted requests with
`x-mmos-public` and the root layout skips its guard when it sees that header. The header is
deleted from every inbound request before middleware re-sets it, so a caller cannot forge it.

**Consequences.**
- Adding a public path means editing `PUBLIC_PATHS` in `middleware.ts` — one list, not two.
- The layout's guard stays a real guard: it still runs on everything else, including any
  route someone forgets to think about. The allowlist still fails closed.
- A route group (`app/(guarded)/…`) would also have worked and is arguably tidier, but it
  means moving every page in the app. Rejected as disproportionate to the fix.

**Alternative rejected.** Passing the token in a query string instead of a fragment. That
puts a live credential into server logs, proxy logs and `Referer` headers on every outbound
link — the exact thing the fragment design exists to prevent.

---

## D-2026-09-07-2 · `iss` is an identity, not an address

**Context.** Both MM OS clients defaulted `issuer` to `os_url` — verify tokens as if issued
by whatever hostname we happen to reach MM OS on. MM OS actually signs a fixed string
(`backend/app/config.py`), regardless of the hostname a caller used.

The two agree only while the URL never changes. The day a service is repointed — a DNS move,
a Coolify `sslip.io` fallback, a staging host — every token starts failing on issuer, with no
log line naming the cause. That trap sat directly across the path of the fix for the 7 Sep
outage: repointing services at working hostnames would have broken them a second time, in a
new and less obvious way.

**Decision.** `issuer` defaults to the constant `https://os.m-mines.com` in both clients,
overridable with `MMOS_ISSUER`. Changing where MM OS *is* no longer changes who MM OS *is*.

**Consequences.**
- `MMOS_URL` and `MMOS_ISSUER` are independent. A service can be repointed freely.
- If MM OS's own `issuer` setting is ever changed, every service needs `MMOS_ISSUER` set to
  match. That is a deliberate, loud coupling — an identity change *should* be a coordinated
  one — rather than a silent one that follows a URL.
- Service Desk already pinned `mmos_issuer` (`servicedesk/app/config.py`) and was never
  exposed. That was correct; it is now the default everywhere.

---

## D-2026-09-07-3 · The registry must prove its pointers, not just hold them

**Context.** Every launch URL MM OS mints is `{base_url}/_mmos/accept#token=…`, read straight
from the service registry. Nothing ever checked that a `base_url` still led to the service it
named. When the m-mines.com subdomains stopped resolving to the VPS, the registry held
perfectly well-formed https URLs, each service was healthy on its own hostname, and the only
symptom was users bouncing back to the MM OS home page. The first detection was a person
reporting they could not log in, days later.

**Decision.** `GET /api/admin/services/reachability` asks each registered `base_url` the
question a browser following a launch link would ask, and distinguishes the failure modes
that matter, because they have different fixes:

| What it finds | What is actually wrong |
| --- | --- |
| connection error | the hostname does not lead to the VPS (DNS, proxy, container down) |
| 200 with HTML | a parked host or a SPA catch-all is answering — a broken pointer |
| 200, JSON, wrong `slug` | two registry rows are crossed |
| 200, JSON, `os.reachable: false` | the service is up but *its* pointer at MM OS is wrong |
| 200, JSON, right slug | a handoff will actually work |

Paired with `/_mmos/health` on the service side, which now reports `degraded` rather than
`ok` when it cannot reach MM OS — a health check that ignores its control plane reports
healthy throughout an outage, which is the failure mode that let this run for days.

**Consequences.**
- One admin call answers "can anybody actually open anything?".
- It is a live probe, so it costs a round trip per service and can be slow when a host is
  black-holing packets. It is admin-only and not on any hot path; the timeout is 8s and the
  probes run concurrently.
- `external` services (ERPNext, Twenty) run their own sessions and expose no `/_mmos/health`,
  so they are checked for liveness only. That is the most that can honestly be checked.
- Not yet wired into the admin UI or an alert. The endpoint is the durable part; surfacing it
  on the Services page is tracked in the punch-list.

---

## D-2026-09-07-4 · A framed session cookie must be `SameSite=None`

**Context.** MM OS renders embeddable services in an iframe on its own origin and points that
iframe at the service's `/_mmos/accept#token=…`. The session cookie both clients set was
`SameSite=Lax`, which browsers do not send in a cross-site frame at all. The cookie would be
set by the accept page and then ignored on the very next request — the frame bounces back to
MM OS, looking exactly like a broken login.

**Decision.** `SameSite=None; Secure` on the service session cookie. `None` requires
`Secure`, which is correct anyway: these tokens must not travel over http.

**Consequences.**
- Embedding works. `launch_mode: embed` is a real option rather than one that silently fails.
- `SameSite` is no longer doing any CSRF work, so the protection has to be real elsewhere,
  and is: Next Server Actions carry Next's own Origin/Host check; `/api/cron/*` carries its
  own shared token; MM OS API routes require a Bearer token, not a cookie. Any *new* mutating
  route that authenticates by cookie alone must add an explicit origin check — this is the
  thing to remember from this entry.
- Services are unreachable over plain http once this lands, since the cookie will not be set.
  That was already true in production and is intended.
