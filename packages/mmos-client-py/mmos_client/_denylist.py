"""In-memory deny-list, merged from GET {os_url}/api/agent/revocations?since=.

Availability rule from the brief: if MM OS is unreachable, keep the last known list and keep
serving. A 15-minute token plus a firewall is an acceptable risk; logging the whole company
out because the control plane restarted is not.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

logger = logging.getLogger("mmos_client.denylist")


class DenyList:
    def __init__(self):
        self._subs: set[str] = set()
        self._jtis: set[str] = set()
        self._since: str | None = None
        self._lock = threading.Lock()

    def is_revoked(self, *, sub: str | None, jti: str | None) -> bool:
        with self._lock:
            return (sub is not None and sub in self._subs) or (jti is not None and jti in self._jtis)

    def merge(self, *, revoked_subjects: list[dict], revoked_jti: list, now: str) -> None:
        with self._lock:
            for row in revoked_subjects or []:
                s = row.get("sub") if isinstance(row, dict) else row
                if s:
                    self._subs.add(s)
            for row in revoked_jti or []:
                j = row.get("jti") if isinstance(row, dict) else row
                if j:
                    self._jtis.add(j)
            self._since = now

    @property
    def since(self) -> str | None:
        return self._since

    def snapshot(self) -> tuple[set, set]:
        with self._lock:
            return set(self._subs), set(self._jtis)


class DenyListPoller:
    """Polls /api/agent/revocations. Call `poll_once()` directly in tests instead of waiting
    on the background thread — the thread just calls the same method on a timer.

    B1 note (see handoff/b1-assembly.md ## Seams fixed): this used to poll the bare
    `/api/revocations` path from docs/03-api-contract.md's example, but the real router
    (backend/app/main.py, frozen) mounts `routers/agent.py` at `/api/agent`, so the
    documented path 404s. A2 flagged this in handoff/a2-tokens.md's Contract objections;
    this is the fix, on the client side, since main.py's mount prefix is the one the whole
    app already depends on (heartbeat, config) and is not worth re-prefixing."""

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        service_key: str,
        denylist: DenyList,
        default_interval_seconds: int = 60,
    ):
        self._client = http_client
        self._service_key = service_key
        self._denylist = denylist
        self._default_interval = default_interval_seconds
        self._next_interval = default_interval_seconds
        self._since = "1970-01-01T00:00:00Z"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def next_interval_seconds(self) -> int:
        return self._next_interval

    def poll_once(self) -> bool:
        """Returns True on a successful poll, False if MM OS was unreachable (deny-list is
        left untouched either way, per the availability rule)."""
        try:
            resp = self._client.get(
                "/api/agent/revocations",
                params={"since": self._since},
                headers={"Authorization": f"Bearer {self._service_key}"},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self._denylist.merge(
                revoked_subjects=data.get("revoked_subjects", []),
                revoked_jti=data.get("revoked_jti", []),
                now=data.get("now", self._since),
            )
            self._since = data.get("now", self._since)
            self._next_interval = int(data.get("poll_after_seconds", self._default_interval))
            return True
        except Exception as exc:  # noqa: BLE001 — degrade, never raise
            logger.warning("mmos: revocation poll failed, keeping last known deny-list (%s)", exc)
            self._next_interval = self._default_interval
            return False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="mmos-denylist-poller")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._next_interval)
