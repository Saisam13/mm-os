"""Session endpoints -- Google OIDC (login + self-service linking) and PIN login, logout.
Owned by A1 (Identity).

Owner ruling, 24 Aug 2026 (handoff/ORCHESTRATOR.md "Owner decisions taken mid-run"), which
modifies the locked docs/04-auth-flow.md "Google Workspace OIDC, locked to hd=m-mines.com"
decision:

  * All 73 employees get a local PIN account on import, corporate addresses included.
    Employee-code + PIN is the universal day-one path; nobody waits on a mailbox.
  * Google sign-in is open to ANY address, personal gmail.com included.
  * A link-your-Google-account flow attaches a verified Google identity to the
    CURRENTLY AUTHENTICATED user only, never resolved from anything in the callback.
    login_email is set, auth_type flips to 'google', and pin_hash is kept so PIN
    login keeps working.
  * hd == google_hosted_domain is enforced only for auto-provisioning -- a Google
    identity that does not match any existing user's login_email must still be a
    corporate account, so a stranger cannot manufacture themselves an account. An
    identity that DOES match an existing user's login_email (because it was linked from
    an authenticated session) is accepted regardless of domain.

See handoff/a1-identity.md ## Deviations and ## Assumptions for the full reasoning.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..db import get_db
from ..deps import audit, client_ip, current_session, current_user
from ..models import Employee, Session, User
from ..security import new_session_token, session_expiry, verify_pin

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

OAUTH_COOKIE_NAME = "mmos_oauth"
OAUTH_COOKIE_TTL_SECONDS = 600  # 10 minutes -- long enough for a Google round trip

# Same generic message for every login failure, PIN or Google, wrong code or wrong PIN or
# locked -- never gives an attacker a signal about which part was wrong.
GENERIC_PIN_ERROR = {"error": "invalid_credentials", "message": "Incorrect employee code or PIN."}


# -- rate limit: per-IP PIN attempts (B3 security review, HIGH finding) -----------------
# Employee codes are guessable (MM + digits) and the per-user lockout in pin_login() only
# protects ONE account at a time -- without this, a single attacker could walk every
# employee code with junk PINs and lock all 73 accounts out of MM OS within seconds. This
# mirrors routers/tokens.py's in-process sliding-window limiter (60/min) exactly, rather
# than inventing a second rate-limiting mechanism: same window, same style, same
# limitation (in-process/in-memory, void across multiple workers or replicas -- B3
# recorded that as a MEDIUM finding for the deployment; see handoff ## Assumptions). It is
# a separate table keyed by IP (pre-authentication), not by user id like tokens.py's.
_PIN_RATE_LIMIT = 60
_PIN_RATE_WINDOW_SECONDS = 60.0
_pin_hits: dict[str, deque[float]] = defaultdict(deque)


def _pin_rate_limited(key: str) -> bool:
    now = time.monotonic()
    bucket = _pin_hits[key]
    while bucket and now - bucket[0] > _PIN_RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _PIN_RATE_LIMIT:
        return True
    bucket.append(now)
    return False


# -- the oauth state+PKCE cookie ---------------------------------------------
# No signing/session library is in requirements.txt, so this is hand-rolled HMAC over the
# mounted RSA signing key file's bytes (a secret already provisioned for us, shared across
# every worker process since it is the one thing Coolify mounts identically everywhere --
# see docs/04-auth-flow.md "Key management"). This never touches app/security.py.
def _oauth_secret() -> bytes:
    path = settings().signing_key_path
    if path.exists():
        return path.read_bytes()
    return b"mmos-dev-oauth-secret"  # only reachable if security.py has not run yet


def _sign_oauth_cookie(payload: str) -> str:
    mac = hashlib.sha256(_oauth_secret() + payload.encode()).hexdigest()
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + mac


def _read_oauth_cookie(raw: str) -> dict | None:
    try:
        body_b64, mac = raw.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(body_b64.encode()).decode()
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return None
    expected = hashlib.sha256(_oauth_secret() + payload.encode()).hexdigest()
    if not secrets.compare_digest(mac, expected):
        return None
    return dict(parse_qsl(payload))


def _make_oauth_cookie(
    *, state: str, code_verifier: str, next_path: str, purpose: str = "login", linking_user_id=None
) -> str:
    exp = int(time.time()) + OAUTH_COOKIE_TTL_SECONDS
    fields = {
        "state": state,
        "code_verifier": code_verifier,
        "next": next_path,
        "exp": str(exp),
        "purpose": purpose,
    }
    if linking_user_id is not None:
        fields["uid"] = str(linking_user_id)
    return _sign_oauth_cookie(urlencode(fields))


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:64]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _safe_next(next_: str | None) -> str:
    """Only ever redirect somewhere inside our own shell -- never an open redirect."""
    if next_ and next_.startswith("/") and not next_.startswith("//"):
        return next_
    return "/"


# -- cookies (session + oauth state) -----------------------------------------
def _cookie_kwargs(*, max_age: int) -> dict:
    cfg = settings()
    kwargs = dict(
        httponly=True,
        secure=cfg.cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    # An empty MMOS_COOKIE_DOMAIN (as in tests) must not become an explicit empty Domain=
    # attribute -- that would target no host at all and the cookie would never come back.
    if cfg.cookie_domain:
        kwargs["domain"] = cfg.cookie_domain
    return kwargs


def _set_session_cookie(response, raw_token: str) -> None:
    cfg = settings()
    response.set_cookie(cfg.cookie_name, raw_token, **_cookie_kwargs(max_age=cfg.session_ttl_hours * 3600))


def _clear_session_cookie(response) -> None:
    cfg = settings()
    response.delete_cookie(cfg.cookie_name, path="/", domain=cfg.cookie_domain or None)


def _set_oauth_cookie(response, value: str) -> None:
    response.set_cookie(OAUTH_COOKIE_NAME, value, **_cookie_kwargs(max_age=OAUTH_COOKIE_TTL_SECONDS))


def _clear_oauth_cookie(response) -> None:
    response.delete_cookie(OAUTH_COOKIE_NAME, path="/", domain=settings().cookie_domain or None)


def _issue_session(db: OrmSession, user: User, request: Request) -> str:
    raw, token_hash = new_session_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=token_hash,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            expires_at=session_expiry(),
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    return raw


class _AuthDenied(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


# -- Google OIDC: login -------------------------------------------------------
@router.get("/google/start")
def google_start(request: Request, next: str = "/"):
    cfg = settings()
    next_path = _safe_next(next)
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = _pkce_pair()

    params = {
        "client_id": cfg.google_client_id,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "hd": cfg.google_hosted_domain,  # convenience hint only -- the id_token claim decides
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    cookie_val = _make_oauth_cookie(state=state, code_verifier=code_verifier, next_path=next_path, purpose="login")
    _set_oauth_cookie(resp, cookie_val)
    return resp


# -- Google OIDC: self-service account linking --------------------------------
@router.get("/google/link/start")
def google_link_start(request: Request, next: str = "/", user: User = Depends(current_user)):
    """Requires an already-authenticated session (PIN or Google). Deliberately sends no
    hd hint -- linking accepts any verified Google account, personal ones included."""
    cfg = settings()
    next_path = _safe_next(next)
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = _pkce_pair()

    params = {
        "client_id": cfg.google_client_id,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    cookie_val = _make_oauth_cookie(
        state=state, code_verifier=code_verifier, next_path=next_path, purpose="link", linking_user_id=user.id
    )
    _set_oauth_cookie(resp, cookie_val)
    return resp


def _fetch_google_claims(code: str, code_verifier: str) -> dict:
    """Exchange the code, then verify the id_token's signature and the claims that hold
    regardless of purpose: aud/iss/exp (via jwt.decode) and email_verified.

    hd is deliberately NOT checked here -- the caller decides whether it applies (see
    _complete_google_login vs _complete_google_link).

    Both network calls go through module-level httpx.post / httpx.get so tests can
    monkeypatch them at that boundary -- no live Google calls happen in the test suite.
    """
    cfg = settings()
    token_resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": cfg.google_client_id,
            "client_secret": cfg.google_client_secret,
            "redirect_uri": cfg.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        timeout=10,
    )
    if token_resp.status_code != 200:
        raise _AuthDenied("token_exchange_failed", "Could not sign in with Google.")
    id_token = token_resp.json().get("id_token")
    if not id_token:
        raise _AuthDenied("token_exchange_failed", "Could not sign in with Google.")

    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError:
        raise _AuthDenied("invalid_token", "Could not verify Google sign-in.")

    jwks_resp = httpx.get(GOOGLE_JWKS_URL, timeout=10)
    if jwks_resp.status_code != 200:
        raise _AuthDenied("invalid_token", "Could not verify Google sign-in.")
    key = next((k for k in jwks_resp.json().get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise _AuthDenied("invalid_token", "Could not verify Google sign-in.")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=cfg.google_client_id,
            issuer=list(GOOGLE_ISSUERS),
            options={"leeway": cfg.clock_skew_seconds},
        )
    except JWTError:
        raise _AuthDenied("invalid_token", "Could not verify Google sign-in.")

    # aud, iss, exp are enforced by jwt.decode above.
    if not claims.get("email_verified"):
        raise _AuthDenied("email_not_verified", "Your Google email is not verified.")
    return claims


def _complete_google_login(request: Request, db: OrmSession, fields: dict, claims: dict, ip: str):
    """Plain (unauthenticated) Google sign-in. MM OS never auto-provisions an account on
    login (docs/04) -- this branch only ever finds an existing user or fails. hd is
    enforced here, but only when no existing user's login_email already matches: a
    personal address that has been linked from an authenticated session (see
    _complete_google_link) is looked up and accepted the same as a corporate one.
    """
    cfg = settings()
    email = claims.get("email")
    user = db.scalar(select(User).where(User.login_email == email)) if email else None

    if user is None:
        # Nobody has this exact email linked. Since we never auto-provision, this always
        # ends in unknown_user -- but hd is checked first so a non-corporate identity is
        # rejected distinctly (hd_mismatch), matching the original architecture decision
        # and its acceptance test.
        if claims.get("hd") != cfg.google_hosted_domain:
            audit(db, action="login.google.denied", ip=ip, reason="hd_mismatch")
            db.commit()
            raise HTTPException(401, {"error": "hd_mismatch", "message": "Sign in with your MiniMines Google account."})
        audit(db, action="login.google.denied", ip=ip, reason="unknown_user", email=email)
        db.commit()
        raise HTTPException(401, {"error": "unknown_user", "message": "No MM OS account for this email."})

    if not user.is_active:
        # Same generic signal as "no such email" -- never confirms a deactivated account exists.
        audit(db, action="login.google.denied", ip=ip, reason="unknown_user", email=email)
        db.commit()
        raise HTTPException(401, {"error": "unknown_user", "message": "No MM OS account for this email."})

    raw = _issue_session(db, user, request)
    audit(db, action="login.google", actor_user_id=user.id, ip=ip)
    db.commit()

    resp = RedirectResponse(_safe_next(fields.get("next")), status_code=302)
    _set_session_cookie(resp, raw)
    _clear_oauth_cookie(resp)
    return resp


def _complete_google_link(request: Request, db: OrmSession, fields: dict, claims: dict, ip: str):
    """Attach a verified Google identity to the CURRENTLY AUTHENTICATED user only. The
    target user is resolved from the live mmos_session cookie -- never from the claims,
    never from anything the client sent in this request. That is what makes accepting a
    personal address safe: the person already proved control of the MM OS account with
    their PIN, and is now proving control of the Google account on top of that.
    """
    try:
        sess = current_session(request, db)
        user = current_user(sess, db)
    except HTTPException:
        audit(db, action="login.google.denied", ip=ip, reason="link_session_expired")
        db.commit()
        raise HTTPException(401, {"error": "link_session_expired", "message": "Sign in again before linking Google."})

    if fields.get("uid") != str(user.id):
        # The signed-in session changed between /link/start and this callback. Abort
        # rather than silently linking to whoever happens to be signed in now.
        audit(db, action="login.google.denied", actor_user_id=user.id, ip=ip, reason="link_session_mismatch")
        db.commit()
        raise HTTPException(409, {"error": "link_session_mismatch", "message": "Sign-in changed mid-flow. Please try linking again."})

    email = claims.get("email")
    other = db.scalar(select(User).where(User.login_email == email, User.id != user.id))
    if other is not None:
        # Deliberately generic: must not confirm or deny whose account it is already on.
        audit(db, action="login.google.denied", actor_user_id=user.id, ip=ip, reason="already_linked")
        db.commit()
        raise HTTPException(409, {"error": "google_account_already_linked", "message": "This Google account is already linked to a different MM OS user."})

    user.login_email = email
    user.auth_type = "google"  # pin_hash is left untouched -- PIN login keeps working
    audit(db, action="login.google.linked", actor_user_id=user.id, ip=ip)
    db.commit()

    resp = RedirectResponse(_safe_next(fields.get("next")), status_code=302)
    _clear_oauth_cookie(resp)
    return resp


@router.get("/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, db: OrmSession = Depends(get_db)):
    ip = client_ip(request)
    raw_cookie = request.cookies.get(OAUTH_COOKIE_NAME)
    fields = _read_oauth_cookie(raw_cookie) if raw_cookie else None

    if not fields or not code or not state or fields.get("state") != state or int(fields.get("exp", 0)) < time.time():
        audit(db, action="login.google.denied", ip=ip, reason="bad_state")
        db.commit()
        raise HTTPException(401, {"error": "invalid_state", "message": "Sign-in expired. Please try again."})

    try:
        claims = _fetch_google_claims(code, fields["code_verifier"])
    except _AuthDenied as exc:
        audit(db, action="login.google.denied", ip=ip, reason=exc.code)
        db.commit()
        raise HTTPException(401, {"error": exc.code, "message": exc.message})

    if fields.get("purpose") == "link":
        return _complete_google_link(request, db, fields, claims, ip)
    return _complete_google_login(request, db, fields, claims, ip)


# -- PIN login ----------------------------------------------------------------
@router.post("/pin")
def pin_login(request: Request, body: dict, db: OrmSession = Depends(get_db)):
    cfg = settings()
    ip = client_ip(request)

    # Checked before ANY lookup or attempt-counting: a throttled request must never touch
    # a user's failed_pin_attempts, or the throttle just slows the same account-lockout
    # attack down instead of closing it, and it must never distinguish a valid employee
    # code from an invalid one (no DB query has happened yet either way). No audit write
    # here either, deliberately matching routers/tokens.py's limiter: once a caller is
    # over budget, every further request in the same window would otherwise still cost a
    # DB insert + commit, turning the fix itself into a write-amplification DoS vector.
    if _pin_rate_limited(ip):
        raise HTTPException(429, {"error": "rate_limited", "message": "Too many PIN attempts from this network. Try again shortly."})

    employee_code = str(body.get("employee_code") or "").strip()
    pin = str(body.get("pin") or "")

    user = db.scalar(
        select(User).join(Employee, User.employee_id == Employee.id).where(Employee.employee_code == employee_code)
    )
    if user is None:
        audit(db, action="login.pin.failed", ip=ip, reason="unknown_code", employee_code=employee_code)
        db.commit()
        raise HTTPException(401, GENERIC_PIN_ERROR)

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until <= now:
        user.failed_pin_attempts = 0
        user.locked_until = None

    if user.locked_until and user.locked_until > now:
        audit(db, action="login.pin.failed", actor_user_id=user.id, ip=ip, reason="locked")
        db.commit()
        raise HTTPException(401, GENERIC_PIN_ERROR)

    # Keyed off pin_hash being present and correct -- not auth_type == 'local_pin'. A
    # user who has linked Google (auth_type flips to 'google') keeps pin_hash, and PIN
    # login must keep working for them (owner ruling, see module docstring). We don't
    # additionally gate on pin_set_at here: that field is only the admin UI's "has IT
    # issued a real PIN yet" signal (see routers/people.py), not a login precondition --
    # an unissued PIN is an unguessable placeholder hash that verify_pin() will already
    # never match against anything a person actually types.
    ok = bool(user.is_active and user.pin_hash and verify_pin(pin, user.pin_hash))
    if not ok:
        user.failed_pin_attempts += 1
        if user.failed_pin_attempts >= cfg.pin_max_attempts:
            user.locked_until = now + timedelta(minutes=cfg.pin_lockout_minutes)
        audit(db, action="login.pin.failed", actor_user_id=user.id, ip=ip)
        db.commit()
        raise HTTPException(401, GENERIC_PIN_ERROR)

    user.failed_pin_attempts = 0
    user.locked_until = None
    raw = _issue_session(db, user, request)
    audit(db, action="login.pin", actor_user_id=user.id, ip=ip)
    db.commit()

    resp = JSONResponse({"ok": True})
    _set_session_cookie(resp, raw)
    return resp


# -- logout --------------------------------------------------------------------
@router.post("/logout")
def logout(request: Request, sess: Session = Depends(current_session), db: OrmSession = Depends(get_db)):
    sess.revoked_at = datetime.now(timezone.utc)
    audit(db, action="logout", actor_user_id=sess.user_id, ip=client_ip(request))
    db.commit()

    resp = JSONResponse({"ok": True})
    _clear_session_cookie(resp)
    return resp
