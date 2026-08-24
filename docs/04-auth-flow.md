# 04 · Auth flow

## Login (Google)

```
Browser                    MM OS                     Google
   │  GET /                  │                          │
   │─────────────────────────▶ no session → 302 ────────▶ accounts.google.com
   │                         │  (state+PKCE in signed cookie, hd=m-mines.com)
   │◀──────── user authenticates, MFA challenge ─────────│
   │  GET /api/auth/google/callback?code=&state=         │
   │─────────────────────────▶ verify state, exchange code
   │                         │  → id_token
   │                         │  assert: aud, iss, exp, email_verified, hd == m-mines.com
   │                         │  look up users.login_email → must exist and be active
   │◀── Set-Cookie: mmos_session (HttpOnly, Secure, SameSite=Lax, .m-mines.com) ──
```

Two rules that matter:

- **`hd` is checked server-side, not just passed as a hint.** The `hd` parameter on the
  authorize URL is a convenience for the user; a hostile client can drop it. The claim in the
  returned `id_token` is the thing that decides.
- **Google authenticating you is not the same as you having an account here.** If the email
  is not in `users`, the login fails with `unknown_user` — a real Google account at some
  other domain, or an ex-employee whose row was deactivated, gets nothing. Provisioning is a
  deliberate admin act, never a side effect of a successful Google login.

## Login (PIN, for staff without a mailbox)

Shop-floor operators (`MM19` and similar) have no Google account. They log in with employee
code plus a 6-digit PIN, hashed with argon2id.

- 5 attempts per employee code per 15 minutes, then a 15-minute lock; every failure audited with IP
- PINs are issued and reset by IT in the admin UI, never self-service, and shown once
- PIN users are visibly flagged in admin, and they cannot hold `is_platform_admin`

This exists because the alternative is a shared account on a shared terminal, which destroys
every audit trail in the system.

## Session

`mmos_session` is an opaque random 32-byte token; the hash is stored in `sessions`. It is not
a JWT — the shell session must be revocable instantly, and only a server-side lookup gives
that. 12-hour life, sliding, capped at 7 days. Logout revokes the row.

## Opening a service

```
Browser                    MM OS                      Item Code Studio
   │ click tile             │                                │
   │ POST /api/token/service {"slug":"itemcode"}             │
   │───────────────────────▶│ session valid?                 │
   │                        │ grant exists? → role           │
   │                        │ mint RS256 JWT, aud=itemcode,  │
   │                        │ exp=+15m, audit token.issue    │
   │◀─ launch_url ──────────│                                │
   │ GET /_mmos/accept#token=eyJ…                            │
   │────────────────────────────────────────────────────────▶│ verify sig via cached JWKS
   │                        │                                │ check aud, exp, deny-list
   │◀────── Set-Cookie: itemcode_session; history.replaceState ─
```

The service now has its own short session and never talks to MM OS again on the hot path.
MM OS going down does not log anyone out of a service they are already inside.

## Verification, in the exact order the client library does it

1. `kid` in header resolves against cached JWKS (refetch on miss, at most once a minute)
2. RS256 signature valid
3. `iss` == configured MM OS issuer
4. `aud` == this service slug — *a token for another service is rejected even though it is perfectly signed*
5. `exp` / `iat` within 60s clock skew
6. `sub` not in the deny-list set, `jti` not in the deny-list set
7. `roles` mapped to the service local role names

Any failure is a `401` with a machine-readable reason and no detail leaked to the browser.

## Revocation, end to end

```
Admin removes grant ──▶ same transaction: DELETE grants + INSERT revocations + audit
                                  │
   every service polls ───────────┘  GET /api/revocations?since=…   (every 60s)
                                  │
   client library merges into deny-list set ──▶ next request from that user: 401
```

Worst case exposure is 60 seconds. Three things shorten or bound it:

- deactivating a user also revokes every `sessions` row, so the shell logs them out at once
- new tokens stop being minted the instant the grant is gone
- disabling the Google account kills authentication upstream of all of this

For a genuine emergency there is `POST /api/admin/users/{id}/kill`, which additionally
writes a `jti`-level entry and drops `poll_after_seconds` to 5 for ten minutes — services
back off again automatically.

## Clock skew

Containers on one VPS share a clock, but a wrong clock breaks token validation in a way that
looks like a signature bug and wastes a day. `systemd-timesyncd` on the host, and the client
library allows 60 seconds of skew and logs a warning above 5 seconds.

## Key management

- RSA-2048 keypair generated at deploy, private key mounted as a file (not an env var — env vars leak into logs and crash reports)
- `kid` format `mmos-YYYY-MM`; rotate every 6 months
- rotation is overlapping: publish the new key in JWKS, wait one hour for caches to pick it up, then start signing with it, keep the old key published for 24 hours
- rotation is therefore zero-downtime, and a botched rotation is recoverable by reverting the signing key while both remain published
