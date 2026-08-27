"""Item Code Studio settings. Own service, own env contract — mirrors servicedesk/app/config.py
exactly (see docs/05-service-integration.md). This is a SHELL: item-code generation/registry
logic does not exist yet, only the MM OS auth seam and a placeholder page.

Nothing here touches the MM OS database or any other service's database: DATABASE_URL points
at the itemcode database (or a local sqlite file for dev/test), never at `mmos` or
`servicedesk`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    version: str = "0.1.0"
    environment: str = "development"

    # Own database. Portable URL — sqlite for local/dev/test, postgres in production.
    database_url: str = "sqlite:///./itemcode.db"

    # MM OS integration (docs/05-service-integration.md).
    mmos_os_url: str = "https://os.m-mines.com"
    mmos_service_slug: str = "itemcode"
    mmos_service_key: str = ""
    mmos_issuer: str = "https://os.m-mines.com"

    # Auth verification mode for the seam in app/mmos_seam.py.
    #   "http"  — verify real RS256 tokens against MM OS's published JWKS (production)
    #   "stub"  — decode a local dev/test token (no MM OS instance reachable). Local dev
    #             and tests only — see app/main.py's boot guard.
    auth_mode: str = "stub"
    dev_secret: str = "itemcode-dev-only-not-a-real-secret"


@lru_cache
def settings() -> Settings:
    return Settings()
