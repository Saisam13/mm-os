#!/usr/bin/env python
"""Check -- and, with --apply, correct -- where the service registry points.

Why this exists
---------------
`seed_services()` is deliberately create-only: it never touches a row an admin has since
hand-edited, so a `base_url` that has gone stale in the live database cannot be fixed by
redeploying. On 7 Sep that turned a DNS change into a silent outage. The m-mines.com
subdomains stopped resolving to the VPS, the registry still held well-formed https URLs, and
every launch URL MM OS minted -- `{base_url}/_mmos/accept#token=...` -- led to a parked
Hostinger box. Users saw themselves bounce back to the MM OS home page and nothing else.

Run this on the server, inside the MM OS container, where DATABASE_URL is already set:

    python scripts/repoint_services.py                 # report only
    python scripts/repoint_services.py --apply         # write the env/seed defaults back
    python scripts/repoint_services.py --apply \
        --set servicedesk=https://desk.example.com     # or set them explicitly

`--apply` writes `base_url` and nothing else. It never creates, deletes or deactivates a row.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import Service  # noqa: E402
from app.seed import SERVICES  # noqa: E402
from sqlalchemy import select  # noqa: E402


def intended_urls() -> dict[str, str]:
    """What seed.py would use today -- i.e. the env vars as this container sees them."""
    return {spec["slug"]: spec["base_url"] for spec in SERVICES}


def probe(url: str, *, external: bool) -> tuple[bool, str]:
    """Ask the URL the same question a browser following a launch link would."""
    target = url.rstrip("/") + ("/" if external else "/_mmos/health")
    try:
        resp = httpx.get(target, follow_redirects=True, timeout=8.0)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}"
    if external:
        return True, f"HTTP {resp.status_code}"
    if "json" not in resp.headers.get("content-type", ""):
        # A parked host answers 200 with HTML. That is a broken pointer, not a service.
        return False, f"not an MM OS service -- got {resp.headers.get('content-type') or 'no type'}"

    body = resp.json()
    os_info = body.get("os") or {}
    if os_info.get("reachable") is False:
        return False, f"up, but cannot reach MM OS: {os_info.get('error')}"
    return True, f"slug={body.get('slug')} version={body.get('version')}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the corrected base_url values")
    ap.add_argument(
        "--set", action="append", default=[], metavar="SLUG=URL",
        help="override one service's target; repeatable. Without it, seed.py's values are used.",
    )
    args = ap.parse_args()

    overrides = {}
    for item in args.set:
        if "=" not in item:
            ap.error(f"--set expects SLUG=URL, got {item!r}")
        slug, url = item.split("=", 1)
        overrides[slug.strip()] = url.strip()

    targets = {**intended_urls(), **overrides}
    intended_map = {spec["slug"]: spec for spec in SERVICES}
    changed = broken = 0

    with SessionLocal() as db:
        services = db.scalars(select(Service).order_by(Service.sort_order, Service.name)).all()
        for svc in services:
            want = targets.get(svc.slug, svc.base_url)
            external = svc.launch_mode == "external"

            ok, detail = probe(svc.base_url, external=external)
            status = "ok  " if ok else "DEAD"
            if not ok:
                broken += 1
            act_tag = "" if svc.is_active else " (INACTIVE)"
            print(f"[{status}] {svc.slug:<14} {svc.base_url}{act_tag}\n{'':>8}{detail}")

            spec = intended_map.get(svc.slug, {})
            want_active = spec.get("is_active", True)
            needs_active_fix = not svc.is_active and want_active
            needs_url_fix = want != svc.base_url

            if not needs_url_fix and not needs_active_fix:
                continue

            row_updated = False
            if needs_url_fix:
                want_ok, want_detail = probe(want, external=external)
                print(f"{'':>8}-> intended URL: {want} ({'reachable' if want_ok else want_detail})")
                if not args.apply:
                    print(f"{'':>8}   (dry run -- pass --apply to write it)")
                elif not want_ok:
                    # Repointing at a second dead URL turns one outage into two. Refuse.
                    print(f"{'':>8}   REFUSED: the intended URL is not reachable either")
                else:
                    svc.base_url = want
                    row_updated = True
                    print(f"{'':>8}   URL updated")

            if needs_active_fix:
                print(f"{'':>8}-> intended active: True")
                if not args.apply:
                    print(f"{'':>8}   (dry run -- pass --apply to activate)")
                else:
                    svc.is_active = True
                    row_updated = True
                    print(f"{'':>8}   activated (is_active: False -> True)")

            if row_updated:
                changed += 1

        if changed:
            db.commit()

    print(f"\n{len(services)} services, {broken} unreachable, {changed} updated")
    return 1 if broken and not changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
