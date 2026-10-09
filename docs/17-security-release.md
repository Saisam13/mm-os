# MMOS 1.1.1 security and administration release

Version 1.1.1 aligns the administrator sign-in screen with the 1.1.0 server
policy: platform administrators use Google. User access retains employee PIN
sign-in. No additional database migration is required after schema 0010.

This release extends the existing People, Accounts, Departments, Grants,
Capabilities and Agents administration screens. It does not replace employee or
service databases.

Credential resets and login-email changes need `credentials.reset`; approval
authority changes need `people.authority`. Department-scoped administrators can
only act on their permitted people. Protected administrator changes require a
recent Google-authenticated session and preserve at least one active platform
administrator. Administrator PIN login is disabled. Recent Google authentication
alone does not establish MFA.

Permission and identity changes revoke affected sessions or service authority.
Explicit signed permission lists, including empty lists, remain authoritative.
Grants cannot outlive their delegation or target service authority. Development
or seed jobs must not restore intentionally revoked access.

MMOS adds `/admin/activity` and an authenticated, service-bound event collector.
Events retain stable actor subjects and readable name/employee-code snapshots;
ordinary database updates/deletes are blocked. Viewing activity needs
`activity.view`, with department scope applied before pagination. Private
business activity also needs `activity.private.view`. A database owner can bypass
local evidence protection, so external archives and operations controls remain
necessary.

## Updating an existing deployment

1. Preserve the current database, signing key, issuer, service keys and volume
   mappings. Back up and prove restoration before applying the new image.
2. Test the exact image and configuration. Set `MMOS_VERSION=1.1.1`, the real HTTPS
   `MMOS_PUBLIC_URL`, Secure cookies and actual trusted proxy peers. Uvicorn no
   longer trusts forwarded headers from arbitrary clients.
3. Apply `alembic upgrade head`: schema `0008 -> 0009 -> 0010`. Run
   `alembic check`. Keep demo seeding off. These migrations add session assurance
   metadata and central activity evidence.
4. Reauthenticate existing protected admins through Google. Test legitimate
   administration and denied cross-department/credential actions, normal service
   launch and activity visibility before reopening normal operations.
5. Preserve revocations and activity when rolling back. Prefer a corrective
   application release with additive schema retained; do not drop evidence tables
   or regenerate the signing key as a repair.

The standalone MMOS image does not deploy external service adapters. Each adapter
needs its own image/source reconciliation, catalog compatibility and rollout.
Service Desk and Samples also have separate migrations. Complete workflow,
browser/proxy, outage, backup, operating-control and independent audit acceptance
remain separate requirements; this release is not a compliance certificate.
