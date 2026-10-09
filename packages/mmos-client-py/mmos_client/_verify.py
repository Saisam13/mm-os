"""Token verification, in the exact order docs/04-auth-flow.md specifies:

    1. kid in header resolves against cached JWKS (refetch on miss, at most once a minute)
    2. RS256 signature valid
    3. iss == configured MM OS issuer
    4. aud == this service slug
    5. exp / iat within 60s clock skew
    6. sub / jti not in the deny-list
    7. roles (left as-is on the returned claims; the service maps them itself)

`alg` is checked explicitly against "RS256" before anything else touches the token, so the
header can never pick the algorithm (the classic alg-confusion hole).

Any failure raises TokenError with a short machine-readable reason and never leaks token
contents — callers turn that into a 401 with no further detail.
"""
from __future__ import annotations

import time
import math

import jwt
from jwt.exceptions import PyJWTError as JOSEError


class TokenError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def verify_token(
    token: str,
    *,
    jwks_cache,
    issuer: str,
    audience: str,
    skew_seconds: int,
    denylist,
) -> dict:
    if not token or not isinstance(token, str):
        raise TokenError("missing_token")

    # 0/1 — header, alg, kid
    try:
        header = jwt.get_unverified_header(token)
    except JOSEError:
        raise TokenError("malformed_token")

    alg = header.get("alg")
    if alg != "RS256":
        # Never let the token header choose the algorithm.
        raise TokenError("alg_not_allowed")

    kid = header.get("kid")
    if not kid:
        raise TokenError("missing_kid")

    key = jwks_cache.get_key(kid)
    if key is None:
        raise TokenError("unknown_kid")

    # 2 — signature only; claim checks are done by hand below so each failure is
    # distinguishable (and so the ordering in docs/04 is the ordering here).
    try:
        claims = jwt.decode(
            token,
            jwt.PyJWK.from_dict(key, algorithm="RS256"),
            algorithms=["RS256"],
            options={
                "verify_aud": False,
                "verify_iss": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
                "verify_sub": False,
                "verify_jti": False,
            },
        )
    except (JOSEError, ValueError, TypeError):
        raise TokenError("bad_signature")

    # 3 — iss
    if claims.get("iss") != issuer:
        raise TokenError("bad_issuer")

    # 4 — aud (a perfectly signed token for another service is rejected here)
    if claims.get("aud") != audience:
        raise TokenError("bad_audience")

    # 5 — exp / iat with skew
    now = time.time()
    exp = claims.get("exp")
    iat = claims.get("iat")
    nbf = claims.get("nbf", iat)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (exp, iat, nbf)):
        raise TokenError("invalid_time_claims")
    if now > exp + skew_seconds:
        raise TokenError("expired")
    if exp <= iat or exp - iat > 900:
        raise TokenError("invalid_token_lifetime")
    if not isinstance(claims.get("sub"), str) or not claims["sub"] or not isinstance(claims.get("jti"), str) or not claims["jti"]:
        raise TokenError("invalid_identity_claims")
    for field in ("roles", "permissions"):
        value = claims.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise TokenError("invalid_authority_claims")
    if max(iat, nbf) > now + skew_seconds:
        raise TokenError("not_yet_valid")

    # 6 — deny-list (sub or jti)
    sub = claims.get("sub")
    jti = claims.get("jti")
    iat = claims.get("iat")
    if denylist.is_revoked(sub=sub, jti=jti, iat=iat if isinstance(iat, (int, float)) else None):
        raise TokenError("revoked")

    # 7 — roles: returned on the claims as-is; require_role() does the mapping.
    return claims
