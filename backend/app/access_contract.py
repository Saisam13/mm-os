"""MM OS's side of the access contract `mmos-access/1` (docs/17-access-contract.md).

A service declares its permissions at `GET {base_url}/_mmos/manifest`; MM OS decides which
role holds which and who holds each role; the service enforces what the token says. This
module reads that manifest and answers two admin questions:

* Does the service follow the contract, and does its list match what MM OS holds?
  (`enforces` / `drift` / `no_manifest` / `unreachable`)
* What would a role file built from the service's own declaration look like? (a draft that
  goes through the ordinary dry-run import in app/roles_io.py, never straight to the DB)

Nothing here writes. The last result per service is kept in-process so Admin -> People
"view as" can show it without probing every service again; it is a hint, not a record.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import httpx

from .models import Service
from .roles_io import FORMAT as ROLE_FILE_FORMAT
from .security import sorted_keys_digest

CONTRACT = "mmos-access/1"
MANIFEST_PATH = "/_mmos/manifest"
FETCH_TIMEOUT_SECONDS = 5.0
_PERM_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")

ENFORCES = "enforces"
DRIFT = "drift"
NO_MANIFEST = "no_manifest"
UNREACHABLE = "unreachable"

# slug -> last check result (without the manifest body). Per worker; losing it only means
# "not checked yet".
_last: dict[str, dict] = {}


def catalog_hash(keys) -> str:
    """First 16 hex of SHA-256 over the sorted keys as compact JSON (spec §1)."""
    return sorted_keys_digest(list(keys))[:16]


class ManifestError(ValueError):
    pass


def parse_manifest(body, slug: str) -> dict:
    """Return the manifest normalised, or raise ManifestError saying what is wrong with it."""
    if not isinstance(body, dict):
        raise ManifestError("the manifest is not a JSON object")
    if body.get("contract") != CONTRACT:
        raise ManifestError(f"contract is {body.get('contract')!r}, not {CONTRACT!r}")
    if body.get("service") != slug:
        raise ManifestError(f"the manifest is for {body.get('service')!r}, not {slug!r}")
    perms = body.get("permissions")
    if not isinstance(perms, dict):
        raise ManifestError("permissions must be an object of {key: label}")
    bad = [str(k) for k in perms if not _PERM_RE.match(str(k))]
    if bad:
        raise ManifestError(f"permission keys not allowed by the contract: {', '.join(bad)}")
    if not all(isinstance(v, str) for v in perms.values()):
        raise ManifestError("every permission needs a text label")
    roles_in = body.get("suggested_roles", [])
    if not isinstance(roles_in, list):
        raise ManifestError("suggested_roles must be a list")
    roles = []
    for i, r in enumerate(roles_in):
        if not isinstance(r, dict) or not isinstance(r.get("key"), str) or not isinstance(r.get("name"), str):
            raise ManifestError(f"suggested_roles[{i}] needs a key and a name")
        rp = r.get("permissions", [])
        if not isinstance(rp, list) or not all(isinstance(p, str) for p in rp):
            raise ManifestError(f"suggested role {r['key']!r} permissions must be a list of keys")
        unknown = [p for p in rp if p not in perms]
        if unknown:
            raise ManifestError(f"suggested role {r['key']!r} lists undeclared permissions: {', '.join(unknown)}")
        roles.append({"key": r["key"], "name": r["name"], "permissions": list(dict.fromkeys(rp))})
    expected = catalog_hash(perms)
    if body.get("catalog_hash") != expected:
        raise ManifestError(f"catalog_hash {body.get('catalog_hash')!r} does not match its permissions ({expected})")
    return {"contract": CONTRACT, "service": slug, "permissions": dict(perms),
            "suggested_roles": roles, "catalog_hash": expected}


async def fetch_manifest(http: httpx.AsyncClient, base_url: str, slug: str) -> tuple[str, dict | None, str | None]:
    """(status, manifest, detail). status is NO_MANIFEST, UNREACHABLE, or "ok"."""
    url = base_url.rstrip("/") + MANIFEST_PATH
    try:
        resp = await http.get(url)
    except Exception as exc:  # noqa: BLE001 - a check reports, it never raises
        return UNREACHABLE, None, f"{type(exc).__name__}: {exc}"
    if resp.status_code >= 500:
        return UNREACHABLE, None, f"HTTP {resp.status_code}"
    if resp.status_code >= 400:
        return NO_MANIFEST, None, f"HTTP {resp.status_code}"
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return NO_MANIFEST, None, "the answer was not JSON"
    try:
        return "ok", parse_manifest(body, slug), None
    except ManifestError as e:
        return NO_MANIFEST, None, str(e)


def compare(stored_catalog: dict | None, manifest: dict) -> dict:
    stored = set((stored_catalog or {}).keys())
    declared = set(manifest["permissions"].keys())
    added, removed = sorted(declared - stored), sorted(stored - declared)
    return {"status": ENFORCES if not added and not removed else DRIFT, "added": added, "removed": removed}


def _svc(s: Service) -> dict:
    return {"slug": s.slug, "name": s.name, "base_url": s.base_url,
            "permission_catalog": dict(s.permission_catalog or {})}


async def _check_one(http: httpx.AsyncClient, svc: dict) -> tuple[dict, dict | None]:
    status, manifest, detail = await fetch_manifest(http, svc["base_url"], svc["slug"])
    out = {"slug": svc["slug"], "name": svc["name"], "status": status, "detail": detail,
           "added": [], "removed": [], "catalog_hash": None,
           "checked_at": datetime.now(timezone.utc).isoformat()}
    if manifest is not None:
        out.update(compare(svc["permission_catalog"], manifest), catalog_hash=manifest["catalog_hash"])
    _last[svc["slug"]] = out
    return out, manifest


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS)


async def check_service(service: Service) -> tuple[dict, dict | None]:
    """(result, manifest or None). Reads the row before awaiting, so the sync session is not
    held across the network call."""
    svc = _svc(service)
    async with _client() as http:
        return await _check_one(http, svc)


async def check_services(services: list[Service]) -> list[dict]:
    svcs = [_svc(s) for s in services]
    async with _client() as http:
        results = await asyncio.gather(*(_check_one(http, s) for s in svcs))
    return [r for r, _ in results]


def last_result(slug: str) -> dict | None:
    return _last.get(slug)


# ── import from service ───────────────────────────────────────────────────────
def draft_role_file(service: Service, manifest: dict) -> tuple[dict, list[str]]:
    """A role file built from the service's manifest, for the ordinary dry-run import.

    The permission list and the suggested roles come from the service. Roles MM OS already
    has keep their name, meaning and default flag; roles the manifest does not list are kept
    (in their current place in the order) with any permission the service no longer declares
    dropped. `remove_unlisted` is false and there is no `assign`: nobody's grant changes."""
    catalog = manifest["permissions"]
    existing = sorted(service.roles, key=lambda r: r.sort_order)
    by_key = {r.key: r for r in existing}
    notes: list[str] = []

    roles: list[dict] = []
    for sr in manifest["suggested_roles"]:
        cur = by_key.get(sr["key"])
        roles.append({
            "key": sr["key"],
            "name": cur.name if cur else sr["name"],
            "description": cur.description if cur else None,
            "default": bool(cur and cur.is_default),
            "permissions": list(sr["permissions"]),
        })
    suggested = {r["key"] for r in roles}

    for idx, r in enumerate(existing):
        if r.key in suggested:
            continue
        kept = [p for p in (r.permissions or []) if p in catalog]
        dropped = [p for p in (r.permissions or []) if p not in catalog]
        pos = 0
        for prev in reversed(existing[:idx]):
            j = next((i for i, x in enumerate(roles) if x["key"] == prev.key), None)
            if j is not None:
                pos = j + 1
                break
        roles.insert(pos, {"key": r.key, "name": r.name, "description": r.description,
                           "default": r.is_default, "permissions": kept})
        if not kept:
            notes.append(f"Role {r.key!r} is not in {service.name}'s list and none of its permissions "
                         "exist there any more. Give it permissions, or move its people onto another "
                         "role with 'replaces', before applying.")
        elif dropped:
            notes.append(f"Role {r.key!r} is kept but loses {', '.join(dropped)}, which {service.name} "
                         "no longer declares.")
        else:
            notes.append(f"Role {r.key!r} is kept: MM OS has it, {service.name} does not suggest it.")

    return {
        "format": ROLE_FILE_FORMAT,
        "service": service.slug,
        "permissions": dict(catalog),
        "roles": roles,
        "remove_unlisted": False,
    }, notes
