#!/usr/bin/env python
"""One-shot fix: activate the Service Desk registry row and repoint its base_url.

Run this inside the MM OS container terminal (where DATABASE_URL is set):

    python /app/scripts/fix_servicedesk_db.py          # report only
    python /app/scripts/fix_servicedesk_db.py --apply  # write changes

Why this exists
---------------
The Service Desk was seeded with is_active=False (a placeholder during development).
GET /api/me and POST /api/token/service both filter on is_active=True, so an inactive
Service Desk is completely invisible to users -- they see no tile and the token mint
returns 403, causing the login loop.

This script is safe to run multiple times (idempotent).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import Service  # noqa: E402
from app.seed import SERVICEDESK_URL  # noqa: E402
from sqlalchemy import select  # noqa: E402


SERVICEDESK_SLUG = "servicedesk"


def probe_health(url: str) -> tuple[bool, str]:
    target = url.rstrip("/") + "/_mmos/health"
    try:
        resp = httpx.get(target, follow_redirects=True, timeout=8.0)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}"
    ct = resp.headers.get("content-type", "")
    if "json" not in ct:
        return False, f"not an MM OS service -- got {ct or 'no content-type'}"
    body = resp.json()
    os_info = body.get("os") or {}
    if os_info.get("reachable") is False:
        return False, f"up, but cannot reach MM OS: {os_info.get('error')}"
    return True, f"slug={body.get('slug')} version={body.get('version')}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the changes to the database")
    args = ap.parse_args()

    with SessionLocal() as db:
        svc = db.scalar(select(Service).where(Service.slug == SERVICEDESK_SLUG))
        if svc is None:
            print(f"[ERROR] No service row found for slug='{SERVICEDESK_SLUG}'")
            return 1

        print(f"\nService Desk registry row:")
        print(f"  slug:      {svc.slug}")
        print(f"  is_active: {svc.is_active}  {'(OK)' if svc.is_active else '(NEEDS FIX)'}")
        print(f"  base_url:  {svc.base_url}")

        intended = SERVICEDESK_URL
        url_changed = svc.base_url != intended
        active_changed = not svc.is_active

        if not active_changed and not url_changed:
            print("\n[OK] No changes needed.")
            return 0

        if active_changed:
            print(f"\n  -> Will activate (is_active: False -> True)")
        if url_changed:
            print(f"\n  -> Will repoint base_url:")
            print(f"       from: {svc.base_url}")
            print(f"         to: {intended}")
            ok, detail = probe_health(intended)
            print(f"     probe: {'reachable' if ok else 'UNREACHABLE: ' + detail}")
            if not ok:
                print("\n  [REFUSED] Intended URL is not reachable. Fix the deployment first.")
                return 1

        if not args.apply:
            print("\n(Dry run -- pass --apply to write changes)")
            return 0

        if active_changed:
            svc.is_active = True
        if url_changed:
            svc.base_url = intended
        db.commit()
        print("\n[DONE] Changes applied.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
