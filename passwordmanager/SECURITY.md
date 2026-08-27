# Security design notes — read before this service ever holds a real secret

**Current state: this service stores no secrets. There is no vault, no encryption, no
credential table, no autofill, and no sharing mechanism anywhere in this codebase.**
`GET /api/me` returns `vault: {"status": "not_implemented"}` deliberately, so nothing
downstream can mistake this shell for a working product. Do not wire up a credentials
table, a "save password" form, or a browser extension against this service until every
item below has an actual answer, reviewed by someone other than the person who wrote the
code.

This document exists so the gap between "authenticated shell" and "safe to hold a real
password" is never silently assumed to be smaller than it is.

## Why this is hard, and why "just add a table" is not an answer

A password manager's core threat is not "can a stranger log in" — MM OS's SSO handoff
already answers that reasonably well for this shell. The core threat is: **can the people
who operate this server, or anyone who compromises it, read what's inside it.** A normal
CRUD service (like Service Desk) is fine with "the database holds the data in the clear
and the app server can read it — access control is the whole story." A password manager
cannot be fine with that. If `passwordmanager`'s database or app server is ever breached,
every stored credential must still be unreadable without something the server never
had.

## Requirements before any real secret storage exists

1. **Zero-knowledge design.** The server must never see a plaintext credential, and
   ideally never see the encryption key either. Encryption/decryption happens client-side;
   the server stores and returns opaque ciphertext blobs. This is the single biggest
   architectural decision and it must be made *before* any schema exists — retrofitting it
   onto a server-side-plaintext design later means a full data migration and re-encryption
   of every stored secret, in the best case, or a breach disclosure in the worst.

2. **Per-user key derivation, not a shared server secret.** Each user's vault key must be
   derived from something only that user has (a master passphrase, a hardware key, or —
   given the Google-account tie-in the product owner described — a key wrapped by a secret
   only derivable client-side from the user's authenticated session, never from a value
   the server can reconstruct on its own). A single service-wide encryption key defeats
   the point: one compromised key would decrypt everyone's vault at once.

3. **Strong, modern KDF and cipher choices**, e.g. Argon2id (or scrypt) for key
   derivation from a passphrase, AES-256-GCM or XChaCha20-Poly1305 for the ciphertext, with
   authenticated encryption (not just confidentiality — tampering must be detectable).
   Never roll a custom scheme; use audited libraries.

4. **Key recovery story that doesn't reintroduce a backdoor.** "Forgot my master
   passphrase" is the hardest UX problem in this space precisely because a real answer
   (zero-knowledge) means MM OS *cannot* reset it for the user the way it resets a PIN
   today (`backend/app/routers/auth.py`'s PIN reset flow). Any recovery mechanism (recovery
   codes, admin-assisted re-encryption with the user's cooperation, etc.) must be designed
   explicitly, not bolted on as an afterthought that quietly gives the server plaintext
   access "just for this one case."

5. **Audit logging of every access**, separate from the encrypted payload itself — who
   requested which vault entry's ciphertext and when, even though the server can't read the
   contents. This is what makes a breach detectable and a legal/compliance story possible.

6. **A written threat model** covering at minimum: a compromised app server, a compromised
   database backup, a malicious or coerced admin, a compromised client device, token replay
   / session hijack via the existing MM OS seam, and what happens to previously-issued
   tokens on employee offboarding (this shell already has the deny-list mechanic in
   `app/mmos_seam.py` — a real vault needs to also confirm offboarding actually revokes
   vault *access*, not just this service's session).

7. **Transport and storage hardening**: TLS everywhere (already assumed for MM OS
   generally), encryption at rest for the database volume as defense in depth (not a
   substitute for #1-#3), and secrets-in-transit never logged (check
   `app/notifications.py`-style logging patterns elsewhere in this repo for what NOT to
   do if a payload might ever contain sensitive data).

8. **Rate limiting and lockout** on any endpoint that takes a passphrase or unlocks a
   vault, to blunt offline/online brute-force attempts against #3's KDF.

9. **Autofill / browser-extension trust boundary**, if that's still the plan: an extension
   that reads a page's origin and only offers credentials matching it (avoiding
   cross-origin credential leakage), and a clear answer for how the extension authenticates
   to this service without ever handling the master key in a way the extension's own
   process (which is far more exposed than a server) could exfiltrate.

## How this would relate to MM OS's existing Google-link flow

`backend/app/routers/auth.py` already has a self-service "link your Google account" flow
(`GET /google/link/start`) that attaches a verified Google identity to an existing MM OS
account — separate from login, and accepting any verified Google account including personal
Gmail. The product idea described to this agent — linking a vault to the user's Google
account so stored credentials can be used on external sites — is a different problem from
that flow and should not casually reuse it:

- The existing link flow's job is *identity* ("this MM OS user also owns this Google
  address"). A vault-unlock flow's job would be *key material* ("derive or unwrap this
  user's vault key using something tied to their Google session") — a much stronger
  requirement. Simply checking "is this user's Google account linked" before serving
  decrypted secrets would violate requirement #1 above, because it implies the server can
  decrypt on its own once identity is confirmed.
- If a future design wants to use Google as one factor in key derivation (e.g. WebAuthn/
  passkey-backed unlock, or an OAuth token used client-side only to unwrap a locally-held
  key), that needs its own design doc and its own review — it is not something this shell
  attempts, and it should not be inferred from the existence of the link flow.
- Any reuse of Google sign-in for this product should go through the same `hd`/
  verified-email checks `auth.py` already enforces for MM OS login, but that only ever
  established identity, never secret-handling. Treat it as a separate control from
  day one.

## What remains before this is a real product

Everything in the numbered list above, an actual vault schema, a client-side crypto
implementation, a security review by someone who didn't write the code, and a decision on
recovery UX. None of it exists in this repository today.
