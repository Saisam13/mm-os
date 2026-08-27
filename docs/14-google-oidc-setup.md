# 14 · Google OIDC setup (INT-4 prep)

The exact click-by-click steps to create the Google OAuth client MM OS signs in against, plus
the env vars to set and how to test. Written for the owner to run in the Google Cloud Console
once; nobody should have to reverse-engineer it from the code later.

Everything here is **verified against `backend/app/routers/auth.py`** as built — the redirect
path, scopes and claim checks below are what the code actually does, not what a generic OIDC
tutorial would say. Where the two differ, the code wins and this doc follows it.

## Where this fits

- **PIN is the only live login this phase.** Google OIDC is fully built and tested but is not
  the primary path yet (product-owner decision, `handoff/c1-sso.md`). This guide is *prep*: do
  it when you are ready to turn Google sign-in on, not as a launch blocker.
- Google sign-in in MM OS is **open to any Google address** (personal `gmail.com` included),
  but authenticating with Google is **not** the same as having an account — a Google identity
  only signs in if its verified email already matches an existing MM OS user's `login_email`.
  MM OS never auto-provisions an account from a Google login. See `docs/04-auth-flow.md` and
  `handoff/a1-identity.md`.
- Employees attach their Google identity themselves via the self-service link flow
  (`GET /api/auth/google/link/start`, requires an authenticated PIN session first). IT cannot
  pre-link on someone's behalf. So the day-1 order is: issue PIN → employee signs in with PIN →
  employee links Google. The OAuth client below serves **both** the login and the link flows —
  they share one registered redirect URI (Google only allows one callback per client, and the
  code branches internally on a signed cookie, not on the URI).

## What the code requires (read before clicking)

From `backend/app/routers/auth.py` and `backend/app/config.py`:

| Thing | Value | Source in code |
|---|---|---|
| Authorized redirect URI | `MMOS_ISSUER` + `MMOS_GOOGLE_REDIRECT_PATH` | `config.py::redirect_uri` (`issuer.rstrip('/') + google_redirect_path`) |
| Default redirect path | `/api/auth/google/callback` | `config.py` default `google_redirect_path` |
| Scopes | `openid email profile` | `auth.py::google_start` / `google_link_start` `scope=` |
| Response type | `code` (Authorization Code + PKCE, `S256`) | `auth.py::google_start` |
| `aud` the id_token must carry | your OAuth **client ID** | `_fetch_google_claims` `audience=cfg.google_client_id` |
| Accepted issuers | `accounts.google.com` / `https://accounts.google.com` | `auth.py::GOOGLE_ISSUERS` |
| Extra claim required | `email_verified == true` | `_fetch_google_claims` |
| `hd` (hosted domain) | hint on the authorize URL **and** gate for auto-provisioning only | `google_start` `hd=`, `_complete_google_login` |

So for a production issuer of `https://os.m-mines.com`, the **one redirect URI to register** is:

```
https://os.m-mines.com/api/auth/google/callback
```

If `MMOS_ISSUER` is anything else (a staging host, an sslip.io URL during transition), the
redirect URI is that host + `/api/auth/google/callback`. It must match byte-for-byte — Google
rejects a mismatch, including a trailing slash or http-vs-https difference.

## Step 1 · Pick / create the Google Cloud project

1. Go to <https://console.cloud.google.com/> signed in as a **Workspace admin** for
   `m-mines.com`.
2. Project picker (top bar) → **New Project** (or reuse an existing MiniMines project).
   - Name: `MiniMines MM OS` (or similar).
   - Organization / Location: the `m-mines.com` organization.
3. **Create**, then make sure the project picker shows this project before continuing.

## Step 2 · OAuth consent screen — Internal

1. Left nav → **APIs & Services → OAuth consent screen** (newer consoles: **Google Auth
   Platform → Branding / Audience**).
2. **User type: Internal.** This is the important choice — Internal means only `m-mines.com`
   Workspace accounts can go through this client, and it needs no Google verification review.
   (Personal `gmail.com` sign-in that MM OS's *code* allows applies to the **link** flow for
   already-provisioned users; the consent screen being Internal is still correct for a Workspace
   deployment. If you later need personal accounts to complete OAuth at the Google layer too,
   that is a separate decision to switch to External + verification — not needed for launch.)
3. App information:
   - App name: `MM OS`
   - User support email: `itadmin@m-mines.com`
   - App logo: optional.
4. App domain (optional but tidy): Application home page `https://os.m-mines.com`.
5. Authorized domain: add `m-mines.com`.
6. Developer contact information: `itadmin@m-mines.com`.
7. **Save and continue.**

## Step 3 · Scopes

1. On the **Scopes** step → **Add or remove scopes**.
2. Select exactly these three and nothing more:
   - `openid`
   - `.../auth/userinfo.email`  (shows as **email**)
   - `.../auth/userinfo.profile` (shows as **profile**)
   These correspond to the code's `scope="openid email profile"`. Do not add Gmail, Drive, or
   any other API scope — MM OS reads only the id_token's `email` / `email_verified` / `hd` /
   `name` claims and never calls another Google API.
3. **Update → Save and continue** to the end, then **Back to dashboard**.

## Step 4 · Create the OAuth client ID

1. Left nav → **APIs & Services → Credentials**.
2. **+ Create credentials → OAuth client ID.**
3. **Application type: Web application.**
4. Name: `MM OS web`.
5. **Authorized JavaScript origins:** not required — MM OS does the OAuth dance server-side
   (server redirect + server-side code exchange), so there is no browser-side Google JS call.
   Leave it empty.
6. **Authorized redirect URIs → + Add URI**, and enter the callback exactly:
   ```
   https://os.m-mines.com/api/auth/google/callback
   ```
   (Substitute your real `MMOS_ISSUER` host if different — see "What the code requires" above.)
   If you run a separate staging deployment with its own issuer, add that host's
   `/api/auth/google/callback` as a second URI here too.
7. **Create.**
8. A dialog shows the **Client ID** and **Client secret**. Copy both now — the secret is shown
   in full here; you can retrieve the client ID again later but treat the secret like any other
   credential (store it in the password manager / Coolify env, never in git or chat).

## Step 5 · Set the env vars

Put these in Coolify's environment for the `mmos` app (or `deploy/.env` for a bare-metal run —
never commit `deploy/.env`). They map to `backend/app/config.py` fields with the `MMOS_` prefix:

```bash
MMOS_GOOGLE_CLIENT_ID=<the client ID from step 4>
MMOS_GOOGLE_CLIENT_SECRET=<the client secret from step 4>
MMOS_GOOGLE_HOSTED_DOMAIN=m-mines.com
```

Leave `MMOS_GOOGLE_REDIRECT_PATH` unset unless you deliberately change the callback path — its
default `/api/auth/google/callback` is what step 4's URI must match. Confirm `MMOS_ISSUER` is
already the real HTTPS host (it forms the first half of the redirect URI). Redeploy / restart
the `mmos` container so the new env is read (`settings()` is read once at process start).

## Step 6 · Test it

There are no Google credentials in the repo and no live Google call in the test suite — the
suite fakes the token exchange at the `httpx` boundary (`backend/tests/test_identity.py`). So
testing the *real* client is a live check, done once after step 5:

1. **Sanity — the authorize redirect is well-formed.** From a machine that can reach MM OS,
   open in a browser (or curl and read the `Location` header):
   ```
   https://os.m-mines.com/api/auth/google/start
   ```
   You should be 302-redirected to `accounts.google.com/o/oauth2/v2/auth?...` with
   `client_id=<yours>`, `redirect_uri=https://os.m-mines.com/api/auth/google/callback`,
   `scope=openid email profile`, `code_challenge=...`, `code_challenge_method=S256`,
   `hd=m-mines.com`. If `client_id` is blank, the env var did not load — recheck step 5 and
   that the container restarted.
2. **A real end-to-end link (the intended day-1 path).** As a provisioned employee:
   sign in with employee code + PIN, then from the profile page choose **Link Google account**
   (hits `GET /api/auth/google/link/start`, which requires that PIN session). Complete Google
   sign-in with the corporate account. On success `users.login_email` is set, `auth_type` flips
   to `google`, and `pin_hash` is kept so PIN login still works. Check the audit log shows
   `login.google.linked`.
3. **A real login.** Sign out, then use **Sign in with Google** for that same account
   (`/api/auth/google/start` → Google → callback). It should land you signed in, with a
   `login.google` audit row.
4. **Negative check — an unlinked stranger is refused.** Signing in with a Google account whose
   email matches no MM OS `login_email` must fail: a non-`m-mines.com` address gets
   `401 hd_mismatch`; an `m-mines.com` address that simply is not provisioned gets
   `401 unknown_user`. Either way no account is created — MM OS never auto-provisions from a
   Google login. (These two branches are the ones `test_identity.py` covers offline; step 4 just
   confirms the real client behaves the same.)

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `redirect_uri_mismatch` on the Google screen | The URI in step 4 does not byte-match `MMOS_ISSUER + /api/auth/google/callback` | Fix the registered URI (trailing slash, http vs https, wrong host) |
| Redirect to Google has blank `client_id` | Env var not loaded | Set `MMOS_GOOGLE_CLIENT_ID` and restart the container |
| `401 invalid_state` at the callback | The 10-minute oauth-state cookie expired or was dropped | Retry the flow; ensure cookies work over the deployed HTTPS host |
| `401 email_not_verified` | The Google account's email is unverified | Use a verified account; MM OS requires `email_verified` |
| Every corporate login is `unknown_user` | Users exist but have never linked Google (no `login_email` set) | Have them link first (step 6.2), or expect PIN-only until they do |

## Related

- `docs/04-auth-flow.md` — the login/link/callback flow and the verification order.
- `handoff/a1-identity.md` — why the `hd` check is conditional and why matching is on email.
- `deploy/.env.production.example` — where these three env vars sit in the full prod contract.
- `deploy/COOLIFY.md` §5 — Coolify-specific env entry (if that section predates this doc, this
  doc is the authoritative click-by-click).
