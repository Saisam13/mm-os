# MM OS access contract — `mmos-access/1`

Owner-approved 30 Sep 2026 (D-2026-09-30-1). One sentence: **the service declares its
permissions, MM OS decides which role holds which and who holds each role, and the service
enforces exactly what the token says — on the server and in its screens.**

## 1. The service declares: `GET /_mmos/manifest`

Public (no auth), JSON, no personal data:

```json
{
  "contract": "mmos-access/1",
  "service": "<slug>",
  "permissions": { "<key>": "<plain label>", "...": "..." },
  "suggested_roles": [
    { "key": "viewer", "name": "Viewer", "permissions": ["view"] }
  ],
  "catalog_hash": "<16 hex>"
}
```

- `permissions`: every key the service's code checks. Keys match `^[a-z][a-z0-9_.:-]{0,63}$`.
- `suggested_roles`: lowest first. MM OS starts from these on import; the service uses them as
  its fallback (§3) while tokens carry no `permissions`.
- `catalog_hash` = first 16 hex chars of SHA-256 over the **sorted** keys serialised as compact
  JSON: JS `JSON.stringify(keys.sort())`, Python
  `json.dumps(sorted(keys), separators=(",", ":"))`. Example: `["edit","setup","view"]`.

## 2. MM OS decides

Admin → Roles is the only place role → permission is edited; grants and the people sheet the
only places person → role is. Every service token carries `roles`, `permissions` (the union for
the person's roles on that service) and `pv` (first 12 hex of SHA-256 over the sorted
permission list, same serialisation as above). Changing a role's permissions or a person's
grant revokes the affected sessions (deny-list, time-aware: only tokens with `iat` ≤ the
revocation are refused).

## 3. The service enforces

- **Effective permissions** = the token's `permissions` if non-empty (unknown keys dropped),
  else the union of `suggested_roles[].permissions` for the token's `roles`.
- Server checks **permission keys, never role names**.
- A service with a local session stores the effective permissions (and `pv`) at handoff and
  honours the deny-list on every request.
- **Record scope stays in the service** (a department head's department, a rep's own leads, a
  Spoke route). MM OS may supply inputs (`dept`), the rule lives with the data.

## 4. Screens follow the same set

The server hands the effective permissions to the UI. Three states per control:

| State | Treatment |
|---|---|
| Allowed | shown, working |
| Everyday action not allowed | shown, disabled, reason on hover/screen reader: "Needs the <Role> role in <Service>. Ask IT to change your role in MM OS." One page-level notice for view-only people instead of per-row text. |
| Admin/setup area not allowed | hidden, with one line saying who manages it |

The server check stays authoritative.

## 5. Local role editors

While MM OS is configured, a service's own role/permission editor is **read-only**, labelled
"Managed in MM OS". Standalone installs and break-glass password logins keep the local scheme.

## Reference implementation

Project Module (`project-purchase-analytics`): `src/auth/permissions.ts`,
`app/_components/access.tsx`, `app/mmos/manifest/route.ts` — commits be96931, 9ed3c1f.
