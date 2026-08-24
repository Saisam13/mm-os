# Agent B3 · Hardening, runbook and cutover pack

**MM OS** is assembled (agent B1) and the existing services are being retrofitted (agent B2,
running in parallel with you). Your job is to make it safe to hand to 74 people and operable
by someone who did not build it. You write no features.

**Read first:** `docs/06-network-security.md` (the posture and the risk table),
`docs/08-v1-plan.md` (the eight v1 criteria), `handoff/b1-assembly.md` (what actually got
built and what it left), then the code you are reviewing.

## You own exclusively

```
docs/10-runbook.md    docs/11-security-review.md    scripts/verify/**    docs/12-floor-guide.md
```

Fixes you find go in as **minimal, targeted patches** — record each in your handoff. If a fix
is larger than a few lines, write it up as a finding instead of doing it.

## 1 · Security review — `docs/11-security-review.md`

Adversarial read of the whole system, not a checklist tick. For each finding: what breaks,
how to reproduce it, severity, and the fix. Verify each claim before writing it down — a
review full of theoretical findings gets ignored, and then the real one gets ignored too.

Cover at minimum:

- **Token handling** — `aud` enforced; `alg` confusion (`none`, `HS256`) rejected; expiry and skew; `kid` handling; is the token ever logged, ever in a query string, ever in `document.referrer`?
- **The deny-list** — does removal actually block within 60s; does the poller fail open on purpose and is that acceptable here; can a service read another service's revocations?
- **Dual-mode Item Code Studio** — is there any mutating endpoint outside `/api/admin/*`; does the read-only role genuinely lack write privileges (test it with a real `INSERT`); is `public_paths` minimal?
- **Session and cookies** — HttpOnly, Secure, SameSite, domain scope; does logout revoke server-side; does deactivating a user kill live sessions in one transaction?
- **The network gate** — is `TRUSTED_PROXY_COUNT` correct for the real proxy depth; can `X-Forwarded-For` be spoofed to pass the CIDR allowlist? Test this with a crafted header, because getting it wrong turns the allowlist into decoration.
- **Admin surface** — every `/api/admin/*` route refuses a non-admin; can a PIN user hold admin (the schema forbids it — confirm nothing bypasses it)?
- **Secrets** — is the signing key a mounted file and not an env var; does any log, error page or crash report contain a key, a PIN, or a token; is `.env` gitignored and absent from history?
- **LLM control plane** — can a heartbeat smuggle an API key into MM OS; does the kill switch actually stop calls?
- **Injection and dependencies** — SQLAlchemy parameterisation throughout; `pip audit` and `npm audit` output recorded.

## 2 · Runbook — `docs/10-runbook.md`

Written for the person on call at 11pm who did not build this. Every entry is commands and
expected output, not prose.

- deploy, roll back, read logs, restart cleanly
- **onboard an employee** (Google account → MM OS user → grants → VPN peer) and **offboard one** (the exact order: disable Google, deactivate MM OS user, delete VPN peer, verify with a real login attempt)
- issue and reset a PIN
- register a new service end to end, including the key and the first grant
- rotate the signing key without downtime (overlapping publication, per `docs/04-auth-flow.md`)
- **emergency revoke** one user, and emergency **disable all LLM** across services
- restore from backup into a scratch database, and the quarterly restore-test procedure
- the monthly VPN-peer versus active-employee audit
- what to do when: MM OS is down, Postgres is down, Frappe Cloud is down, certificates expired, a laptop is lost
- where the logs, backups and audit trail live, and how long each is kept

## 3 · Verification scripts — `scripts/verify/`

Extend B1's `acceptance.sh` with:

- `verify-security.sh` — the mechanical security assertions above, runnable after any change
- `verify-backup.sh` — dump, restore into scratch, compare row counts, report
- `verify-offboard.sh` — given an employee code, prove access is gone everywhere

Each prints one pass/fail line per check and exits non-zero on any failure. These outlive the
project; they are how a future change gets checked without re-reading every doc.

## 4 · Floor guide — `docs/12-floor-guide.md`

One page, printable, for the 30-minute training in the M6 cutover. Written for a plant
operator, not an engineer: how to sign in (Google, or code and PIN), what the tiles are, how
to get back to MM OS from any service, how to raise a support ticket, how to request an
automation, and who to call. No jargon, no screenshots of things that will change next week.

## 5 · Prove the v1 criteria

Go through the eight criteria in `docs/08-v1-plan.md` and record, for each, the evidence:
command run, output seen. A criterion without evidence is not met — say so plainly rather
than assuming.

## Guardrails

No features, no refactoring, no redesign. Findings over fixes when a fix is more than a few
lines. Verify every claim before writing it — do not report a vulnerability you have not
reproduced. Never touch the live ERPNext instance, real secrets, or production data. If a
check resists two attempts, record it under `## Not done` with what it blocks.

## Finish by writing `handoff/b3-hardening.md`

`## Findings` (severity-ordered, each reproduced) · `## Fixes applied` (each, with the diff
summary) · `## Findings left open` (with why) · `## v1 criteria evidence` (all eight) ·
`## Not done`.
