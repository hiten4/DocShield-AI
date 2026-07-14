-- Runs automatically on FIRST database init (docker-entrypoint-initdb.d).
-- For an existing pgdata volume, run this once manually:
--   docker compose exec postgres psql -U befree -d befree -f /docker-entrypoint-initdb.d/01_app_role.sql
--
-- WHY THIS EXISTS: the postgres image creates POSTGRES_USER (befree) as a
-- SUPERUSER, and superusers bypass row-level security entirely — even with
-- FORCE ROW LEVEL SECURITY. The app must connect as this non-superuser,
-- non-BYPASSRLS role or tenant isolation at the Postgres layer is OFF.

-- pgcrypto needs superuser; create it here so migrations running as the
-- app role can no-op on CREATE EXTENSION IF NOT EXISTS.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'befree_app') THEN
        CREATE ROLE befree_app LOGIN PASSWORD 'befree_app' NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE befree TO befree_app;
GRANT USAGE, CREATE ON SCHEMA public TO befree_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO befree_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO befree_app;

-- Cover tables created later by the befree (superuser) role, e.g. via psql.
ALTER DEFAULT PRIVILEGES FOR ROLE befree IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO befree_app;
ALTER DEFAULT PRIVILEGES FOR ROLE befree IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO befree_app;
