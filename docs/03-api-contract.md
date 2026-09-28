# 03 · API contract

Base: `https://os.m-mines.com` (private DNS). All JSON. All errors:

```json
{ "error": "grant_not_found", "message": "Prashanth has no access to Item Code Studio.", "request_id": "01J…" }
```

Three audiences, three auth mechanisms:

| Audience | Auth | Prefix |
|---|---|---|
| Browser (the shell itself) | `mmos_session` cookie, HttpOnly, SameSite=Lax, Domain=`.m-mines.com` | `/api/…` |
| A service talking to MM OS | `Authorization: Bearer <service_key>` | `/api/agent/…` |
| Anyone verifying a token | none, public | `/.well-known/…` |

## Public

```http
GET /healthz                    → {"ok":true,"version":"1.0.0","db":"up"}
GET /.well-known/jwks.json      → {"keys":[{"kty":"RSA","kid":"mmos-2026-08","use":"sig","alg":"RS256","n":"…","e":"AQAB"}]}
GET /embed.js                   → the OS bar (immutable, 5 min cache)
GET /manifest.webmanifest       → PWA manifest
GET /api/public/services        → the entry-page directory (no session required)
```

```json
{ "services": [
  { "slug": "erpnext",  "name": "ERPNext",          "launch_url": "https://minimines-uat.m.frappe.cloud", "session_owner": "service" },
  { "slug": "itemcode", "name": "Item Code Studio", "launch_url": "https://itemcode.m-mines.com",         "session_owner": "mmos" }
] }
```

**Names and launch URLs only.** No roles, no health, no owner, no counts, no employee data —
this endpoint is reachable without signing in, so every field on it is a field published to
anyone who can reach the login page. `session_owner` tells the entry page whether a click
bounces through MM OS (`mmos`) or lands on the service's own sign-in (`service`).

## Session

```http
GET  /api/auth/google/start?next=/            → 302 to Google (state + PKCE in a signed cookie)
GET  /api/auth/google/callback?code=&state=   → sets mmos_session, 302 to next
POST /api/auth/pin                            {"employee_code":"MM19","pin":"…"} → sets session
POST /api/auth/logout                         → clears cookie, revokes session row
```

`/api/auth/pin` is rate limited: 5 attempts per employee code per 15 minutes, then a 15
minute lock. Failures are audited with the source IP.

## The one call the shell lives on

```http
GET /api/me
```

```json
{
  "user":     { "id": "u-9f3…", "name": "Prashanth V", "employee_code": "MM32",
                "email": "prashanth@m-mines.com", "auth_type": "google",
                "department": "Purchase", "division": "Finance", "band": "L1S",
                "approval_level": "L1 (Associate)", "is_platform_admin": false },
  "services": [
    { "slug": "erpnext",  "name": "ERPNext",           "category": "erp",
      "role": "user",  "launch_mode": "handoff", "base_url": "https://minimines-uat.m.frappe.cloud",
      "icon": "database", "health": "up" },
    { "slug": "itemcode", "name": "Item Code Studio",   "category": "production",
      "role": "viewer", "launch_mode": "handoff", "base_url": "https://itemcode.m-mines.com",
      "icon": "hash", "health": "up" }
  ],
  "badges": { "servicedesk_open": 2, "approvals_waiting": 0 }
}
```

`services` is already filtered to what this person may open. The shell never filters
client-side, and never receives a service the user has no grant for.

## Handoff — how a click becomes a logged-in session elsewhere

```http
POST /api/token/service      {"slug":"itemcode"}
→ 200 {"access_token":"eyJ…","token_type":"Bearer","expires_in":900,
       "launch_url":"https://itemcode.m-mines.com/_mmos/accept#token=eyJ…"}
```

Requires a live session **and** a matching grant. Denied with `403 grant_not_found`
otherwise. Every issue is written to `audit_log` with action `token.issue`.

The token travels in the URL **fragment**, not the query string — fragments are never sent
to servers, never logged by proxies, and never land in the browser history entry sent
onward. `/_mmos/accept` is provided by `mmos-client-py`: it reads the fragment, sets the
service local cookie, and immediately `history.replaceState`s the token out of the URL bar.

### Token claims

```json
{
  "iss": "https://os.m-mines.com",
  "sub": "user:9f3c1e6a-…",
  "aud": "itemcode",
  "jti": "01J8Z…",
  "iat": 1774000000,
  "exp": 1774000900,
  "emp": "MM32",
  "email": "prashanth@m-mines.com",
  "name": "Prashanth V",
  "dept": "Purchase",
  "division": "Finance",
  "band": "L1S",
  "approval_level": "L1 (Associate)",
  "roles": ["viewer"],
  "platform_admin": false
}
```

RS256, `kid` in the header, 15 minute life, `aud` is exactly one service. A token minted for
`itemcode` is worthless at `att` — that is the point of per-service minting.

## Revocation (the deny-list services poll)

```http
GET /api/revocations?since=2026-08-22T10:00:00Z
Authorization: Bearer <service_key>
```

```json
{ "now": "2026-08-22T10:01:00Z", "poll_after_seconds": 60,
  "revoked_subjects": [ {"sub":"user:9f3c…","reason":"grant_removed","at":"2026-08-22T10:00:42Z"} ],
  "revoked_jti": [] }
```

Scoped automatically to the calling service plus global entries. The client library merges
this into an in-memory set and rejects matching tokens even when the signature is valid.
**If MM OS is unreachable, the last known list is kept and requests continue** — availability
beats freshness for a 15-minute token, and the firewall is still in front of everything.

## Service → MM OS

```http
POST /api/agent/heartbeat
Authorization: Bearer <service_key>
{
  "version": "2.0.1",
  "llm": { "provider": "anthropic", "model": "claude-opus-5", "key_present": true, "enabled": true },
  "usage": { "day": "2026-08-22", "requests": 41, "input_tokens": 128400, "output_tokens": 9100 }
}
→ 200 {"llm_enabled": true, "config_version": 7}
```

```http
GET /api/agent/config     → {"llm_enabled": false, "config_version": 8, "poll_after_seconds": 60}
```

One call does three jobs: proves the service is alive, populates the LLM control plane, and
picks up the kill switch. Omit `llm` and the service shows as `unreported` — visible, not
silent. Omit `usage` and the consumption columns stay blank.

## Admin (requires `is_platform_admin`)

```http
GET    /api/admin/employees?q=&dept=&status=
POST   /api/admin/employees
PATCH  /api/admin/employees/{id}
POST   /api/admin/employees/import          multipart xlsx → dry-run diff, then ?commit=true

GET    /api/admin/users
PATCH  /api/admin/users/{id}                {"is_active":false}  → cascades a revocation row
POST   /api/admin/users/{id}/pin            {"pin":"…"} | {"clear":true}

GET    /api/admin/services
POST   /api/admin/services
PATCH  /api/admin/services/{slug}
POST   /api/admin/services/{slug}/roles     {"key":"admin","name":"Administrator"}
POST   /api/admin/services/{slug}/rotate-key → {"service_key":"shown once"}

GET    /api/admin/grants?service=&user=
POST   /api/admin/grants                    {"user_id":…,"slug":"itemcode","role":"admin","reason":"…"}
DELETE /api/admin/grants/{id}               → writes a revocation row immediately
POST   /api/admin/grants/bulk               {"slug":"att","role":"viewer","band":["L3","L4"]}

GET    /api/admin/llm                       → registrations + 30-day usage
POST   /api/admin/llm/{slug}/toggle         {"enabled":false,"reason":"cost spike"}

GET    /api/admin/audit?action=&actor=&from=&to=&limit=100
```

`POST /api/admin/employees/import` is a **dry run by default** — it returns the diff (new,
changed, missing, conflicting) and applies nothing until `?commit=true`. Re-importing the
spreadsheet must never be able to silently orphan a grant.

## Rules that hold everywhere

- Nothing mutating is a `GET`.
- Every mutating admin route writes `audit_log` in the same transaction as the change.
- Deleting a grant or deactivating a user writes a `revocations` row in that same transaction — access removal is never a two-step that can half-fail.
- Pagination is `?limit=&cursor=`, default 50, max 200.
