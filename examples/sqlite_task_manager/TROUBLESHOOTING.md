# SQLite Persistence - Troubleshooting Guide

This guide covers common issues, error messages, and solutions when using SQLite with Ruvon SDK.

## Table of Contents
- [Common Errors](#common-errors)
- [Performance Issues](#performance-issues)
- [Data Integrity](#data-integrity)
- [Migration Problems](#migration-problems)
- [Best Practices](#best-practices)

---

## Common Errors

### Error: "database is locked"

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Causes:**
- Multiple concurrent writes exceeding SQLite's write serialization capability
- Transaction held open for too long
- Insufficient lock timeout

**Solutions:**

1. **Increase timeout** (most common fix):
```python
persistence = SQLitePersistenceProvider(
    db_path="workflows.db",
    timeout=30.0  # Increase from default 5 seconds
)
```

2. **Reduce concurrent writes:**
```python
# Limit concurrent workflow operations
# Use a semaphore or queue to serialize writes
import asyncio

write_semaphore = asyncio.Semaphore(1)  # Only 1 writer at a time

async def save_with_lock(workflow_id, data):
    async with write_semaphore:
        await persistence.save_workflow(workflow_id, data)
```

3. **Use WAL mode** (automatically enabled for file-based databases):
```python
# Verify WAL mode is enabled
async with persistence.conn.execute("PRAGMA journal_mode") as cursor:
    mode = await cursor.fetchone()
    print(f"Journal mode: {mode[0]}")  # Should be 'wal'

# If not enabled, set it manually
await persistence.conn.execute("PRAGMA journal_mode=WAL")
```

4. **Switch to PostgreSQL for high concurrency:**
```python
# For >50 concurrent writers, use PostgreSQL
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider
persistence = PostgresPersistenceProvider(db_url="postgresql://...")
```

---

### Error: "no such table"

**Symptoms:**
```
sqlite3.OperationalError: no such table: workflow_executions
```

**Causes:**
- Database schema not initialized
- Using wrong database file
- Migrations not applied

**Solutions:**

1. **Apply migrations:**
```bash
# Initialize schema_migrations table
python tools/migrate.py --db sqlite:///workflows.db --init

# Apply all pending migrations
python tools/migrate.py --db sqlite:///workflows.db --up

# Check migration status
python tools/migrate.py --db sqlite:///workflows.db --status
```

2. **Create schema manually** (for testing):
```python
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider

persistence = SQLitePersistenceProvider(db_path=":memory:")
await persistence.initialize()

# Apply schema from migration file
with open("migrations/002_sqlite_initial.sql", "r") as f:
    schema = f.read()
    await persistence.conn.executescript(schema)
```

3. **Verify database path:**
```python
import os

db_path = "workflows.db"
if os.path.exists(db_path):
    print(f"Database exists: {os.path.abspath(db_path)}")
else:
    print(f"Database NOT found at: {os.path.abspath(db_path)}")
```

---

### Error: "UNIQUE constraint failed"

**Symptoms:**
```
sqlite3.IntegrityError: UNIQUE constraint failed: workflow_executions.idempotency_key
```

**Explanation:**
This is **expected behavior** when using idempotency keys. SQLite uses `INSERT OR REPLACE` semantics, which updates existing records instead of raising an error.

**Solutions:**

1. **For idempotent operations** (most cases):
```python
# This is NORMAL - SQLite will update the existing record
# No action needed
await persistence.save_workflow(workflow_id, workflow_data)
```

2. **To detect duplicates:**
```python
# Check if workflow exists before saving
existing = await persistence.load_workflow(workflow_id)
if existing:
    print(f"Workflow {workflow_id} already exists")
else:
    await persistence.save_workflow(workflow_id, workflow_data)
```

3. **To enforce uniqueness:**
```python
# Use a unique idempotency_key for each operation
import uuid

workflow_data['idempotency_key'] = str(uuid.uuid4())
await persistence.save_workflow(workflow_id, workflow_data)
```

---

### Error: "table workflow_metrics has no column named X"

**Symptoms:**
```
sqlite3.OperationalError: table workflow_metrics has no column named unit
```

**Causes:**
- Schema mismatch between code and database
- Using old schema with new code
- Missing columns in custom schema

**Solutions:**

1. **Regenerate schema from schema.yaml:**
```bash
# Generate fresh SQLite schema
python tools/compile_schema.py --target sqlite --output migrations/002_sqlite_initial.sql

# Apply to database
python tools/migrate.py --db sqlite:///workflows.db --up
```

2. **Add missing columns manually:**
```sql
ALTER TABLE workflow_metrics ADD COLUMN unit TEXT;
ALTER TABLE workflow_metrics ADD COLUMN tags TEXT DEFAULT '{}';
```

3. **Use complete schema from migrations:**
```python
# For in-memory databases, use full schema
with open("migrations/002_sqlite_initial.sql", "r") as f:
    schema = f.read()
    await persistence.conn.executescript(schema)
```

---

### Error: "cannot commit - no transaction is active"

**Symptoms:**
```
sqlite3.ProgrammingError: cannot commit - no transaction is active
```

**Causes:**
- Transaction already committed
- Connection auto-commit mode
- Nested transaction issue

**Solutions:**

1. **Let aiosqlite handle transactions:**
```python
# Don't call commit() manually - aiosqlite handles it
await persistence.conn.execute("INSERT INTO ...")
# await persistence.conn.commit()  # Remove manual commit
```

2. **Use context manager for transactions:**
```python
async with persistence.conn.execute("INSERT INTO ...") as cursor:
    result = await cursor.fetchone()
# Auto-commits on context exit
```

---

## Performance Issues

### Slow Write Operations

**Symptoms:**
- Workflow saves taking >100ms
- High latency for task creation
- Database locks lasting multiple seconds

**Diagnostics:**
```python
import time

# Measure write performance
start = time.time()
await persistence.save_workflow(workflow_id, workflow_data)
elapsed = time.time() - start
print(f"Save took {elapsed*1000:.2f}ms")
```

**Solutions:**

1. **Enable WAL mode** (should be automatic):
```python
# Verify WAL mode
async with persistence.conn.execute("PRAGMA journal_mode") as cursor:
    mode = await cursor.fetchone()
    if mode[0] != 'wal':
        await persistence.conn.execute("PRAGMA journal_mode=WAL")
        await persistence.conn.commit()
```

2. **Use in-memory database for tests:**
```python
# 10-100x faster for tests
persistence = SQLitePersistenceProvider(db_path=":memory:")
```

3. **Batch operations:**
```python
# Instead of many small writes
for i in range(100):
    await persistence.save_workflow(f"wf_{i}", data)

# Use a transaction
async with persistence.conn.cursor() as cursor:
    for i in range(100):
        await cursor.execute("INSERT INTO ...")
    await persistence.conn.commit()
```

4. **Optimize indexes:**
```sql
-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_workflow_status
    ON workflow_executions(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_workflow_type
    ON workflow_executions(workflow_type);
```

---

### High Memory Usage

**Symptoms:**
- Memory usage growing over time
- OOM errors with large workflows

**Solutions:**

1. **Close connections when done:**
```python
try:
    persistence = SQLitePersistenceProvider(db_path="workflows.db")
    await persistence.initialize()
    # ... use persistence ...
finally:
    await persistence.close()  # Important!
```

2. **Limit result set sizes:**
```python
# Don't load all workflows at once
workflows = await persistence.list_workflows(
    status='ACTIVE',
    limit=100  # Paginate large result sets
)
```

3. **Use vacuum for database maintenance:**
```python
# Reclaim space from deleted records
await persistence.conn.execute("VACUUM")
```

---

## Data Integrity

### Foreign Key Violations

**Symptoms:**
```
sqlite3.IntegrityError: FOREIGN KEY constraint failed
```

**Causes:**
- Deleting parent workflow with active children
- Creating tasks for non-existent workflows

**Solutions:**

1. **Verify foreign key enforcement:**
```python
# Check if foreign keys are enabled
async with persistence.conn.execute("PRAGMA foreign_keys") as cursor:
    enabled = await cursor.fetchone()
    print(f"Foreign keys enabled: {enabled[0] == 1}")

# Enable if needed
await persistence.conn.execute("PRAGMA foreign_keys = ON")
```

2. **Use CASCADE deletes** (already in schema):
```sql
-- Parent workflow deletion cascades to children
CREATE TABLE tasks (
    ...
    execution_id TEXT REFERENCES workflow_executions(id) ON DELETE CASCADE
);
```

3. **Check references before deletion:**
```python
# Verify no child workflows exist
async with persistence.conn.execute(
    "SELECT COUNT(*) FROM workflow_executions WHERE parent_execution_id = ?",
    (workflow_id,)
) as cursor:
    count = (await cursor.fetchone())[0]
    if count > 0:
        print(f"Cannot delete: {count} child workflows exist")
```

---

### Data Type Conversion Errors

**Symptoms:**
```
TypeError: Object of type datetime is not JSON serializable
ValueError: Invalid UUID format
```

**Solutions:**

1. **Use provided conversion helpers:**
```python
# These are built into SQLitePersistenceProvider
from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider

# UUID conversion
uuid_text = persistence._serialize_json(uuid_obj)
uuid_obj = persistence._deserialize_json(uuid_text)

# Datetime conversion
iso_string = persistence._to_iso8601(datetime_obj)
datetime_obj = persistence._from_iso8601(iso_string)

# Boolean conversion
int_value = persistence._bool_to_int(True)  # 1
bool_value = persistence._int_to_bool(1)    # True
```

2. **Let Pydantic handle serialization:**
```python
from pydantic import BaseModel

class WorkflowState(BaseModel):
    created_at: datetime
    workflow_id: UUID

# Pydantic automatically handles JSON serialization
state_dict = workflow_state.model_dump(mode='json')
```

---

## Migration Problems

### Migration Version Conflicts

**Symptoms:**
```
Error: Migration 002 already applied
Error: Cannot apply migration - version mismatch
```

**Solutions:**

1. **Check migration status:**
```bash
python tools/migrate.py --db sqlite:///workflows.db --status
```

2. **Reset migrations** (development only):
```bash
# Delete database and start fresh
rm workflows.db workflows.db-shm workflows.db-wal

# Re-apply migrations
python tools/migrate.py --db sqlite:///workflows.db --init
python tools/migrate.py --db sqlite:///workflows.db --up
```

3. **Manual migration table management:**
```python
# View applied migrations
async with persistence.conn.execute(
    "SELECT * FROM schema_migrations ORDER BY version"
) as cursor:
    migrations = await cursor.fetchall()
    for version, applied_at in migrations:
        print(f"Migration {version}: {applied_at}")
```

---

### Schema Drift Between Databases

**Symptoms:**
- PostgreSQL schema works but SQLite fails
- Missing columns in SQLite
- Type conversion errors

**Solutions:**

1. **Always use schema.yaml as source of truth:**
```bash
# Regenerate both schemas
python tools/compile_schema.py --all

# Validate consistency
python tools/validate_schema.py --all
```

2. **Run validation in CI:**
```yaml
# .github/workflows/test.yml
- name: Validate Schema
  run: |
    python tools/validate_schema.py --all
    python tools/compile_schema.py --all
    git diff --exit-code migrations/  # Fail if schemas changed
```

---

## Best Practices

### Development Workflow

```python
# 1. Use file-based database for development
persistence = SQLitePersistenceProvider(db_path="dev_workflows.db")

# 2. Add to .gitignore
# *.db
# *.db-shm
# *.db-wal

# 3. Apply migrations on startup
if not os.path.exists("dev_workflows.db"):
    # Initialize schema
    subprocess.run([
        "python", "tools/migrate.py",
        "--db", "sqlite:///dev_workflows.db",
        "--up"
    ])
```

### Testing Workflow

```python
# Use in-memory database for tests
@pytest.fixture
async def persistence():
    provider = SQLitePersistenceProvider(db_path=":memory:")
    await provider.initialize()

    # Apply schema
    with open("migrations/002_sqlite_initial.sql") as f:
        await provider.conn.executescript(f.read())

    yield provider

    await provider.close()
```

### Production Deployment (Low Concurrency)

```python
# 1. Use absolute path
persistence = SQLitePersistenceProvider(
    db_path="/var/lib/rufus/workflows.db",
    timeout=30.0
)

# 2. Set up backups
import shutil
from datetime import datetime

def backup_database():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"/backups/workflows_{timestamp}.db"
    shutil.copy("/var/lib/rufus/workflows.db", backup_path)
    print(f"Backup created: {backup_path}")

# Run backup daily via cron
# 0 2 * * * python /path/to/backup_script.py
```

### Monitoring

```python
# Monitor database size
import os

db_path = "workflows.db"
size_mb = os.path.getsize(db_path) / (1024 * 1024)
print(f"Database size: {size_mb:.2f} MB")

# Monitor performance
import time

async def monitor_query_performance():
    start = time.time()
    workflows = await persistence.list_workflows(limit=100)
    elapsed = time.time() - start

    if elapsed > 1.0:
        print(f"SLOW QUERY: list_workflows took {elapsed:.2f}s")
```

---

## When to Switch to PostgreSQL

Consider migrating to PostgreSQL if you experience:

1. **Database locked errors** despite increasing timeout
2. **Write throughput** needs exceed 50 concurrent writers
3. **Real-time updates** required (LISTEN/NOTIFY)
4. **Distributed deployment** across multiple servers
5. **Production workloads** with high concurrency requirements

Migration path:
```python
# Export from SQLite
sqlite_db = SQLitePersistenceProvider(db_path="workflows.db")
workflows = await sqlite_db.list_workflows(limit=10000)

# Import to PostgreSQL
pg_db = PostgresPersistenceProvider(db_url="postgresql://...")
for workflow in workflows:
    await pg_db.save_workflow(workflow['id'], workflow)
```

---

## Getting Help

If you encounter issues not covered in this guide:

1. **Run benchmarks** to compare performance:
   ```bash
   python tests/benchmarks/persistence_benchmark.py
   ```

2. **Check SQLite limits:**
   ```python
   async with persistence.conn.execute("PRAGMA compile_options") as cursor:
       options = await cursor.fetchall()
       for option in options:
           print(option[0])
   ```

3. **Enable verbose logging:**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

4. **File an issue** at: https://github.com/KamikaziD/ruvon-sdk/issues
   - Include error messages
   - Provide minimal reproduction case
   - Share system information (Python version, aiosqlite version, OS)

---

## Additional Resources

- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [aiosqlite Documentation](https://aiosqlite.omnilib.dev/)
- [SQLITE_IMPLEMENTATION_PLAN.md](../../SQLITE_IMPLEMENTATION_PLAN.md)
- [CLAUDE.md - SQLite Section](../../CLAUDE.md#sqlite-persistence-provider)
- [Ruvon SDK Examples](../)
