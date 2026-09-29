"""CORS for the MM OS bar (packages/embed/embed.js).

Every service page loads `{os}/embed.js`, which asks `GET {os}/api/me` — with the MM OS
session cookie — who is signed in. That request comes from the service's own origin
(po.m-mines.in, not m-mines.in), and MM OS never answered it with CORS headers, so the
browser withheld the response and the bar said "Not signed in to MM OS" on every service,
for everyone, always.

Scope is deliberately narrow:
- only `GET /api/me` — the bar's service switcher already falls back to the service's own
  launch flow when it cannot mint a token cross-origin, so token minting stays same-origin;
- only https origins under `MMOS_COOKIE_DOMAIN`, i.e. exactly the hosts the session cookie is
  already sent to. With no cookie domain (local, tests) nothing is allowed.

It is a simple request (GET, no custom headers), so there is no preflight to answer.
"""
from __future__ import annotations

import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

EMBED_PATHS = ("/api/me",)


def allowed_origin(origin: str | None, cookie_domain: str) -> bool:
    domain = cookie_domain.strip().lstrip(".").lower()
    if not origin or not domain:
        return False
    return re.fullmatch(r"https://([a-z0-9-]+\.)*" + re.escape(domain), origin.lower()) is not None


class EmbedCors(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method == "GET" and request.url.path in EMBED_PATHS:
            origin = request.headers.get("origin")
            if allowed_origin(origin, settings().cookie_domain):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        return response
