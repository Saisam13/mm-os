-- MM OS — Postgres bootstrap.
--
-- Runs once, on first container start, as the POSTGRES_USER bootstrap superuser
-- (docker-entrypoint-initdb.d). One Postgres instance, one database and one login role
-- per service — isolated data, one engine to back up — per docs/01-architecture.md and
-- the A6 brief. Do not split this into per-service Postgres containers; the VPS cannot
-- spare the RAM for that.
--
-- deploy/docker-compose.yml sets POSTGRES_USER=mmos / POSTGRES_PASSWORD / POSTGRES_DB=mmos,
-- so the postgres image's own entrypoint already creates role `mmos` (as superuser) and
-- database `mmos` *before* this script runs. This file only adds what that bootstrap step
-- does not: the other three service databases and roles, and the read-only role.
--
-- Passwords below are placeholders. Whoever runs this against a real deployment must
-- replace every CHANGE_ME in a local, gitignored copy before first start — this file as
-- written contains no real secret, but the substituted result must never be committed.
-- See deploy/.env.example and deploy/COOLIFY.md.

-- ── pgcrypto on the database the bootstrap step already created ────────────────────
-- Matches backend/app/db.py's dev-path init_db(), which runs the same statement against
-- MMOS_DATABASE_URL for local dev and CI.
\connect mmos
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── one additional database + one login role per remaining service ─────────────────
CREATE ROLE servicedesk LOGIN PASSWORD 'CHANGE_ME_SERVICEDESK';
CREATE ROLE itemcode    LOGIN PASSWORD 'CHANGE_ME_ITEMCODE';
CREATE ROLE att         LOGIN PASSWORD 'CHANGE_ME_ATT';

CREATE DATABASE servicedesk OWNER servicedesk;
CREATE DATABASE itemcode    OWNER itemcode;
CREATE DATABASE att         OWNER att;

\connect servicedesk
CREATE EXTENSION IF NOT EXISTS pgcrypto;

\connect itemcode
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Item Code Studio: the dual-mode read-only role ──────────────────────────────────
-- Exactly the statements in docs/05-service-integration.md. Item Code Studio has a
-- public lookup endpoint and an admin console in the same app; this role is what holds
-- even when the application-level routing (the /api/admin/* prefix, the public_paths
-- allowlist) is wrong, because the database connection behind the public path has no
-- INSERT, UPDATE or DELETE grant at all.
CREATE ROLE itemcode_public LOGIN PASSWORD 'CHANGE_ME_ITEMCODE_PUBLIC';
GRANT CONNECT ON DATABASE itemcode TO itemcode_public;
GRANT USAGE ON SCHEMA public TO itemcode_public;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO itemcode_public;
ALTER DEFAULT PRIVILEGES FOR ROLE itemcode IN SCHEMA public
    GRANT SELECT ON TABLES TO itemcode_public;
-- FOR ROLE itemcode: default privileges are scoped to the role that will CREATE the
-- tables (itemcode, the owner role above), not to whoever runs this init script. Without
-- this clause, ALTER DEFAULT PRIVILEGES would apply to tables *this* session (the
-- bootstrap superuser) creates, which are not the ones Item Code Studio's own migrations
-- will produce, and the read-only grant would silently stop covering new tables.

\connect att
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- att has no public/admin split today (docs/08-v1-plan.md lists only Item Code Studio
-- for the dual-mode read-only role) so no *_public role is created here. If ATT grows a
-- public surface later, add its read-only role the same way, in this file.
