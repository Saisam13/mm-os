"""JWKS cache: refreshed on an unknown kid, at most once a minute.

A slow-but-safe design on purpose. If MM OS is unreachable the last known key set is kept —
signature verification then fails closed for a genuinely new key, but does not thrash the
network on every request from an attacker cycling `kid` values, and does not stop verifying
tokens signed with the key it already has.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

logger = logging.getLogger("mmos_client.jwks")


class JWKSCache:
    def __init__(self, jwks_url: str, *, http_client: httpx.Client, min_refresh_seconds: int = 60, state_store=None):
        self._url = jwks_url
        self._client = http_client
        self._min_refresh = min_refresh_seconds
        self._keys: dict[str, dict] = {}
        self._last_fetch = 0.0
        self._lock = threading.Lock()
        self._store = state_store
        self._last_success = 0.0
        if self._store:
            saved = self._store.read("jwks")
            if type(saved.get("fetched_at")) in (int, float) and 0 <= time.time() - saved["fetched_at"] <= 86400:
                keys = saved.get("keys", [])
                self._keys = {k["kid"]: k for k in keys if isinstance(k, dict) and isinstance(k.get("kid"), str)} if isinstance(keys, list) else {}
                self._last_success = saved["fetched_at"]

    def get_key(self, kid: str) -> dict | None:
        with self._lock:
            if (time.time() - self._last_success >= 300 or kid not in self._keys) and self._can_refetch():
                self._fetch_locked()
            if kid in self._keys and 0 <= time.time() - self._last_success <= 86400:
                return self._keys[kid]
            return None

    def _can_refetch(self) -> bool:
        return (time.monotonic() - self._last_fetch) >= self._min_refresh

    def _fetch_locked(self) -> None:
        self._last_fetch = time.monotonic()
        try:
            resp = self._client.get(self._url, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            self._keys = {k["kid"]: k for k in data.get("keys", []) if "kid" in k}
            self._last_success = time.time()
            if self._store:
                self._store.write("jwks", {"fetched_at": self._last_success, "keys": list(self._keys.values())})
        except Exception as exc:  # noqa: BLE001 — degrade, never raise into a request path
            logger.warning("mmos: JWKS fetch from %s failed, keeping cached keys (%s)", self._url, exc)

    def force_refresh(self) -> None:
        """Test/ops hook: bypass the rate limit once."""
        with self._lock:
            self._last_fetch = 0.0
            self._fetch_locked()
