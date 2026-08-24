# 11 · Security review

Written by B3 (hardening, run 2), 24 Aug 2026, against the build B1 assembled and verified
green (`backend/tests` 72 passed/1 skipped, `servicedesk/tests` 31, `packages/mmos-client-py`
15, `packages/embed` smoke 5, both frontend builds, `scripts/verify/acceptance.sh local` 12/0/5
— re-confirmed identically before this review started, and 15/0/5 after this review's own
three additions to that script; see `handoff/b3-hardening.md`).

**Every finding below was reproduced**, either by reading the exact code path and tracing it
end to end, or by running a script that exercises it (`scripts/verify/verify-security.sh`,
`scripts/verify/verify-offboard.sh`, `pip-audit`, `npm audit`). Where something could not be
reproduced without Docker or a live Postgres/VPS, that is stated plainly rather than assumed
either way.

**Ranking is by exploitability inside this specific deployment** — VPN-only,
`NETWORK_MODE=private`, ~74 accounts, a handful of registered internal services — not by
generic CVSS-style severity. A theoretical hole nobody in this deployment can reach is listed
below the real ones, not above them.

---

## Findings, ranked

### 1 · HIGH (conditional on infrastructure I could not test) — a published container port can turn "not internet-facing" into false

**What breaks.** `deploy/docker-compose.yml`'s `api` service publishes `ports: - "8000:8000"`,
which binds `0.0.0.0:8000` on the VPS host by default. Docker manages published ports through
its own iptables rules in the `DOCKER`/`FORWARD` chains, inserted independently of `ufw`'s
`INPUT` chain — this is a long-documented interaction (Docker issue moby/moby#4737 and a large
body of follow-on operator documentation), where a container port published this way is
reachable from the public internet **even when `ufw status` shows it denied**, unless the
operator has separately added `DOCKER-USER` chain rules or a tool like `ufw-docker`.
`deploy/NETWORK.md`'s `ufw` ruleset (allow only 22/tcp, 51820/udp, and 443/tcp from specific
sources) does not by itself close port 8000 — it only looks like it does.

If port 8000 is reachable directly (bypassing Coolify's Traefik, which is the thing actually
supposed to gate 443), the second independent enforcement point — `NETWORK_MODE=private`'s
CIDR allowlist — is also defeated, because of how it trusts `X-Forwarded-For`:
`backend/app/deps.py::client_ip()` takes the `MMOS_TRUSTED_PROXY_COUNT`-th entry from the right
of the header **whenever the header is present**, with no way to verify that entry was actually
appended by a trusted proxy rather than typed by the caller. I proved this mechanically
(`scripts/verify/verify-security.sh`, check "client_ip() cannot tell a real proxy hop from a
self-supplied header"): a caller at an arbitrary public IP sending its own
`X-Forwarded-For: 10.8.0.1` is trusted exactly as if Coolify's Traefik had added that entry.
`deploy/COOLIFY.md` §6 already names the correct live test for this
(`curl -H "X-Forwarded-For: 10.8.0.1" https://os.m-mines.com/api/me` from outside the VPN,
expecting `403`) — it just has not been run against a real deployment yet.

**Net effect if both are true:** an internet attacker reaches every MM OS route with no
authentication bypass (Google OIDC / PIN is still required), but the entire premise of
`docs/06`'s threat model — "not internet-facing," which is what justifies treating credential
phishing and brute force as low risks — is false, and every endpoint including the login
surfaces and JWKS becomes reachable by anyone.

**Reproduced:** the `X-Forwarded-For` trust behavior, mechanically, in
`scripts/verify/_security_checks.py`. **Not reproduced:** the actual Docker/ufw port exposure —
there is no VPS or Docker host reachable from this build machine (docs/09's standing
amendment). This is reported as a well-known, high-probability misconfiguration class given
what's in the compose file today, not an observed live exploit.

**Fix.** Either:
- Remove the `ports: ["8000:8000"]` mapping from `deploy/docker-compose.yml` entirely.
  Coolify's Traefik reaches sibling containers over the internal Docker network by service
  name/label, not by a published host port (`deploy/COOLIFY.md` §1, §8 already describe Traefik
  as the thing terminating 80/443 — a host-published port on `api` is not what makes that work);
  or
- If a host-published port is genuinely required for some other reason, bind it to loopback
  only (`127.0.0.1:8000:8000`) so nothing outside the host can reach it directly, and add an
  explicit `iptables -I DOCKER-USER -p tcp --dport 8000 -j DROP` rule (or install `ufw-docker`)
  as insurance against a future compose change re-opening it.

Then run `deploy/COOLIFY.md` §6's curl test for real, from a machine outside
`MMOS_ALLOWED_CIDRS`, and confirm it returns `403`.

This is a `deploy/**` file (A6-owned, not `scripts/verify/**` or `docs/10-11`), and the correct
fix depends on exactly how Coolify's proxy is configured on the real VPS (verified fact I don't
have) — so it is written up here with the exact fix rather than applied.

---

### 2 · HIGH, but self-limiting — `POST /api/auth/pin` has no throttle beyond per-account lockout, and employee codes are guessable

**What breaks.** `pin_login` (`backend/app/routers/auth.py`) locks one account after 5 wrong
PIN attempts for 15 minutes (`user.failed_pin_attempts`/`locked_until`), which correctly
defeats brute-forcing *one* person's PIN. But nothing throttles the endpoint itself by IP or
globally — unlike `POST /api/token/service`, which has an explicit 60/minute/user in-memory
limiter (`backend/app/routers/tokens.py`). Employee codes are short and patterned (`MM` plus one
or two digits, confirmed against the real sheet and `app/seed.py`'s synthetic ones), so anyone
who can reach the endpoint — anyone on the VPN, including a compromised laptop, or an internet
attacker if finding #1 above is real — can send 5 wrong-PIN attempts against every one of the 73
employee codes in well under a minute and lock every PIN account in the company simultaneously.

**Why this ranks where it does.** It is not a data-breach risk (the accounts don't get
compromised, they get locked), and it self-heals in 15 minutes. But it is trivial to execute
from inside the trust boundary this deployment actually relies on (VPN access), and it lands
squarely on the population this PIN path exists to serve — the ~50 staff with no corporate
mailbox, who have no other way in during the lockout window. A malicious or merely careless
script on one VPN-connected laptop, run once, denies MM OS access company-wide for 15 minutes.

**Reproduced:** read `pin_login` end to end — the only throttle keys off the target user row,
nothing keys off the caller.

**Fix.** Add the same in-memory sliding-window pattern already used in
`backend/app/routers/tokens.py` to `POST /api/auth/pin`, keyed by `client_ip(request)` rather
than by user (e.g. 20/minute/IP — generous enough for a shared shop-floor terminal with normal
typos, tight enough to blunt an enumeration script). This is a few lines in
`backend/app/routers/auth.py` (A1-owned, not frozen, but not a B3-owned path either, and the
right threshold is a product judgment call) — written up rather than applied.

---

### 3 · MEDIUM — rate limiting is in-process and in-memory; a second worker or replica silently disables it

`POST /api/token/service`'s 60/min/user limiter (and finding #2's proposed fix, if added) is a
plain `dict[str, deque[float]]` inside one Python process. **As currently deployed this is fully
effective**: `deploy/Dockerfile`'s `CMD` runs `uvicorn app.main:app` with no `--workers` flag
(one process), and `deploy/docker-compose.yml` runs exactly one `api` container. The moment
anyone scales to more than one worker or more than one replica — an ordinary future move on
Coolify, and one that requires no code change to make — every limit silently becomes N times
more permissive with no error, no log line, and no test that would catch it, because each
process keeps its own counter. State this plainly in the runbook (`docs/10-runbook.md` §
"Known limits") so a future capacity change doesn't quietly reopen this. Fix if it's ever
needed: a shared store (Redis) — already correctly named as future work in A2's own handoff.

---

### 4 · MEDIUM — no Content-Security-Policy header anywhere

`docs/06-network-security.md`'s own "Baseline hardening" list requires a CSP
(`default-src 'self'; connect-src 'self'; frame-ancestors 'none'`). `backend/app/middleware.py`'s
`SecurityHeaders` sets `X-Content-Type-Options`, `Referrer-Policy`, `Strict-Transport-Security`
and `X-Frame-Options`, but never `Content-Security-Policy`. Confirmed by reading the file and
mechanically by `scripts/verify/verify-security.sh` (`WARN no Content-Security-Policy header on
any response`) against every response the running app returns, including `/healthz`.

`middleware.py` is frozen spine (`docs/09-build-agents.md`) — I did not edit it. **Fix**, for
whoever next makes a frozen-spine change:

```python
response.headers.setdefault(
    "Content-Security-Policy",
    "default-src 'self'; connect-src 'self'; frame-ancestors 'none'",
)
```

in `SecurityHeaders.dispatch`, in `main.py`'s existing block that already special-cases
`/embed.js` for `X-Frame-Options` — `embed.js` itself doesn't need a CSP exemption on MM OS's
side (a service embedding it sets its own page's CSP; MM OS's CSP only governs MM OS's own
responses). Low urgency in practice: the shipped frontend is React with default escaping and no
`dangerouslySetInnerHTML`/raw-HTML sink found anywhere in `frontend/src` or
`servicedesk/frontend/src` during this review, so a missing CSP is a real but currently
low-cost gap, not a live injection path.

---

### 5 · LOW/MEDIUM, mostly theoretical in this deployment — `GET /api/agent/org/chain` has no per-endpoint ACL

B1 already flagged this (`handoff/b1-assembly.md` `## Assumptions`). Any service holding a valid
service key can call `GET /api/agent/org/chain?sub=` for an arbitrary subject — the same trust
boundary `heartbeat`/`config`/`revocations` already share. Minimum disclosure already limits the
response to 7 fields (no band, division, job title). Given VPN-only deployment and a realistic
population of service-key holders that is small — the internal services that actually integrate
`mmos-client-py` and hold a rotated key (Item Code Studio, ATT, Service Desk; ERPNext and Twenty
are `launch_mode="external"` and, by design, don't call back into MM OS's agent surface at all)
— exploiting this requires an attacker to have already compromised one of those services' keys,
which already grants everything `heartbeat`/`config`/`revocations` grant. I rank this low
specifically because the marginal disclosure this endpoint adds on top of an already-severe
compromise is small, not because the missing ACL is fine in principle.

**Fix**, if wanted: an explicit allowlist inline in `agent.py`
(`if service.slug not in {"servicedesk"}: raise HTTPException(403, ...)`) or a proper
`allowed_callers` column on `Service`. Not applied — behavioral ambiguity (would need to be kept
in sync with which services legitimately need org-chain lookups, and a hardcoded slug list
breaks the moment a second consumer needs it).

---

### 6 · LOW — dependency CVEs (recorded, not fixed; `requirements.txt` is orchestrator-owned)

Run today, against the exact pinned versions in the tree:

```
backend/.venv/Scripts/python.exe -m pip_audit -r backend/requirements.txt
backend/.venv/Scripts/python.exe -m pip_audit -r servicedesk/requirements.txt
cd frontend && npm audit --omit=dev
cd servicedesk/frontend && npm audit --omit=dev
```

| Package | Pinned | Advisories | Fix |
|---|---|---|---|
| `python-jose[cryptography]` (backend + servicedesk) | 3.3.0 | PYSEC-2024-232, PYSEC-2024-233, PYSEC-2025-185 | 3.4.0 |
| `cryptography` (backend) | 44.0.0 | 7 advisories incl. GHSA-537c-gmf6-5ccf | newest 4x.x patch compatible with the pinned `psycopg`/`argon2-cffi` build |
| `python-multipart` (backend) | 0.0.20 | 6 advisories | ≥0.0.22 (check FastAPI 0.115.6's own compatible-version pin first) |
| `starlette` (backend + servicedesk, transitive via `fastapi==0.115.6`) | 0.41.3 | 9 advisories | needs a `fastapi` bump, not a bare `starlette` bump |
| `ecdsa` (transitive via `python-jose`) | 0.19.2 | PYSEC-2026-1325 | resolved by the `python-jose` bump above |
| `react-router-dom` / `@remix-run/router` (frontend) | 6.30.2-era | GHSA-2w69-qvjg-hvjx, GHSA-2j2x-hqr9-3h42 (open-redirect/XSS class) | `react-router-dom@6.30.6` (non-breaking patch; do **not** run `npm audit fix --force`, which would jump a major version) |
| servicedesk/frontend | — | 0 findings | — |

None of these are remotely exploitable the way they would be on an internet-facing deployment —
VPN-only cuts off the population of attackers who could reach network-triggered bugs at all —
but `cryptography`'s advisories are worth prioritizing regardless of network exposure, since a
compromised or malicious *registered service* is already inside the trust boundary those bugs
would matter to, and this deployment's threat model already treats a compromised VPN-connected
client as the realistic adversary (`docs/06`'s own risk table: "a compromised laptop on the VPN
is inside everything"). `backend/requirements.txt` and `servicedesk/requirements.txt` are
orchestrator-owned (`docs/09`) — recording exact target versions here rather than editing them.

---

## Verified — not findings

The brief asked specifically about these; each was traced end to end or mechanically
re-proven, not just read and assumed correct.

### The Google-link flow resolves its target strictly from the live session

Traced `google_link_start` → `_make_oauth_cookie(purpose="link", linking_user_id=user.id)` →
`google_callback` → `_complete_google_link` (`backend/app/routers/auth.py`). The target user is
read only via `current_session(request, db)` / `current_user(sess, db)` — the live
`mmos_session` cookie — **never** from the OIDC `id_token`'s claims or anything else the client
sent in the callback request. The `uid` value baked into the signed, HMAC-protected oauth-state
cookie is compared against the live session's resolved user id purely as defense-in-depth
against the signed-in session changing mid-flow (a second sign-in in another tab): a mismatch
409s (`link_session_mismatch`) rather than silently linking to whoever happens to be signed in
by the time the callback lands. I could not find a path where the target user is taken from
anything the callback supplies. This holds under every path I traced, including a session swap
mid-flow.

Residual, already-accepted trade-off (not new — A1's handoff and `handoff/ORCHESTRATOR.md`
already name it, restated here because it's genuinely security-relevant): no `google_sub`
column and a mutable `login_email` mean a changed Google-side address reads as "unknown email"
rather than "same person, new address" on a future sign-in, requiring the person to re-link.
Also: for anyone signing in with a personal Google account, MFA is whatever that account's own
2FA is — it cannot be enforced from Workspace admin — and offboarding **must** be done by
deactivating the MM OS user, since disabling a corporate mailbox does not lock out a linked
personal account. This is in `docs/10-runbook.md`'s offboarding procedure.

### No placeholder `pin_hash` can authenticate

Every seeded user's placeholder is `hash_pin(f"{secrets.randbelow(1_000_000):06d}")`
(`app/seed.py`) — argon2-hashed, generated with `secrets` (not `random`), never displayed,
never logged, never returned by any API. Grepped every file under `backend/app` for a
log/print statement touching `pin`/`pin_hash`: none exists — `audit()` rows never carry PIN
values, only action names and non-secret metadata. `pin_login` keys success on `pin_hash` being
present **and correct** via `verify_pin` (argon2), never on `auth_type` alone, and the
5-attempts/15-minute lockout (`MMOS_PIN_MAX_ATTEMPTS`/`MMOS_PIN_LOCKOUT_MINUTES`) makes
brute-forcing a specific 6-digit placeholder impractical (≈1,000,000 combinations at 5 guesses
per 15 minutes is years, not an attack anyone would run). Mechanically re-proven in
`scripts/verify/verify-security.sh`.

### `platform_admin` correctly no longer bypasses a service's own role check — with one operational consequence

Traced every `require_role`/`can_see_full`/`_is_agent` call site in
`packages/mmos-client-py/mmos_client/core.py` and `servicedesk/app/{mmos_seam,privacy,routers/tickets,routers/comments}.py`.
None grants an automatic bypass to `platform_admin` — B1's removal (seam inventory §A.3) is
complete, not partial. This is the right call: a service's role vocabulary is its own, and a
platform admin silently inheriting "sees every private ticket" or "has the Service Desk agent
console" would be exactly the invisible privilege escalation the whole grants model exists to
prevent.

**Operational consequence, not a vulnerability:** `seed_platform_admin()` (`app/seed.py`) never
creates a grant for `MM-ITADMIN` on any service. IT starts with **zero grants anywhere**,
including Service Desk, and must explicitly grant itself the relevant role
(`POST /api/admin/grants`) before it can open a service's own console — same as anyone else.
This is a feature (the audit log then shows exactly when and why IT gained access, instead of an
always-on invisible admin backdoor), but it needs to be documented so it is not discovered as
"IT can't get into Service Desk" during an actual incident. Added to `docs/10-runbook.md`.

### The deny-list end-to-end chain is wired correctly, proven fresh, not just inspected

`DELETE /api/admin/grants/{id}` and `POST /api/admin/users/{id}/kill`
(`backend/app/routers/platform.py`) both write a `Revocation` row in the **same transaction** as
the access-removing change. `GET /api/agent/revocations` (mounted at `/api/agent/revocations` —
B1 already fixed the historical divergence where `packages/mmos-client-py`'s poller targeted the
bare `/api/revocations` path from `docs/03`'s own inconsistent example) serves them
service-scoped. `mmos_client._denylist.DenyListPoller.poll_once()` polls exactly that path and
merges into an in-memory `DenyList`; `mmos_client._verify.verify_token()` checks it after
signature/iss/aud/exp, before returning claims.

I re-ran this specific chain end to end via `scripts/verify/_security_checks.py` — not just the
existing test suite — and additionally proved cross-service isolation (a revocation scoped to
one service's grant is **not** visible to a different service's poll of the same endpoint).
`scripts/verify/_offboard_check.py` separately proves a full user deactivation revokes the shell
session cookie immediately (a *second* client presenting the same raw cookie value is also
rejected — this is not a cache artifact of the first client) and lands the subject on the
deny-list every service will see on its next poll, all inside one process.

**Not reproduced:** the real 60-second wall-clock SLA between two independently running
processes over a network — A4's handoff already did this once, live, against the real
background poller thread (`examples/echo-service`), and nothing about the wiring has changed
since. I did not repeat that specific live run.

### The LLM control plane cannot have a key smuggled through it, and the kill switch works — with a propagation delay worth knowing

`heartbeat`'s `_strip_key_fields`/`_looks_like_key` (`backend/app/routers/agent.py`) regex-drops
any field that looks like a credential by name. Traced further than the regex itself: even a
field name that evades the regex (e.g. `"credential"`, which matches none of
`api[_-]?key|secret|password|access[_-]?token`) still cannot be persisted, because the handler
only ever *reads* `provider`, `model`, and `key_present` out of the incoming `llm` object — every
other key, caught by the regex or not, is simply discarded. The regex is a second, redundant
layer of defense on top of an already-safe explicit whitelist, not the only thing standing
between a heartbeat payload and the database.

The kill switch (`POST /api/admin/llm/{slug}/toggle`) does stop calls, but not instantly: a
service's cached `llm_enabled` flag (`mmos_client._heartbeat.Heartbeat`) only updates on its next
heartbeat, default every 300 seconds, and **defaults to `True` (open) until the first heartbeat
ever lands** — a deliberate availability trade-off (A4's handoff) so a control-plane restart
doesn't 503 every LLM route company-wide. Net effect: "disable all LLM" takes up to 5 minutes to
take effect per service, and a service that has just restarted has up to 5 minutes of
LLM access open by default even if it was disabled before the restart. Documented in
`docs/10-runbook.md`'s emergency-disable procedure so nobody is surprised by the delay
mid-incident.

### Cookies, sessions, admin surface, injection

- **Cookie flags** match `docs/06`: `HttpOnly`, `Secure` (`cookie_secure` defaults `true`),
  `SameSite=Lax`, `Domain=.m-mines.com` by default — read from `_cookie_kwargs`
  (`backend/app/routers/auth.py`) and mechanically confirmed on a real login response
  (`scripts/verify/verify-security.sh`).
- **Logout revokes server-side** (`sess.revoked_at = now()`, `routers/auth.py::logout`) —
  session tokens are opaque and DB-checked on every request (`security.py`'s own comment:
  "deliberately not a JWT: the shell session must be revocable the instant an admin deactivates
  someone"), not JWTs that would keep verifying until expiry.
- **Deactivating a user revokes every live session and writes a revocation row in one
  transaction** (`routers/people.py::update_user`) — confirmed by reading it and by
  `scripts/verify/verify-offboard.sh`'s synthetic run.
- **CSRF**: `SameSite=Lax` on the session cookie blocks a cross-site `POST`/`PATCH`/`DELETE`
  from carrying it (Lax only attaches cookies to top-level-navigation `GET`s), and every
  state-changing admin route in this codebase is `POST`/`PATCH`/`DELETE`, never a mutating
  `GET`. No separate CSRF token is needed given that shape, and none was found missing.
- **Admin surface**: every `/api/admin/*` route depends on `require_admin`
  (`backend/app/deps.py`), which checks `user.is_platform_admin` — confirmed by reading every
  router file mounted under that prefix (`people.py`, `platform.py`) and by
  `scripts/verify/verify-security.sh`'s direct 401/403 check. `models.py`'s
  `no_pin_admins` CHECK constraint (`NOT (auth_type='local_pin' AND is_platform_admin)`) makes a
  PIN-authenticated admin structurally impossible at the schema level, not just by convention —
  confirmed by reading the constraint; not exercised against a real Postgres (SQLite enforces
  CHECK constraints identically, and the existing test suite already covers this path).
- **Injection**: every query reviewed uses SQLAlchemy's Core/ORM query builder
  (`select(...).where(...)`) — no raw SQL string interpolation was found anywhere in
  `backend/app` or `servicedesk/app`. `openpyxl`'s spreadsheet reader (`app/seed.py`) reads
  cell values only, never evaluates formulas (`data_only=True`).
- **Secrets**: the signing key is a mounted file
  (`_load_or_create_key` reads `settings().signing_key_path`, and
  `deploy/docker-compose.yml`'s `secrets:` block mounts it at exactly that path), never an env
  var. No log or print statement anywhere in `backend/app`/`servicedesk/app` touches a PIN,
  token, service key, or the signing key's contents (grepped for `print(`/`logger.`/`logging.`
  across every file that handles one). `.gitignore` excludes `.env`, `*.pem`, `*.key`, and
  `run/secrets/`; no `.env` or stray non-vendor `.pem` file exists anywhere in the working tree
  today. **Not verified**: whether a secret was ever committed and later removed (a rotated
  secret is still compromised even if the current tree is clean). Checking that needs
  `git log --all -p -- '**/.env' '**/*.pem' '**/*.key'` — I was instructed not to run git
  commands (the orchestrator owns version control); ask the orchestrator to run this once.

---

## Not verified without a live deployment

- **The Docker/`ufw` port-exposure question (finding #1)** — no VPS or Docker host reachable
  from this build machine.
- **`MMOS_TRUSTED_PROXY_COUNT` against the real Coolify/Traefik chain** — same limitation;
  `deploy/COOLIFY.md` §6 already has the exact curl command to run once deployed.
- **The 60-second revocation SLA between two independently running live processes over a real
  network** — A4 proved this once already against `examples/echo-service`; not re-run here.
- **`alembic upgrade head` against a real Postgres**, and anything Postgres-specific
  (`pgcrypto`, JSONB containment operators) — no Postgres on this machine. SQLite enforces the
  same CHECK constraints and unique constraints this review leans on, so the *logic* reviewed
  above is not in doubt, but the migration itself has never run for real (A1's handoff already
  says this; repeating it here because it is directly relevant to trusting the schema this
  review assumes exists).
- **Whether a secret was ever committed to git history** — see above; needs a git command I was
  instructed not to run.
