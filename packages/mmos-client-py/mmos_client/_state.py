"""Atomic local trust-state storage. Mount outside web roots, writable only by the service.

Contains public verification keys and revocation metadata, never credentials or JWTs.
The directory is an operator-controlled trust boundary, not an arbitrary request path.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("mmos_client.state")


class StateStore:
    def __init__(self, directory: str | Path, namespace: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt" and self.directory.stat().st_mode & 0o022:
            raise ValueError("MMOS trust cache directory must not be group/world writable")
        self.prefix = namespace

    def read(self, kind: str) -> dict:
        try:
            path = self.directory / f"{self.prefix}-{kind}.json"
            if path.stat().st_size > 2_000_000:
                raise ValueError("trust state is too large")
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("mmos: ignoring invalid local %s trust state", kind)
            return {}

    def write(self, kind: str, value: dict) -> None:
        scratch = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False) as handle:
                scratch = Path(handle.name)
                os.chmod(scratch, 0o600)
                json.dump(value, handle, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(scratch, self.directory / f"{self.prefix}-{kind}.json")
        except (OSError, ValueError):
            logger.error("mmos: could not persist %s trust state", kind)
        finally:
            if scratch is not None:
                scratch.unlink(missing_ok=True)
