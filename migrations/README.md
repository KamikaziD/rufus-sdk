# Database Migrations

This directory contains database schema definitions and migrations for Rufus SDK.

## Overview

Rufus uses a **unified schema definition** approach to maintain feature parity across multiple databases (PostgreSQL and SQLite) while handling database-specific differences automatically.

## Files

### Schema Definition

- **`schema.yaml`** - Single source of truth for database schema
  - Database-agnostic table and column definitions
  - Type mappings for PostgreSQL and SQLite
  - Indexes, triggers, views, and constraints
  - Current version: 1.0.0

### Generated Migrations

These files are **automatically generated** from `schema.yaml` and should not be edited directly:

- **`002_postgres_standardized.sql`** - PostgreSQL migration (271 lines)
  - Uses UUID, JSONB, TIMESTAMPTZ
  - PostgreSQL triggers and functions
  - LISTEN/NOTIFY support

- **`002_sqlite_initial.sql`** - SQLite migration (223 lines)
  - Type conversions (UUID→TEXT, JSONB→TEXT)
  - SQLite-compatible triggers
  - Optimized for embedded usage

### Legacy Files

- **`confucius/migrations/001_init_postgresql_schema.sql`** - Original PostgreSQL schema
  - Reference implementation
  - Used for validation

## Workflow

### 1. Modify Schema

Edit `schema.yaml` to add/modify tables, columns, indexes, etc.

```yaml
tables:
  my_new_table:
    description: "My new table"
    columns:
      - name: id
        type: uuid
        primary_key: true
        default:
          postgres: "gen_random_uuid()"
          sqlite: "lower(hex(randomblob(16)))"

      - name: name
        type: varchar
        size: 100
        nullable: false
```

### 2. Generate Migrations

```bash
# Generate both PostgreSQL and SQLite migrations
python tools/compile_schema.py --all

# Or generate specific database
python tools/compile_schema.py --target postgres --output migrations/003_my_changes.sql
```

### 3. Validate

```bash
# Validate generated schema
python tools/validate_schema.py --all

# Expected output:
# POSTGRES: ✅ 6/6 tables, 18/18 indexes, 4/4 triggers, 2/2 views
# SQLITE:   ✅ 6/6 tables, 18 indexes, 3 triggers, 2/2 views
```

### 4. Apply Migrations

```bash
# Initialize migration tracking (first time only)
python tools/migrate.py --db postgres://user:pass@localhost/rufus --init

# Check migration status
python tools/migrate.py --db postgres://user:pass@localhost/rufus --status

# Apply pending migrations
python tools/migrate.py --db postgres://user:pass@localhost/rufus --up

# SQLite example
python tools/migrate.py --db sqlite:///rufus.db --init
python tools/migrate.py --db sqlite:///rufus.db --up
```

## Type Mappings

The schema compiler automatically converts unified types to database-specific types:

| Unified Type | PostgreSQL | SQLite | Notes |
|--------------|------------|--------|-------|
| `uuid` | UUID | TEXT | Hex string in SQLite |
| `jsonb` | JSONB | TEXT | JSON string in SQLite |
| `timestamp` | TIMESTAMPTZ | TEXT | ISO8601 string |
| `boolean` | BOOLEAN | INTEGER | 0/1 in SQLite |
| `bigserial` | BIGSERIAL | INTEGER AUTOINCREMENT | Auto-increment |
| `varchar` | VARCHAR(n) | TEXT | Size ignored in SQLite |
| `text` | TEXT | TEXT | Same |
| `integer` | INTEGER | INTEGER | Same |
| `numeric` | NUMERIC | REAL | Floating point |
| `inet` | INET | TEXT | IP as string |

## Schema Version Tracking

Migrations are tracked in the `schema_migrations` table:

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL,
    checksum VARCHAR(64)
);
```

Each migration file is named: `<version>_<description>_<dbtype>.sql`

Example:
- `001_init_postgresql_schema.sql` (version 1, PostgreSQL)
- `002_postgres_standardized.sql` (version 2, PostgreSQL)
- `002_sqlite_initial.sql` (version 2, SQLite)

## Database-Specific Features

### PostgreSQL Features

- **Extensions**: uuid-ossp, pgcrypto
- **Advanced Types**: UUID, JSONB, INET, TIMESTAMPTZ
- **Triggers**: Auto-update timestamps, LISTEN/NOTIFY
- **Partial Indexes**: `WHERE` clauses for conditional indexing
- **Foreign Keys**: Full CASCADE support

### SQLite Features

- **Embedded**: No server required, single file
- **In-Memory Mode**: `:memory:` for fast tests
- **Type Affinity**: Flexible typing with TEXT storage
- **Triggers**: UPDATE triggers for timestamp management
- **Compatibility**: Standard SQL with some limitations

### Feature Parity

Both databases support:
- ✅ All 6 core tables (workflow_executions, tasks, compensation_log, etc.)
- ✅ All indexes (18 indexes)
- ✅ Auto-updating timestamps
- ✅ Foreign key constraints
- ✅ Partial indexes (filtered)
- ✅ Views (active_workflows, workflow_execution_summary)
- ✅ Idempotency keys
- ✅ JSONB data (as TEXT in SQLite)

PostgreSQL-only features:
- ❌ LISTEN/NOTIFY (real-time notifications)
- ❌ Advanced indexing (GIN, GiST)
- ❌ Stored procedures

## Testing

Run schema compiler tests:

```bash
python -c 'import pytest; pytest.main(["-v", "tests/test_schema_compiler.py", "-o", "addopts="])'

# Expected: 20 tests passing
# - Type mappings (PostgreSQL, SQLite)
# - Column definition compilation
# - Table, index, trigger, view generation
# - Full migration generation
```

## Tools

### compile_schema.py

Compiles `schema.yaml` to database-specific SQL.

```bash
python tools/compile_schema.py --help
python tools/compile_schema.py --all
python tools/compile_schema.py --target postgres --output migrations/003_custom.sql
```

### validate_schema.py

Validates generated migrations against original schema.

```bash
python tools/validate_schema.py --help
python tools/validate_schema.py --all
python tools/validate_schema.py --target sqlite
```

### migrate.py

Manages migration versioning and application.

```bash
python tools/migrate.py --help
python tools/migrate.py --db <db_url> --init     # Create schema_migrations table
python tools/migrate.py --db <db_url> --status   # Show pending migrations
python tools/migrate.py --db <db_url> --up       # Apply all pending
python tools/migrate.py --db <db_url> --up --to 5  # Apply up to version 5
```

## Best Practices

1. **Never edit .sql files directly** - Always modify `schema.yaml`
2. **Increment version** when making schema changes
3. **Generate both databases** to ensure consistency
4. **Validate** before committing
5. **Test migrations** on development database first
6. **Commit schema.yaml + generated .sql files** together
7. **Document breaking changes** in migration comments

## Troubleshooting

**Problem**: Type mapping error

```
ValueError: No type mapping for 'custom_type' in postgres
```

**Solution**: Add type mapping to `schema.yaml`:

```yaml
type_mappings:
  custom_type:
    postgres: "TEXT"
    sqlite: "TEXT"
```

---

**Problem**: Generated SQL doesn't match original

**Solution**: Run validation to see differences:

```bash
python tools/validate_schema.py --target postgres
```

---

**Problem**: Migration already applied

```
ERROR: duplicate key value violates unique constraint "schema_migrations_pkey"
```

**Solution**: Check migration status:

```bash
python tools/migrate.py --db <db_url> --status
```

## Additional Resources

- [SQLite Implementation Plan](../SQLITE_IMPLEMENTATION_PLAN.md)
- [CLAUDE.md - Database Schema Management](../CLAUDE.md#database-schema-management)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [SQLite Documentation](https://www.sqlite.org/docs.html)
