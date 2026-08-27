"""Password Manager settings. Own service, own env contract — mirrors servicedesk/app/config.py
and docs/05-service-integration.md's shape.

THIS SERVICE IS A SHELL. It has no database and stores no secrets of any kind — see
SECURITY.md for what a real vault implementation would still need before it may ever hold a
real credential. `database_url` exists only so a future run can add tables without another
config pass; nothing in app/ writes to it yet.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    version: str = "0.1.0"
    environment: str = "development"

    # Reserved for a future vault schema. Unused today — this shell creates no tables and
    # stores no secrets. Own database if/when it exists, never the MM OS one.
    database_url: str = "sqlite:///./passwordmanager.db"

    # MM OS integration (docs/05-service-integration.md).
    mmos_os_url: str = "https://os.m-mines.com"
    mmos_service_slug: str = "passwordmanager"
    mmos_service_key: str = ""
    mmos_issuer: str = "https://os.m-mines.com"

    # Auth verification mode for the seam in app/mmos_seam.py.
    #   "http"  — verify real RS256 tokens against MM OS's published JWKS (production)
    #   "stub"  — decode a local dev/test token (no MM OS instance reachable) — local
    #             dev/tests only, never production. See app/main.py's boot guard.
    auth_mode: str = "stub"
    dev_secret: str = "passwordmanager-dev-only-not-a-real-secret"


@lru_cache
def settings() -> Settings:
    return Settings()
