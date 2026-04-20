-- Rufus Edge - PostgreSQL Bootstrap Extensions
--
-- All table schema is managed by Alembic (src/ruvon/alembic/).
-- All seed data (roles, policies, rate limit rules, default config, command
-- versions) is inserted by the Alembic migration:
--   a1b2c3d4e5f6_consolidate_schema_add_missing_tables_v1.py
--
-- Usage:
--   1. This file runs automatically when the PostgreSQL container first
--      initialises (mounted as /docker-entrypoint-initdb.d/init-db.sql).
--      It creates the required extensions before schema creation.
--   2. Run Alembic to create all tables and seed data:
--        alembic upgrade head
--      Or via Docker Compose:
--        docker-compose run --rm ruvon-server alembic upgrade head

-- PostgreSQL extensions required before schema creation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";    -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";      -- trigram text search

DO $$
BEGIN
    RAISE NOTICE 'Rufus extensions initialised. Run: alembic upgrade head';
END $$;
