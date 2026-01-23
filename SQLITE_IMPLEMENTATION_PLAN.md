# SQLite Persistence Layer Implementation Plan

## Implementation Status

**Phase 1 (Week 1): Schema Standardization** ✅ **COMPLETED**

### Completed Deliverables
- ✅ `migrations/schema.yaml` - Unified database-agnostic schema definition (1.0.0)
- ✅ `tools/compile_schema.py` - Schema compiler generating PostgreSQL & SQLite migrations
- ✅ `migrations/002_postgres_standardized.sql` - Generated PostgreSQL migration (271 lines)
- ✅ `migrations/002_sqlite_initial.sql` - Generated SQLite migration (223 lines)
- ✅ `tools/validate_schema.py` - Schema validation tool (all checks passed)
- ✅ `tools/migrate.py` - Migration management with versioning support
- ✅ `tests/test_schema_compiler.py` - Comprehensive unit tests (20 tests, all passing)

### Validation Results
```
POSTGRES: ✅ 6/6 tables, 18/18 indexes, 4/4 triggers, 2/2 views
SQLITE:   ✅ 6/6 tables, 18 indexes, 3 triggers, 2/2 views
          ✅ All type mappings correct (UUID→TEXT, JSONB→TEXT, etc.)
```

---

**Phase 2 (Week 2-3): SQLitePersistenceProvider Implementation** ✅ **COMPLETED**

### Completed Deliverables
- ✅ `src/rufus/implementations/persistence/sqlite.py` - Full SQLitePersistenceProvider (800+ lines)
- ✅ All 20 PersistenceProvider interface methods implemented
- ✅ Type conversion helpers (JSON, datetime, UUID, boolean)
- ✅ WAL mode for better concurrency
- ✅ Foreign key enforcement
- ✅ Synchronous wrapper methods for compatibility
- ✅ `tests/test_sqlite_persistence.py` - Unit tests (14 tests, all passing)
- ✅ `tests/integration/test_sqlite_integration.py` - Integration tests (6 tests, all passing)
- ✅ `requirements.txt` updated with `aiosqlite>=0.19.0`

### Test Results
```
Unit Tests:        ✅ 14/14 passed (0.70s)
Integration Tests: ✅ 6/6 passed (0.67s)

Coverage:
- Core workflow methods (save/load/list)
- Task queue operations
- Logging (execution/audit/compensation)
- Metrics recording and retrieval
- Saga compensation flow
- Sub-workflow hierarchies
- Concurrent operations
- Idempotency keys
```

### Usage Example
```python
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

# In-memory database (for testing)
persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()

# File-based database (for development)
persistence = SQLitePersistenceProvider(db_path="workflows.db")
await persistence.initialize()
```

**Status:** SQLite persistence layer fully functional and production-ready for development/testing use cases.

---

## Executive Summary

This plan outlines the implementation of SQLite as an additional persistence layer for Rufus SDK, with a focus on **database schema standardization** between PostgreSQL and SQLite. This will provide a lightweight, embedded database option for development, testing, and single-server deployments.

---

## Goals

### Primary Goals
1. **Add SQLite persistence provider** - Implement `SQLitePersistenceProvider` with full feature parity
2. **Standardize database schema** - Create a unified schema specification that works across both databases
3. **Simplify development workflow** - Enable developers to run Rufus without PostgreSQL server
4. **Improve testing** - Faster test execution with in-memory SQLite databases

### Non-Goals
- **Not** replacing PostgreSQL for production use
- **Not** implementing distributed features in SQLite (e.g., LISTEN/NOTIFY)
- **Not** supporting cross-database migrations

---

## Current State Analysis

### PostgreSQL Schema Overview

**Core Tables (from `confucius/migrations/001_init_postgresql_schema.sql`):**

1. **`workflow_executions`** - Main workflow state (362 lines of schema)
   - 22 columns including JSONB for state/config
   - UUID primary keys
   - Sub-workflow support (parent_execution_id)
   - Saga mode support
   - Regional data sovereignty
   - Idempotency keys

2. **`tasks`** - Distributed task queue
   - Worker claiming with `FOR UPDATE SKIP LOCKED`
   - Retry logic
   - Idempotency keys

3. **`compensation_log`** - Saga pattern rollback tracking
   - State snapshots (before/after)
   - Action results

4. **`workflow_audit_log`** - Compliance and traceability
   - User actions tracking
   - IP address, user agent
   - State diffs

5. **`workflow_execution_logs`** - Operational debugging
   - Log levels
   - Trace context (trace_id, span_id)
   - Structured metadata

6. **`workflow_metrics`** - Performance monitoring
   - Time-series data
   - Tags for aggregation

**PostgreSQL-Specific Features:**
- UUID generation (`uuid-ossp`, `gen_random_uuid()`)
- JSONB columns with indexing
- Triggers for auto-updates
- LISTEN/NOTIFY for real-time updates
- Foreign key cascades
- Partial indexes
- Views for common queries

---

## Database Schema Standardization

### Strategy: Unified Schema Specification

Create a **database-agnostic schema definition** that can be compiled to both PostgreSQL and SQLite.

### Approach: Three-Layer Architecture

```
┌─────────────────────────────────────────┐
│   Unified Schema Definition (YAML)     │
│   - Declarative table/column specs     │
│   - Database-agnostic types             │
│   - Constraints and indexes             │
└───────────┬─────────────────────────────┘
            │
    ┌───────┴───────┐
    │               │
    ▼               ▼
┌─────────┐   ┌─────────┐
│ Postgres│   │ SQLite  │
│ Compiler│   │ Compiler│
└────┬────┘   └────┬────┘
     │             │
     ▼             ▼
  .sql files   .sql files
```

### Unified Schema Specification

**File**: `migrations/schema.yaml`

```yaml
# Rufus SDK Unified Database Schema
version: "1.0.0"

tables:
  workflow_executions:
    description: "Core workflow execution state and metadata"
    columns:
      - name: id
        type: uuid
        primary_key: true
        default:
          postgres: gen_random_uuid()
          sqlite: hex(randomblob(16))

      - name: workflow_type
        type: varchar(100)
        nullable: false

      - name: current_step
        type: integer
        nullable: false
        default: 0

      - name: status
        type: varchar(50)
        nullable: false

      - name: state
        type: json
        nullable: false
        default: '{}'
        column_type:
          postgres: JSONB
          sqlite: TEXT  # Store as JSON string

      - name: steps_config
        type: json
        nullable: false
        default: '[]'
        column_type:
          postgres: JSONB
          sqlite: TEXT

      - name: state_model_path
        type: varchar(500)
        nullable: false

      - name: saga_mode
        type: boolean
        default: false

      - name: completed_steps_stack
        type: json
        default: '[]'
        column_type:
          postgres: JSONB
          sqlite: TEXT

      - name: parent_execution_id
        type: uuid
        nullable: true
        foreign_key:
          table: workflow_executions
          column: id
          on_delete: CASCADE

      - name: blocked_on_child_id
        type: uuid
        nullable: true

      - name: data_region
        type: varchar(50)
        default: "'us-east-1'"

      - name: priority
        type: integer
        default: 5

      - name: created_at
        type: timestamp
        default:
          postgres: NOW()
          sqlite: CURRENT_TIMESTAMP

      - name: updated_at
        type: timestamp
        default:
          postgres: NOW()
          sqlite: CURRENT_TIMESTAMP

      - name: completed_at
        type: timestamp
        nullable: true

      - name: idempotency_key
        type: varchar(255)
        nullable: true
        unique: true

      - name: metadata
        type: json
        default: '{}'
        column_type:
          postgres: JSONB
          sqlite: TEXT

      # Additional columns for encryption (Phase 1 optimizations)
      - name: owner_id
        type: varchar(100)
        nullable: true

      - name: org_id
        type: varchar(100)
        nullable: true

      - name: encrypted_state
        type: bytea
        nullable: true
        column_type:
          postgres: BYTEA
          sqlite: BLOB

      - name: encryption_key_id
        type: varchar(100)
        nullable: true

    indexes:
      - name: idx_workflow_status
        columns: [status, updated_at]
        order: [ASC, DESC]

      - name: idx_workflow_type
        columns: [workflow_type]

      - name: idx_workflow_parent
        columns: [parent_execution_id]
        where: "parent_execution_id IS NOT NULL"

      - name: idx_workflow_region
        columns: [data_region]

      - name: idx_workflow_priority
        columns: [priority, created_at]
        where: "status = 'PENDING'"

    # PostgreSQL-only features (not supported in SQLite)
    postgres_only:
      - trigger: workflow_executions_updated_at
        function: update_updated_at_column()
        event: BEFORE UPDATE
      - trigger: workflow_update_trigger
        function: notify_workflow_update()
        event: AFTER UPDATE
      - trigger: workflow_completed_at
        function: set_completed_at()
        event: BEFORE UPDATE

  tasks:
    # Similar structure...

  compensation_log:
    # Similar structure...

  workflow_audit_log:
    # Similar structure...

  workflow_execution_logs:
    # Similar structure...

  workflow_metrics:
    # Similar structure...
```

### Type Mapping Table

| Unified Type | PostgreSQL | SQLite | Notes |
|--------------|------------|--------|-------|
| `uuid` | `UUID` | `TEXT` | Store as hex string in SQLite |
| `varchar(N)` | `VARCHAR(N)` | `TEXT` | SQLite has no length limit |
| `integer` | `INTEGER` | `INTEGER` | Compatible |
| `boolean` | `BOOLEAN` | `INTEGER` | 0/1 in SQLite |
| `json` | `JSONB` | `TEXT` | Parse/serialize in code |
| `timestamp` | `TIMESTAMPTZ` | `TEXT` | ISO 8601 format in SQLite |
| `bytea` | `BYTEA` | `BLOB` | Compatible |
| `bigserial` | `BIGSERIAL` | `INTEGER PRIMARY KEY` | Auto-increment |

### Schema Compiler Tool

**File**: `tools/compile_schema.py`

```python
#!/usr/bin/env python3
"""
Compiles unified schema.yaml to database-specific SQL scripts.

Usage:
    python tools/compile_schema.py --target postgres --output migrations/001_postgres.sql
    python tools/compile_schema.py --target sqlite --output migrations/001_sqlite.sql
"""

import yaml
import argparse
from typing import Dict, List, Any

class SchemaCompiler:
    def __init__(self, schema: Dict[str, Any], target: str):
        self.schema = schema
        self.target = target  # 'postgres' or 'sqlite'

    def compile(self) -> str:
        """Compile schema to SQL"""
        sql_parts = []

        # Header
        sql_parts.append(self._compile_header())

        # Tables
        for table_name, table_spec in self.schema['tables'].items():
            sql_parts.append(self._compile_table(table_name, table_spec))

        # Indexes
        for table_name, table_spec in self.schema['tables'].items():
            sql_parts.extend(self._compile_indexes(table_name, table_spec))

        # Database-specific features
        if self.target == 'postgres':
            sql_parts.append(self._compile_postgres_features())

        return '\n\n'.join(sql_parts)

    def _compile_header(self) -> str:
        if self.target == 'postgres':
            return """
-- Rufus SDK PostgreSQL Schema (Auto-generated)
-- Version: {version}

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
""".format(version=self.schema['version'])
        else:  # sqlite
            return """
-- Rufus SDK SQLite Schema (Auto-generated)
-- Version: {version}

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
""".format(version=self.schema['version'])

    def _compile_table(self, table_name: str, table_spec: Dict) -> str:
        columns = []

        for col in table_spec['columns']:
            col_def = self._compile_column(col)
            columns.append(f"    {col_def}")

        # Foreign keys
        for col in table_spec['columns']:
            if 'foreign_key' in col:
                fk = col['foreign_key']
                fk_def = f"FOREIGN KEY ({col['name']}) REFERENCES {fk['table']}({fk['column']}) ON DELETE {fk['on_delete']}"
                columns.append(f"    {fk_def}")

        table_sql = f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
        table_sql += ',\n'.join(columns)
        table_sql += "\n);"

        return table_sql

    def _compile_column(self, col: Dict) -> str:
        name = col['name']

        # Get database-specific type
        if 'column_type' in col and self.target in col['column_type']:
            col_type = col['column_type'][self.target]
        else:
            col_type = self._map_type(col['type'])

        # Build column definition
        parts = [name, col_type]

        # Primary key
        if col.get('primary_key'):
            if self.target == 'sqlite' and col['type'] == 'uuid':
                parts.append('PRIMARY KEY')
            else:
                parts.append('PRIMARY KEY')

        # Nullable
        if not col.get('nullable', True) and not col.get('primary_key'):
            parts.append('NOT NULL')

        # Default
        if 'default' in col:
            if isinstance(col['default'], dict):
                default_val = col['default'].get(self.target, col['default'].get('value'))
            else:
                default_val = col['default']
            parts.append(f'DEFAULT {default_val}')

        # Unique
        if col.get('unique'):
            parts.append('UNIQUE')

        return ' '.join(parts)

    def _map_type(self, unified_type: str) -> str:
        """Map unified type to database-specific type"""
        if self.target == 'postgres':
            return {
                'uuid': 'UUID',
                'integer': 'INTEGER',
                'boolean': 'BOOLEAN',
                'timestamp': 'TIMESTAMPTZ',
                'json': 'JSONB',
            }.get(unified_type.split('(')[0], unified_type)
        else:  # sqlite
            return {
                'uuid': 'TEXT',
                'integer': 'INTEGER',
                'boolean': 'INTEGER',
                'timestamp': 'TEXT',
                'json': 'TEXT',
                'bytea': 'BLOB',
            }.get(unified_type.split('(')[0], 'TEXT')

    # ... more methods for indexes, views, triggers, etc.
```

---

## SQLite Implementation

### File Structure

```
src/rufus/implementations/persistence/
├── __init__.py
├── postgres.py          # Existing
├── redis.py             # Existing
├── memory.py            # Existing
├── sqlite.py            # NEW
└── base/                # NEW - shared code
    ├── __init__.py
    ├── schema.py        # Schema utilities
    └── json_utils.py    # JSON serialization helpers
```

### SQLite Persistence Provider

**File**: `src/rufus/implementations/persistence/sqlite.py`

```python
"""
SQLite Persistence Provider for Rufus Workflow Engine

Provides lightweight, embedded persistence with the same interface as PostgreSQL.

Features:
- Single-file or in-memory database
- Full ACID compliance
- JSON storage for workflow state
- Suitable for development, testing, and single-server deployments

Limitations (compared to PostgreSQL):
- No LISTEN/NOTIFY (use polling instead)
- No true UUID type (stored as TEXT)
- Limited concurrency (write locks entire database)
- No JSONB indexing
"""

import sqlite3
import aiosqlite
import asyncio
import os
import uuid
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from rufus.providers.persistence import PersistenceProvider
from rufus.utils.serialization import serialize, deserialize


class SQLitePersistenceProvider(PersistenceProvider):
    """SQLite-backed workflow persistence with full feature parity"""

    def __init__(self, db_path: str = "rufus.db", in_memory: bool = False):
        """
        Initialize SQLite persistence provider.

        Args:
            db_path: Path to SQLite database file
            in_memory: If True, use in-memory database (for testing)
        """
        self.db_path = ":memory:" if in_memory else db_path
        self.db: Optional[aiosqlite.Connection] = None
        self._initialized = False
        self.encryption_enabled = os.getenv("ENABLE_ENCRYPTION_AT_REST", "false").lower() == "true"

    async def initialize(self):
        """Create connection and verify schema"""
        if self._initialized:
            return

        try:
            # Connect to SQLite database
            self.db = await aiosqlite.connect(self.db_path)

            # Enable foreign keys
            await self.db.execute("PRAGMA foreign_keys = ON")

            # Enable WAL mode for better concurrency
            await self.db.execute("PRAGMA journal_mode = WAL")

            # Set busy timeout (wait for locks)
            await self.db.execute("PRAGMA busy_timeout = 5000")

            # Verify schema exists
            async with self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_executions'"
            ) as cursor:
                result = await cursor.fetchone()

                if not result:
                    logger.warning(
                        f"workflow_executions table not found in {self.db_path}. "
                        "Please run migrations: python tools/migrate.py --target sqlite"
                    )

            self._initialized = True
            logger.info(f"SQLite persistence initialized (db={self.db_path})")

        except Exception as e:
            logger.error(f"Failed to initialize SQLite: {e}")
            raise

    async def close(self):
        """Close database connection"""
        if self.db:
            await self.db.close()
            self._initialized = False

    async def save_workflow(self, workflow_id: str, workflow_dict: Dict[str, Any]) -> None:
        """Save workflow state"""
        if not self._initialized:
            await self.initialize()

        # Set defaults
        workflow_dict.setdefault('saga_mode', False)
        workflow_dict.setdefault('completed_steps_stack', [])
        workflow_dict.setdefault('data_region', 'us-east-1')
        workflow_dict.setdefault('priority', 5)
        workflow_dict.setdefault('metadata', {})

        # Serialize JSON fields
        state_json = serialize(workflow_dict['state'])
        steps_config_json = serialize(workflow_dict['steps_config'])
        completed_steps_json = serialize(workflow_dict['completed_steps_stack'])
        metadata_json = serialize(workflow_dict['metadata'])

        # Handle encryption (if enabled)
        encrypted_state = None
        encryption_key_id = None
        if self.encryption_enabled:
            from rufus.implementations.security.crypto_utils import encrypt_string
            encrypted_state = encrypt_string(state_json)
            state_json = '{}'  # Store empty JSON in plaintext column
            encryption_key_id = "default"

        try:
            # Upsert workflow
            await self.db.execute("""
                INSERT INTO workflow_executions
                    (id, workflow_type, current_step, status, state,
                     steps_config, state_model_path, saga_mode,
                     completed_steps_stack, parent_execution_id, blocked_on_child_id,
                     data_region, priority, idempotency_key, metadata,
                     owner_id, org_id, encrypted_state, encryption_key_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    current_step = excluded.current_step,
                    status = excluded.status,
                    state = excluded.state,
                    steps_config = excluded.steps_config,
                    saga_mode = excluded.saga_mode,
                    completed_steps_stack = excluded.completed_steps_stack,
                    blocked_on_child_id = excluded.blocked_on_child_id,
                    metadata = excluded.metadata,
                    owner_id = excluded.owner_id,
                    org_id = excluded.org_id,
                    encrypted_state = excluded.encrypted_state,
                    encryption_key_id = excluded.encryption_key_id,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                workflow_dict['id'],
                workflow_dict['workflow_type'],
                workflow_dict['current_step'],
                workflow_dict['status'],
                state_json,
                steps_config_json,
                workflow_dict['state_model_path'],
                1 if workflow_dict['saga_mode'] else 0,
                completed_steps_json,
                workflow_dict.get('parent_execution_id'),
                workflow_dict.get('blocked_on_child_id'),
                workflow_dict['data_region'],
                workflow_dict['priority'],
                workflow_dict.get('idempotency_key'),
                metadata_json,
                workflow_dict.get('owner_id'),
                workflow_dict.get('org_id'),
                encrypted_state,
                encryption_key_id
            ))

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to save workflow {workflow_id}: {e}")
            raise

    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Load workflow state"""
        if not self._initialized:
            await self.initialize()

        async with self.db.execute(
            "SELECT * FROM workflow_executions WHERE id = ?",
            (workflow_id,)
        ) as cursor:
            row = await cursor.fetchone()

            if not row:
                return None

            # Convert row to dict
            columns = [desc[0] for desc in cursor.description]
            workflow_data = dict(zip(columns, row))

            # Deserialize JSON fields
            workflow_data['state'] = deserialize(workflow_data['state'])
            workflow_data['steps_config'] = deserialize(workflow_data['steps_config'])
            workflow_data['completed_steps_stack'] = deserialize(workflow_data['completed_steps_stack'])
            workflow_data['metadata'] = deserialize(workflow_data['metadata'])

            # Convert SQLite boolean (0/1) to Python bool
            workflow_data['saga_mode'] = bool(workflow_data['saga_mode'])

            # Handle decryption (if enabled)
            if workflow_data.get('encrypted_state'):
                from rufus.implementations.security.crypto_utils import decrypt_string
                decrypted_json = decrypt_string(workflow_data['encrypted_state'])
                workflow_data['state'] = deserialize(decrypted_json)

            return workflow_data

    # ... implement remaining methods following the same pattern
```

### Key Differences from PostgreSQL

| Feature | PostgreSQL | SQLite | Implementation Strategy |
|---------|------------|--------|-------------------------|
| **UUID** | Native `UUID` type | Store as `TEXT` | Generate with Python `uuid.uuid4()` |
| **JSONB** | Native with indexing | `TEXT` column | Serialize/deserialize in code |
| **Timestamps** | `TIMESTAMPTZ` | `TEXT` ISO 8601 | Parse/format in code |
| **Boolean** | Native `BOOLEAN` | `INTEGER` (0/1) | Convert in code |
| **Triggers** | PostgreSQL functions | SQLite triggers | Limited auto-update support |
| **LISTEN/NOTIFY** | Yes | No | Polling or external pub/sub |
| **Concurrency** | Row-level locking | Database-level | Accept limitation for dev/test |
| **FOR UPDATE SKIP LOCKED** | Yes | No | Use simpler locking |

---

## Implementation Phases

### Phase 1: Schema Standardization (Week 1)

**Tasks:**
1. Create `migrations/schema.yaml` with unified schema definition
2. Implement `tools/compile_schema.py` schema compiler
3. Generate PostgreSQL and SQLite migration scripts
4. Validate generated SQL matches existing Postgres schema
5. Add schema versioning support

**Deliverables:**
- `migrations/schema.yaml` - Unified schema
- `tools/compile_schema.py` - Schema compiler
- `migrations/002_postgres_standardized.sql` - Generated Postgres migration
- `migrations/002_sqlite_initial.sql` - Generated SQLite migration
- Unit tests for schema compiler

**Success Criteria:**
- Generated PostgreSQL schema matches existing schema
- SQLite schema passes validation
- Schema compiler handles all data types correctly

---

### Phase 2: SQLite Implementation (Week 2)

**Tasks:**
1. Implement `SQLitePersistenceProvider` class
2. Implement all `PersistenceProvider` interface methods
3. Add JSON serialization helpers
4. Handle UUID generation and storage
5. Implement connection pooling (if needed)
6. Add encryption support (compatible with Postgres)

**Deliverables:**
- `src/rufus/implementations/persistence/sqlite.py`
- `src/rufus/implementations/persistence/base/` - Shared utilities
- Unit tests for all persistence methods
- Integration tests with workflow engine

**Success Criteria:**
- All persistence methods implemented
- Tests pass with >90% coverage
- Performance acceptable for dev/test workloads

---

### Phase 3: Migration & Compatibility (Week 3)

**Tasks:**
1. Create migration tool for switching between databases
2. Add database connection abstraction
3. Implement schema migration utilities
4. Add backward compatibility for existing PostgreSQL deployments
5. Create examples with SQLite

**Deliverables:**
- `tools/migrate.py` - Migration tool
- Updated examples using SQLite
- Migration documentation
- Performance comparison benchmarks

**Success Criteria:**
- Existing PostgreSQL users unaffected
- Easy switching between databases
- Migration tool handles all edge cases

---

### Phase 4: Testing & Documentation (Week 4)

**Tasks:**
1. Add comprehensive test suite for SQLite
2. Run all existing tests with SQLite backend
3. Performance benchmarks (SQLite vs Postgres vs Redis)
4. Update documentation (README, CLAUDE.md, examples)
5. Add troubleshooting guide

**Deliverables:**
- Test suite with 95%+ coverage
- Performance benchmark results
- Complete documentation updates
- Troubleshooting guide

**Success Criteria:**
- All tests pass with SQLite
- Documentation complete and accurate
- Performance meets expectations for target use cases

---

## Usage Examples

### Development Setup (Simplified)

**Before (PostgreSQL required):**
```python
# Requires running PostgreSQL server
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider

persistence = PostgresPersistenceProvider(
    db_url="postgresql://user:pass@localhost:5432/rufus_db"
)
```

**After (SQLite for development):**
```python
# No server required!
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

# Option 1: File-based (persists across runs)
persistence = SQLitePersistenceProvider(db_path="rufus_dev.db")

# Option 2: In-memory (for tests)
persistence = SQLitePersistenceProvider(in_memory=True)
```

### Testing Improvements

**Before:**
```python
# Slow: requires PostgreSQL
@pytest.fixture
async def persistence():
    pg = PostgresPersistenceProvider("postgresql://...")
    await pg.initialize()
    yield pg
    await pg.close()
    # Manual cleanup of test data
```

**After:**
```python
# Fast: in-memory SQLite
@pytest.fixture
async def persistence():
    sqlite = SQLitePersistenceProvider(in_memory=True)
    await sqlite.initialize()
    yield sqlite
    await sqlite.close()
    # Automatic cleanup (in-memory)
```

### Production Deployment

SQLite is **not recommended for production** but can be used for:
- **Single-server deployments** (low concurrency)
- **Embedded applications**
- **Edge computing** (IoT devices)
- **Desktop applications**

```python
# Production SQLite example (with WAL mode)
persistence = SQLitePersistenceProvider(
    db_path="/var/lib/rufus/workflows.db"
)
# WAL mode enabled automatically for better concurrency
```

---

## Performance Expectations

### Benchmarks (Estimated)

| Operation | PostgreSQL | SQLite (File) | SQLite (Memory) |
|-----------|------------|---------------|-----------------|
| **Workflow Save** | 2-5ms | 1-3ms | 0.1-0.5ms |
| **Workflow Load** | 2-5ms | 1-3ms | 0.1-0.5ms |
| **List Workflows** | 10-20ms | 5-15ms | 1-5ms |
| **Concurrent Writes** | 1000+/sec | 100-200/sec | 500-1000/sec |
| **Database Size** | Larger (indexes) | Smaller | N/A |

### When to Use Each

| Use Case | PostgreSQL | SQLite | Redis (Memory) |
|----------|------------|--------|----------------|
| **Production (High Scale)** | ✅ Best | ❌ No | ⚠️ Cache only |
| **Production (Single Server)** | ✅ Good | ✅ Acceptable | ❌ No persistence |
| **Development** | ⚠️ Requires setup | ✅ Perfect | ✅ Good |
| **Testing** | ⚠️ Slow | ✅ Fast | ✅ Fastest |
| **CI/CD** | ❌ Slow | ✅ Ideal | ✅ Ideal |
| **Edge Devices** | ❌ Too heavy | ✅ Perfect | ⚠️ Limited |
| **Distributed Workers** | ✅ Required | ❌ No | ❌ No |

---

## Risk Assessment

### Low Risk
- ✅ SQLite implementation (well-established library)
- ✅ Schema standardization (clear mapping)
- ✅ Development/testing use cases

### Medium Risk
- ⚠️ Schema compiler complexity (need thorough testing)
- ⚠️ Migration tool edge cases
- ⚠️ Performance under concurrent load

### High Risk
- ❌ Using SQLite in production without understanding limitations
- ❌ Schema divergence between databases over time

### Mitigation Strategies
1. **Automated testing** - Test suite runs against both databases
2. **Schema validation** - CI checks schema consistency
3. **Clear documentation** - Usage guidelines and limitations
4. **Deprecation warnings** - Warn if using SQLite in production

---

## Open Questions

1. **Schema Evolution**: How do we handle schema migrations going forward?
   - **Proposed**: Use Alembic with custom SQLite/Postgres targets

2. **Concurrency**: What's the acceptable write throughput for SQLite?
   - **Proposed**: Benchmark and document limits

3. **LISTEN/NOTIFY Alternative**: How to handle real-time updates in SQLite?
   - **Proposed**: Polling with configurable interval, or external pub/sub (Redis)

4. **Testing Strategy**: Run all tests against both databases?
   - **Proposed**: Parameterized fixtures, run tests with both backends in CI

5. **Encryption**: Same encryption approach as Postgres?
   - **Proposed**: Yes, use same `crypto_utils` module

---

## Success Metrics

### Technical Metrics
- ✅ 100% PersistenceProvider interface implemented
- ✅ >95% test coverage for SQLite provider
- ✅ All existing tests pass with SQLite backend
- ✅ Schema compiler handles 100% of schema definition
- ✅ <5% performance degradation vs. Postgres for dev workloads

### User Experience Metrics
- ✅ Zero-config development setup (no PostgreSQL required)
- ✅ 10x faster test execution (in-memory SQLite)
- ✅ Simplified CI/CD (no database containers)
- ✅ Easy switching between databases (config change only)

### Documentation Metrics
- ✅ Complete usage guide
- ✅ Migration guide from Postgres to SQLite
- ✅ Performance tuning guide
- ✅ Troubleshooting guide

---

## Next Steps

1. **Review this plan** - Get feedback from stakeholders
2. **Refine schema design** - Finalize unified schema format
3. **Prototype schema compiler** - Validate approach
4. **Implement Phase 1** - Schema standardization
5. **Iterate** - Adjust based on learnings

---

## Appendix: Alternative Approaches Considered

### Approach 1: Dual Schema (Rejected)
**Description**: Maintain separate schemas for Postgres and SQLite
**Pros**: Simpler initially
**Cons**: Schema drift, duplication, maintenance burden
**Decision**: Rejected in favor of unified schema

### Approach 2: ORM-Based (Rejected)
**Description**: Use SQLAlchemy ORM to abstract database
**Pros**: Database abstraction, migrations
**Cons**: Performance overhead, complexity, limited control
**Decision**: Rejected, prefer direct SQL control

### Approach 3: Shared Base Class (Considered)
**Description**: Extract common code to `BasePersistenceProvider`
**Pros**: Code reuse, consistency
**Cons**: Some complexity
**Decision**: Implement in Phase 2 if beneficial

---

**Total Estimated Effort**: 4 weeks (1 engineer)
**Priority**: Medium
**Dependencies**: None (Phase 1 optimizations already complete)
**Risk Level**: Low-Medium
