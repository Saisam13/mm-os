"""Heartbeat loop: liveness, LLM control-plane visibility, kill-switch pickup.

`report_usage()` accumulates in memory; a successful heartbeat ships and clears the
counters, a failed one leaves them for the next attempt — losing MM OS costs counters,
never requests. `llm_guard()` only ever reads the cached flag, so it never makes a network
call on the request path.
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading

import httpx

logger = logging.getLogger("mmos_client.heartbeat")


class UsageAccumulator:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests = 0
        self._input_tokens = 0
        self._output_tokens = 0

    def add(self, *, requests: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            self._requests += requests
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "day": _dt.datetime.now(_dt.timezone.utc).date().isoformat(),
                "requests": self._requests,
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
            }

    def clear(self) -> None:
        with self._lock:
            self._requests = 0
            self._input_tokens = 0
            self._output_tokens = 0


class Heartbeat:
    def __init__(
        self,
        *,
        http_client: httpx.Client,
        service_key: str,
        version: str,
        usage: UsageAccumulator,
        llm_provider: str | None,
        llm_model: str | None,
        llm_key_present: bool,
        interval_seconds: int = 300,
        # Availability rule (documented as an assumption in the handoff): assume the LLM
        # gate is open until MM OS says otherwise, since a control-plane restart must not
        # silently 503 every LLM route in the company before the first heartbeat lands.
        initial_llm_enabled: bool = True,
    ):
        self._client = http_client
        self._service_key = service_key
        self._version = version
        self._usage = usage
        self._llm_provider = llm_provider
        self._llm_model = llm_model
        self._llm_key_present = llm_key_present
        self._interval = interval_seconds
        self.llm_enabled = initial_llm_enabled
        self.config_version: int | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _payload(self) -> dict:
        body: dict = {"version": self._version}
        if self._llm_provider:
            body["llm"] = {
                "provider": self._llm_provider,
                "model": self._llm_model,
                "key_present": self._llm_key_present,
                "enabled": self.llm_enabled,
            }
        usage = self._usage.snapshot()
        if usage["requests"] or usage["input_tokens"] or usage["output_tokens"]:
            body["usage"] = usage
        return body

    def beat_once(self) -> bool:
        """Returns True on success. Call directly in tests instead of waiting 5 minutes."""
        try:
            resp = self._client.post(
                "/api/agent/heartbeat",
                json=self._payload(),
                headers={"Authorization": f"Bearer {self._service_key}"},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self.llm_enabled = bool(data.get("llm_enabled", self.llm_enabled))
            self.config_version = data.get("config_version", self.config_version)
            self._usage.clear()
            return True
        except Exception as exc:  # noqa: BLE001 — degrade, never raise
            logger.warning("mmos: heartbeat failed, cached llm_enabled=%s kept (%s)", self.llm_enabled, exc)
            return False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="mmos-heartbeat")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.beat_once()
            self._stop.wait(self._interval)
