"""Service Desk settings. Own service, own env contract — see docs/05-service-integration.md.

Reads env vars with the SERVICEDESK_ / MMOS_ / SMTP_ prefixes used across MM OS services.
Nothing here touches the MM OS database: DATABASE_URL points at the servicedesk database
(or a local sqlite file for dev/test), never at `mmos`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    version: str = "0.1.0"
    environment: str = "development"

    # Own database. Portable URL — sqlite for local/dev/test, postgres in production,
    # unchanged code either way because app/models.py uses only portable SQLAlchemy types.
    database_url: str = "sqlite:///./servicedesk.db"

    # MM OS integration (docs/05-service-integration.md).
    mmos_os_url: str = "https://os.m-mines.com"
    mmos_service_slug: str = "servicedesk"
    mmos_service_key: str = ""
    mmos_issuer: str = "https://os.m-mines.com"

    # Auth verification mode for the seam in app/mmos_seam.py.
    #   "http"  — verify real RS256 tokens against MM OS's published JWKS (production)
    #   "stub"  — decode a local dev/test token (no MM OS instance reachable) — see
    #             app/mmos_seam.py and `## Assumptions` in handoff/a5-servicedesk.md
    auth_mode: str = "stub"
    dev_secret: str = "servicedesk-dev-only-not-a-real-secret"

    # Org chart lookup (approver computation) — see app/org_chart.py.
    #   "http" — call the assumed MM OS org-chain endpoint (does not exist yet, see
    #            `## Contract objections`)
    #   "seed" — a tiny in-memory fixture, used until that endpoint lands
    org_chart_mode: str = "seed"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notifications_enabled: bool = True


@lru_cache
def settings() -> Settings:
    return Settings()
