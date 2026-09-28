# Agent context: identity administration

Read `docs/14-identity-administration.md` before changing People, Agents, Departments,
Roles/Capabilities, Service Grants, provisioning, or revocation behavior.

Invariants:

1. People (`Employee` + `User`) and machine identities (`AgentIdentity`) are separate types,
   endpoints, pages, grants, and credential boundaries.
2. New people reference an existing active `Department`; keep `hr_department` synchronized only
   for backward compatibility.
3. Validate every requested service-role pair before writing. Person creation is one transaction.
4. Authorization comes from the verified session and explicit `UserCapability` records. Never
   accept an audit actor or authority flag from a request body.
5. No operation may leave MM OS without an active platform administrator.
6. Grant removal and role replacement must write `Revocation` in the same transaction.
7. Seed/import paths may add missing records but never recreate intentionally revoked grants.
8. Never serialize `pin_hash`, `service_key_hash`, `credential_hash`, signing keys, or raw tokens.

Compatibility: existing `employees.hr_department`, `users.is_platform_admin`, single-grant API,
and API response `role` fields remain supported while new clients use department IDs, explicit
capabilities, multiple grants, and the `roles` token claim.
