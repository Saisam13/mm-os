"""Configuration. Everything comes from the environment; nothing is hardcoded.

The signing key is read from a mounted FILE, not an env var, because env vars leak into
logs, crash reports and `docker inspect`.
"""
from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MMOS_", extra="ignore")

    # ── identity of this deployment ───────────────────────────────────────
    issuer: str = "https://os.m-mines.com"
    environment: str = "production"
    version: str = "1.0.0"

    # ── database ──────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://mmos:mmos@localhost:5432/mmos"

    # ── network posture (see docs/06-network-security.md) ─────────────────
    network_mode: str = "private"                 # private | public
    allowed_cidrs: str = "10.8.0.0/24,127.0.0.1/32"
    trusted_proxy_count: int = 1

    # ── Google Workspace OIDC ─────────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    google_hosted_domain: str = "m-mines.com"
    google_redirect_path: str = "/api/auth/google/callback"

    # ── tokens ────────────────────────────────────────────────────────────
    signing_key_path: Path = Path("/run/secrets/mmos_signing_key.pem")
    signing_key_id: str = "mmos-2026-08"
    service_token_ttl_seconds: int = 900          # 15 minutes
    session_ttl_hours: int = 12
    session_max_days: int = 7
    clock_skew_seconds: int = 60
    revocation_poll_seconds: int = 60

    # ── cookies ───────────────────────────────────────────────────────────
    cookie_name: str = "mmos_session"
    cookie_domain: str = ".m-mines.com"
    cookie_secure: bool = True

    # ── PIN login ─────────────────────────────────────────────────────────
    pin_max_attempts: int = 5
    pin_lockout_minutes: int = 15

    @field_validator("network_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("private", "public"):
            raise ValueError("network_mode must be 'private' or 'public'")
        return v

    @property
    def cidrs(self) -> list:
        return [ip_network(c.strip()) for c in self.allowed_cidrs.split(",") if c.strip()]

    @property
    def redirect_uri(self) -> str:
        return self.issuer.rstrip("/") + self.google_redirect_path


@lru_cache
def settings() -> Settings:
    return Settings()
