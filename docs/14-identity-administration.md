# Identity and access administration

## Current-state assessment (before this change)

The implemented product had separate `employees` and `users`, but administration exposed a
hard-coded department filter, free-text department editing, a spreadsheet-oriented creation
path, and one `is_platform_admin` switch. A grant's uniqueness constraint allowed only one role
per person/service. People had no combined employee/login/grants transaction. Machine identities
had no separate administrative model or page. The API allowed an administrator to remove the
last platform administrator, and the UI offered deactivation for every user. Bulk grants committed
immediately without a preview. The deny-list path for existing grant removal was already sound.

## Target model now implemented

MM OS remains the source of truth for its human directory and grants:

- `departments` is the controlled list. `employees.department_id` is authoritative for new
  writes; `hr_department` remains a compatibility snapshot for existing consumers.
- `employees.onboarding_ref` is an optional unique link to an HR onboarding record. MM OS does
  not copy or become the HR database.
- `grants` is unique by user, service, and role, so a human can hold multiple independent roles
  in a service. `origin` records how a grant arrived.
- `user_capabilities` contains explicit delegated administration rights, optionally scoped to a
  department. Platform admins implicitly hold all capabilities.
- `agent_identities` is a separate machine-identity boundary. It has no employee/user foreign key
  and cannot receive human service grants. Credential hashes are never serialized.

Capabilities are `people.view`, `people.create`, `people.edit`, `departments.assign`,
`grants.view`, `grants.add`, `grants.change`, `grants.revoke`, `agents.manage`,
`admin_roles.manage`, and `hr_onboarding.create`. A delegated role administrator may delegate
only capabilities they already possess; an IT Admin may delegate any approved capability.

## Primary workflows

`POST /api/admin/people` validates the controlled department, duplicate employee code/email/
onboarding link, every service, and every service-role pair before writing. The employee, login,
grants, and audit records then commit in one database transaction. HR onboarding delegates must
supply an onboarding reference and stay inside their configured department scope.

`POST /api/admin/grants/batch` adds multiple service/role selections in one transaction. With
`replace: true` it replaces a service's role set, emits a service-scoped revocation, and records
the change. `DELETE /api/admin/grants/{id}` revokes one role without deleting the person.
Deactivation remains distinct and emits a global subject revocation.

`POST /api/admin/grants/bulk` accepts `preview: true` and returns the exact create/skip counts
without writing. Commit recomputes selection and validation server-side. The spreadsheet importer
uses the same unique identity constraints and controlled department records; it never deletes a
person or restores a grant.

## IT Admin protection

There is no person/user delete endpoint. The People UI suppresses normal deactivation for an IT
Admin. The API rejects deactivation or platform-role removal when it would leave no active IT
Admin and audits the attempt as `admin.protected_attempt`. Completed role changes are audited as
`admin.role_change`.

## Deployment

1. Back up the MM OS database using `scripts/backup.sh` and record the current image tag.
2. Build and test the API and frontend.
3. Run `alembic upgrade head`. Migration `0002` creates controlled departments from existing
   employee values, links existing employees, preserves every record, and widens grant uniqueness.
4. Deploy the new image, then verify `/healthz`, `/api/me`, People, Service grants, and token issue.
5. Do not run the seed as a repair job: seed creates missing registry data but must never be used
   to recreate intentionally revoked grants.

## Rollback

Prefer application rollback with the `0002` schema left in place; the older application ignores
the additive tables/columns. A database downgrade is lossy when a user has multiple roles in one
service, because `0001` can represent only one. If a schema rollback is mandatory, export grants
and audit first, choose the role to preserve for each person/service, run `alembic downgrade 0001`,
then restore the prior image. Restore the pre-migration database backup if any downgrade check
fails.

## Production gates and residual risks

- Run migration upgrade and rollback rehearsal against a Postgres 16 clone; local automated tests
  use SQLite and do not prove Postgres DDL.
- Confirm at least two active IT Admins before normal operations.
- Confirm service consumers accept a JWT `roles` array containing more than one value.
- Exercise revocation polling between separately running processes to re-prove the 60-second SLA.
- The HR system integration currently stores an opaque reference; live onboarding lookup/prefill
  needs an authorized HR API and is intentionally not simulated.
- Bulk spreadsheet import establishes previously unseen department values during migration/import;
  routine individual editing can select only an existing active department.
