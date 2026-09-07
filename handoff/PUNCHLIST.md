# MM OS — live punch-list (owner-reported + found)

Running list of issues/gaps to work through. Newest context at top of each section.

## Handoff services got no token — the real login blocker (8 Sep, fixed)
After the 7 Sep fixes deployed and verified live (accept 200, control plane reachable),
purchase and servicedesk *still* bounced to the MM OS home page. Root cause was in the MM OS
**frontend**, not the services: the workspace only minted a token for `embed`-mode services;
`handoff` mode opened the bare `base_url` with no token, so the service bounced the request
to `{os}/launch/{slug}` = the SPA home page. Fixed in `frontend/src/pages/Dashboard.tsx` —
handoff services now mint a token and open the `/_mmos/accept#token=…` URL in a new top-level
tab (first-party cookie, browser-robust). Typecheck + build clean; verified in the dev mock
that the Launch button href is the minted handoff URL, not base_url.
- [ ] **Redeploy the MM OS frontend** (deploy-snapshot, commit below) — this is the fix.
- [ ] Then fix the live registry (unchanged by any redeploy): run
      `python /app/scripts/repoint_services.py --apply` in the MM OS container so Service
      Desk's `base_url` stops pointing at the dead servicedesk.m-mines.com.
- [ ] Confirm each service's `MMOS_SLUG` env equals its registry slug (`purchase`,
      `servicedesk`); the token `aud` is the registry slug and a mismatch fails verification.
- [ ] Deny-list minor bug: the TS client (project-module) omits `since` on its first
      revocations poll, and MM OS's `/api/agent/revocations` requires it → HTTP 422, so that
      service never syncs revocations. Login-independent; fix by defaulting `since` to epoch.


## BLOCKER — every *.m-mines.com host is off the VPS (7 Sep, verified)
Owner report: "Project module opens but sign-in goes back to the MM OS home page; same with
Service Desk." Two separate causes, both verified over the wire.

**1. DNS.** `os.m-mines.com`, `servicedesk.m-mines.com`, `desk.m-mines.com`,
`itemcode.m-mines.com`, `att.m-mines.com` all resolve (globally — checked via 8.8.8.8, and
the domain is on GoDaddy nameservers) to **72.62.225.9**, a Hostinger *shared-hosting*
LiteSpeed box: `403 Forbidden` over http, TLS handshake failure over https. The VPS is still
**200.234.36.153** and is healthy — every app answers on its Coolify sslip.io URL:
- MM OS — `https://hrxd6lgu3h7qpnkbpy2mqgdc.200.234.36.153.sslip.io` (JWKS serves fine)
- Service Desk — `https://uthjgvwpvx68afqgrz8gf9rh.200.234.36.153.sslip.io` (`_mmos/health` ok)
- Sales Hub — `https://llv4ukunkpxp6zhwsqwnyevr.200.234.36.153.sslip.io`
- Project Module — `https://mdqtimbvyv6zwpkgfvmcj44h.200.234.36.153.sslip.io`
Consequence: **Service Desk's registered `base_url` is `https://servicedesk.m-mines.com`**
(seed.py:301, and the 5 Sep admin-API edit set the same), so the launch URL MM OS mints points
at the dead host. Service Desk's own auth is fine — a forged token gets `bad_signature`, not
`unknown_kid`, so its JWKS is loaded.
- [ ] **Owner action:** repoint the A records for the m-mines.com subdomains at
      200.234.36.153 and re-add the domains in Coolify so it re-issues certs. Confirm with
      `GET /api/admin/services/reachability`. Whatever moved the DNS also needs finding —
      this worked on 5 Sep.
- [x] Stopgap landed: Service Desk's seed default is now the verified Coolify hostname
      (`MMOS_SVC_SERVICEDESK_URL` still overrides it); ATT/OCR/purchase defaults moved
      http→https. `seed_services()` is create-only, so the **live DB row still needs
      `python scripts/repoint_services.py --apply`** run inside the MM OS container.
- [x] Guardrails so this cannot go unnoticed again — `GET /api/admin/services/reachability`
      (7 tests), `/_mmos/health` now reports `degraded` instead of `ok` when it cannot reach
      MM OS, and `issuer` no longer follows `MMOS_URL`. See CHANGELOG.md + docs/16-decisions.md.
- [ ] Surface reachability on the admin Services page (endpoint exists, no UI yet).

**2. Project Module (purchase) sign-in loop — fixed, needs deploy.**
`GET /_mmos/accept` answered **307 → `{os}/launch/purchase`**. The root layout
(`app/layout.tsx`) is a server component, so it cannot see the request path and ran its
"no verified user → redirect to MM OS" guard on the accept page too — the one page whose job
is to create the session. The token arrives in the URL *fragment*, which the browser never
sends to the server, so the layout saw an anonymous request and bounced it back; MM OS minted
a fresh token; repeat forever. The accept page's client JS never ran.
Fixed in `C:/Users/Anura/OneDrive/Desktop/project-purchase-analytics`, branch
**`fix-mmos-handoff-loop`**, commit `105dced` (not pushed): middleware marks the allowlisted
public paths with `x-mmos-public` (stripped from every inbound request first, so it cannot be
forged) and the layout skips its guard on those. Same commit fixes the deny-list poller, which
fetched `/api/revocations` — MM OS mounts that router at `/api/agent`, so it got the SPA's
index.html back (`last_error: "Unexpected token '<'"` on `/_mmos/health`).
Verified on a production build: `/_mmos/accept` → 200, `/` → still 307 to MM OS, `/` with a
spoofed `x-mmos-public: 1` → still 307.
Two more faults were found and fixed on the same branch (`3f8a056`), each of which would
have broken the handoff again on the next redeploy: `issuer` defaulted to `MMOS_URL` (so
repointing a service silently invalidated every token), and the session cookie was
`SameSite=Lax` (never sent inside MM OS's cross-site iframe). Both branch commits are pushed.
- [ ] **Merge `fix-mmos-handoff-loop` to master and redeploy Project Module without cache.**
- [ ] Redeploy Service Desk too — it picks up the same `mmos-client-py` fixes.

## HTTPS cutover — embedding fix (5 Sep)
Root cause of "embedding broken after HTTPS": after the http→https cutover, MM OS's proxy
302-redirects http→https. The shared httpx mmos-client used `follow_redirects=False`, so
services configured with an http os_url fetched the 302 body instead of the JWKS →
`unknown_kid` on every launch token. Item Code's `requests` client already followed
redirects (so it worked). Fixed by adding `follow_redirects=True`:
- [x] mm-os `packages/mmos-client-py` (covers servicedesk) — commit bf88cb9, pushed deploy-snapshot. **REDEPLOY servicedesk.**
- [x] attplatfrom `backend/vendor/mmos_client` (saleshub) — commit 8ee3b42, pushed mmos-retrofit. **REDEPLOY saleshub.**
- [x] project-module (purchase) — repo IS on disk at `Desktop/project-purchase-analytics`. Its client is TypeScript/`jose`, not the httpx one, and `fetch` already follows redirects; the real failure was the layout redirect loop above. See the 7 Sep blocker section.
Also done via admin API (no redeploy): ERPNext + Twenty granted to all 24 users (tiles now
show); Service Desk already granted to all 24 (universal); embed base_urls switched http→https
(servicedesk/saleshub/purchase). All four embed backends now answer over https.

## In progress / cutover (root cause of several "rough" symptoms)
- [ ] **Set service keys + deploy retrofits** (Step 3-4). Until done, embedded services load unauthenticated → look rough. Affects servicedesk, saleshub, itemcode.
- [ ] **Service Desk should embed inside MM OS**, not open separately. Needs launch_mode=embed + its retrofit deployed + a key. (owner, explicit)

## UX / consistency (owner: "discuss later, keep in list")
- [ ] **Consistent UI across ALL services** — each service (Service Desk, Item Code, Sales Hub) has its own look; owner wants the MM OS design language applied *inside* each service too. Big cross-service effort; deferred but tracked.
- [ ] Services admin: **rotate-key is hard to find** — it's inside the per-service detail panel; surface it better / make the row-opens-panel affordance clearer.
- [ ] General **polish inconsistency** across pages (owner-reported). Itemise per page.

## Admin IA (proposed, owner approved direction)
- [ ] **Settings page** (new) — General/branding, Services & Links (incl. external URLs), Security, AI. Split OS-config OUT of Access.
- [ ] **People scoping** — regular users see only their **own department**; admins see full org + hierarchy. (owner confirmed "own dept")
- [ ] **External links** (ERPNext, Twenty, any URL) addable via Settings → Services & Links.

## Functional gaps (to be itemised)
- [ ] Owner reports "a lot of functionality gaps" visible in the live app — need specific pointers or a systematic review to enumerate, then fix.
