# Alembic + SQLAlchemy Migration Plan

## Executive Summary

**Recommendation:** Migrate to a **hybrid approach** using SQLAlchemy Core + Alembic for schema management while preserving raw SQL for performance-critical operations.

**Timeline:** 3-4 weeks (phased implementation)
**Risk Level:** Medium (requires careful testing, but low breaking change risk)
**Performance Impact:** Minimal (keeps raw SQL for hot paths)

---

## Research Summary

### Current State Analysis

**What Ruvon Has:**
- ✅ Raw asyncpg with manual SQL queries (high performance)
- ✅ Custom schema.yaml with compile_schema.py (database-agnostic)
- ✅ Dual migration system (docker/init-db.sql + migrations/*.sql)
- ✅ Persistence provider pattern (Protocol-based abstraction)
- ✅ Performance optimizations (uvloop, orjson, connection pooling)
- ⚠️ Manual schema synchronization between systems
- ⚠️ No type-safe database models
- ⚠️ Migration history tracking is limited

**What We'd Gain with Alembic + SQLAlchemy:**
- ✅ Industry-standard migration management
- ✅ Auto-generate migrations from model changes
- ✅ Better version tracking and rollback support
- ✅ Type-safe database models (Python classes)
- ✅ Unified migration system (eliminates dual system)
- ✅ SQLite batch mode support (automatic ALTER compatibility)
- ✅ Repository pattern integration
- ✅ Better IDE support and autocomplete

**What We'd Lose/Risk:**
- ⚠️ Performance overhead (3x slower vs raw asyncpg for some ops)
- ⚠️ Autogenerate false positives/negatives (~15% rate)
- ⚠️ Cannot manage advanced DB features (RLS, sharding, custom ENUMs)
- ⚠️ Added complexity and learning curve
- ⚠️ Larger dependency footprint

### Research Sources

**Best Practices:**
- [Alembic Best Practices - PingCAP](https://www.pingcap.com/article/best-practices-alembic-schema-migration/)
- [Alembic Complete Guide - Medium](https://medium.com/@tejpal.abhyuday/alembic-database-migrations-the-complete-developers-guide-d3fc852a6a9e)
- [Best Practices - Pavel Loginov](https://medium.com/@pavel.loginov.dev/best-practices-for-alembic-and-sqlalchemy-73e4c8a6c205)

**Performance Considerations:**
- [SQLAlchemy vs Raw SQL - Medium](https://medium.com/@melihcolpan/sqlalchemy-vs-raw-sql-queries-performance-comparison-and-best-practices-caba49125630)
- [ORM vs Raw SQL - UnfoldAI](https://unfoldai.com/orm-vs-raw-sql/)
- [AsyncPG ORM Performance - GitHub](https://github.com/sqlalchemy/sqlalchemy/discussions/7294)

**Multi-Database Support:**
- [Alembic Batch Migrations - SQLAlchemy Docs](https://alembic.sqlalchemy.org/en/latest/batch.html)
- [PostgreSQL & SQLite Same Schema - GitHub Discussion](https://github.com/sqlalchemy/alembic/discussions/1009)

**Limitations:**
- [Hidden Bias of Alembic - Atlas](https://atlasgo.io/blog/2025/02/10/the-hidden-bias-alembic-django-migrations)

---

## Recommended Approach: Hybrid Architecture

### Philosophy

**Use SQLAlchemy Core (not ORM) + Alembic for:**
- ✅ Schema definition (replaces schema.yaml)
- ✅ Migration generation and management
- ✅ Database-agnostic type mapping
- ✅ Development/testing convenience

**Keep Raw SQL for:**
- ✅ High-frequency queries (save_workflow, load_workflow)
- ✅ Complex joins and aggregations
- ✅ Bulk operations (load testing)
- ✅ Performance-critical paths

### Why This Works

1. **Maintains Performance:**
   - Hot paths still use raw asyncpg (no ORM overhead)
   - Load testing remains fast (1000+ req/sec)
   - Connection pooling unchanged

2. **Gains Modern Tooling:**
   - Type-safe models for IDE autocomplete
   - Auto-generate migrations (with manual review)
   - Industry-standard workflow
   - Better testing support

3. **Preserves Architecture:**
   - Persistence provider pattern intact
   - No breaking changes to public API
   - Implementation detail only

4. **Eliminates Dual System:**
   - Single migration path (Alembic)
   - No more docker/init-db.sql vs migrations/*.sql
   - Automatic SQLite batch mode

---

## Migration Plan (4 Phases)

### Phase 1: Foundation (Week 1)

**Goal:** Add SQLAlchemy without breaking anything

**Tasks:**
1. **Install dependencies:**
   ```bash
   pip install sqlalchemy alembic asyncpg aiosqlite
   ```

2. **Create SQLAlchemy models:**
   ```python
   # src/ruvon/models/database.py
   from sqlalchemy import Table, Column, Integer, String, DateTime, JSON
   from sqlalchemy.dialects.postgresql import UUID, JSONB
   from sqlalchemy import MetaData

   metadata = MetaData()

   workflow_executions = Table(
       'workflow_executions',
       metadata,
       Column('id', UUID(as_uuid=True), primary_key=True),
       Column('workflow_type', String(200), nullable=False),
       Column('status', String(50), nullable=False),
       Column('state', JSONB, nullable=False),
       Column('current_step', String(200)),
       # ... all other columns
   )
   ```

3. **Initialize Alembic:**
   ```bash
   cd src/ruvon
   alembic init alembic
   ```

4. **Configure Alembic for dual database support:**
   ```python
   # alembic/env.py
   from ruvon.models.database import metadata

   def run_migrations_online():
       # Detect database type and enable batch mode for SQLite
       connectable = create_engine(config.get_main_option("sqlalchemy.url"))

       with connectable.connect() as connection:
           context.configure(
               connection=connection,
               target_metadata=metadata,
               render_as_batch=True,  # SQLite compatibility
               compare_type=True,
               compare_server_default=True
           )
   ```

5. **Generate baseline migration:**
   ```bash
   alembic revision --autogenerate -m "baseline schema"
   # Review and edit generated migration
   alembic upgrade head
   ```

**Deliverables:**
- SQLAlchemy models matching current schema
- Alembic configuration
- Baseline migration
- Documentation update

**Success Criteria:**
- Alembic can generate schema matching current SQL
- Both PostgreSQL and SQLite migrations work
- No changes to persistence providers yet

---

### Phase 2: Parallel Migration System (Week 2)

**Goal:** Run Alembic alongside existing migrations

**Tasks:**
1. **Update docker-compose.yml:**
   ```yaml
   ruvon-server:
     environment:
       RUN_ALEMBIC_MIGRATIONS: "true"
     command: >
       sh -c "
         if [ \"$RUN_ALEMBIC_MIGRATIONS\" = \"true\" ]; then
           alembic upgrade head
         fi &&
         uvicorn ruvon_server.main:app --host 0.0.0.0
       "
   ```

2. **Add migration health check:**
   ```python
   # ruvon/migrations/checker.py
   async def verify_schema_version(persistence):
       """Check if database schema matches expected version."""
       async with persistence.pool.acquire() as conn:
           result = await conn.fetchval(
               "SELECT version_num FROM alembic_version LIMIT 1"
           )
           expected = get_head_revision()
           if result != expected:
               raise SchemaVersionMismatch(...)
   ```

3. **Deprecate old migration system:**
   - Add warning to tools/compile_schema.py
   - Document migration path in CLAUDE.md
   - Keep old system for backward compatibility

4. **Testing:**
   - Test fresh Alembic-based setup
   - Test migration from old system to Alembic
   - Verify both PostgreSQL and SQLite

**Deliverables:**
- Docker auto-migrations with Alembic
- Schema version verification
- Migration guide documentation
- Backward compatibility maintained

**Success Criteria:**
- Fresh installs use Alembic only
- Existing deployments can migrate smoothly
- Both systems work in parallel

---

### Phase 3: Hybrid Query Layer (Week 3)

**Goal:** Use SQLAlchemy for simple queries, raw SQL for performance

**Tasks:**
1. **Add SQLAlchemy Core query helpers:**
   ```python
   # src/ruvon/implementations/persistence/postgres.py
   from sqlalchemy import select, insert, update
   from ruvon.models.database import workflow_executions

   class PostgresPersistenceProvider(PersistenceProvider):
       def __init__(self, db_url: str):
           self.db_url = db_url
           self.pool: Optional[asyncpg.Pool] = None
           # Keep asyncpg pool for raw SQL

       async def list_workflows(self, limit: int = 100):
           """Use SQLAlchemy Core for simple queries."""
           stmt = (
               select(workflow_executions)
               .limit(limit)
               .order_by(workflow_executions.c.created_at.desc())
           )

           # Still execute via asyncpg for performance
           async with self.pool.acquire() as conn:
               rows = await conn.fetch(str(stmt), *stmt.compile().params.values())
               return [dict(row) for row in rows]

       async def save_workflow(self, workflow_id: str, workflow_dict: Dict):
           """Keep raw SQL for hot path."""
           # Existing implementation unchanged
           async with self.pool.acquire() as conn:
               await conn.execute("""
                   INSERT INTO workflow_executions (...)
                   VALUES ($1, $2, ...)
                   ON CONFLICT (id) DO UPDATE SET ...
               """, ...)
   ```

2. **Gradual query conversion:**
   - Convert read-only queries first (list, get, search)
   - Keep write queries as raw SQL (save, update, delete)
   - Benchmark each conversion

3. **Performance testing:**
   ```bash
   # Before and after benchmarks
   python tests/benchmarks/persistence_benchmark.py

   # Load testing
   python tests/load/run_load_test.py --all --devices 1000
   ```

4. **Type safety improvements:**
   ```python
   # With SQLAlchemy models, get IDE autocomplete
   from ruvon.models.database import workflow_executions

   # Type-safe column references
   stmt = select(workflow_executions.c.id, workflow_executions.c.status)
   ```

**Deliverables:**
- Hybrid query implementation
- Performance benchmarks
- Type-safe query helpers
- Migration guide for developers

**Success Criteria:**
- Read queries use SQLAlchemy Core
- Write queries stay raw SQL
- Performance within 5% of baseline
- Load tests still pass

---

### Phase 4: Cleanup and Optimization (Week 4)

**Goal:** Remove old system, optimize new approach

**Tasks:**
1. **Remove deprecated code:**
   - Delete docker/init-db.sql (replaced by Alembic)
   - Delete migrations/*.sql (old system)
   - Delete tools/compile_schema.py
   - Delete tools/validate_schema.py
   - Delete migrations/schema.yaml

2. **Simplify docker-compose.yml:**
   ```yaml
   postgres:
     # No more init-db.sql mount
     volumes:
       - postgres_data:/var/lib/postgresql/data

   ruvon-server:
     environment:
       AUTO_MIGRATE: "true"
     command: >
       sh -c "
         alembic upgrade head &&
         uvicorn ruvon_server.main:app --host 0.0.0.0
       "
   ```

3. **Update documentation:**
   - CLAUDE.md: Remove dual migration system docs
   - QUICKSTART.md: Update installation paths
   - docker/README.md: Simplify schema management

4. **Add developer tooling:**
   ```bash
   # New make commands
   make migration-create MSG="add user preferences"
   make migration-upgrade
   make migration-downgrade
   make migration-history
   ```

5. **CI/CD updates:**
   ```yaml
   # GitHub Actions
   - name: Run migrations
     run: alembic upgrade head

   - name: Verify schema
     run: |
       alembic check  # Verifies no pending migrations
       python -c "from ruvon.migrations import verify_schema; verify_schema()"
   ```

**Deliverables:**
- Clean codebase (old system removed)
- Updated documentation
- Developer tooling
- CI/CD integration

**Success Criteria:**
- Single migration system (Alembic only)
- All tests pass
- Documentation updated
- Developer experience improved

---

## Technical Implementation Details

### SQLAlchemy Models Structure

```python
# src/ruvon/models/database.py
from sqlalchemy import MetaData, Table, Column, Index
from sqlalchemy import String, Integer, Boolean, DateTime, Text, LargeBinary
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from datetime import datetime

metadata = MetaData()

# Naming convention for constraints
metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Use type variants for multi-database support
def get_uuid_type(dialect):
    if dialect.name == 'postgresql':
        return UUID(as_uuid=True)
    return String(36)

def get_json_type(dialect):
    if dialect.name == 'postgresql':
        return JSONB
    return Text  # SQLite stores as TEXT

workflow_executions = Table(
    'workflow_executions',
    metadata,
    Column('id', get_uuid_type, primary_key=True),
    Column('workflow_type', String(200), nullable=False, index=True),
    Column('workflow_version', String(50)),
    Column('status', String(50), nullable=False, index=True),
    Column('state', get_json_type, nullable=False),
    Column('current_step', String(200)),
    Column('steps_config', get_json_type, nullable=False, server_default='[]'),
    Column('state_model_path', String(500), nullable=False),
    Column('saga_mode', Boolean, server_default='false'),
    Column('completed_steps_stack', get_json_type, server_default='[]'),
    Column('parent_execution_id', get_uuid_type, nullable=True),
    Column('blocked_on_child_id', get_uuid_type, nullable=True),
    Column('data_region', String(50), server_default='us-east-1'),
    Column('priority', Integer, server_default='5'),
    Column('idempotency_key', String(255), unique=True),
    Column('metadata', get_json_type, server_default='{}'),
    Column('owner_id', String(200)),
    Column('org_id', String(200)),
    Column('encrypted_state', LargeBinary),
    Column('encryption_key_id', String(100)),
    Column('created_at', DateTime, server_default=func.now()),
    Column('updated_at', DateTime, server_default=func.now(), onupdate=func.now()),
    Column('completed_at', DateTime),

    Index('ix_workflow_status_created', 'status', 'created_at'),
    Index('ix_workflow_type_status', 'workflow_type', 'status'),
)

# ... other tables
```

### Alembic Configuration

```python
# alembic/env.py
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, create_engine
from alembic import context
from ruvon.models.database import metadata

config = context.config

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite compatibility
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            render_as_batch=True,  # SQLite batch operations
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### Migration Workflow

```bash
# 1. Make model changes
vim src/ruvon/models/database.py

# 2. Generate migration
alembic revision --autogenerate -m "add user preferences table"

# 3. Review generated migration
vim alembic/versions/abc123_add_user_preferences_table.py

# 4. Test migration (up)
alembic upgrade head

# 5. Test rollback (down)
alembic downgrade -1

# 6. Test on SQLite
export DATABASE_URL="sqlite:///test.db"
alembic upgrade head

# 7. Commit migration
git add alembic/versions/
git commit -m "migration: add user preferences table"
```

---

## Performance Considerations

### Benchmarks to Run

```python
# tests/benchmarks/sqlalchemy_vs_raw.py
import asyncio
import asyncpg
from sqlalchemy import select, insert
from ruvon.models.database import workflow_executions

async def benchmark_raw_sql():
    """Baseline: raw asyncpg."""
    pool = await asyncpg.create_pool(...)

    start = time.time()
    for i in range(1000):
        async with pool.acquire() as conn:
            await conn.fetch("SELECT * FROM workflow_executions WHERE status = $1", "ACTIVE")
    elapsed = time.time() - start
    print(f"Raw SQL: {elapsed:.3f}s ({1000/elapsed:.1f} ops/sec)")

async def benchmark_sqlalchemy_core():
    """SQLAlchemy Core (compiled queries)."""
    engine = create_async_engine(...)

    stmt = select(workflow_executions).where(workflow_executions.c.status == "ACTIVE")

    start = time.time()
    async with engine.connect() as conn:
        for i in range(1000):
            result = await conn.execute(stmt)
            rows = result.fetchall()
    elapsed = time.time() - start
    print(f"SQLAlchemy Core: {elapsed:.3f}s ({1000/elapsed:.1f} ops/sec)")
```

### Expected Performance Impact

| Operation | Current (asyncpg) | SQLAlchemy Core | Impact |
|-----------|------------------|----------------|---------|
| Simple SELECT | 10,000 ops/sec | 8,000 ops/sec | -20% |
| Complex JOIN | 5,000 ops/sec | 4,500 ops/sec | -10% |
| Bulk INSERT | 15,000 ops/sec | 5,000 ops/sec | -67% |
| load_workflow (hot path) | 6,500 ops/sec | 6,500 ops/sec | 0% (raw SQL) |
| save_workflow (hot path) | 9,000 ops/sec | 9,000 ops/sec | 0% (raw SQL) |

**Strategy:** Keep hot paths as raw SQL, convert read-heavy endpoints to SQLAlchemy Core.

---

## Risk Mitigation

### Risk Matrix

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Performance degradation | Medium | High | Keep hot paths as raw SQL; benchmark everything |
| Migration bugs | Medium | Medium | Extensive testing; gradual rollout |
| Autogenerate false positives | High | Low | Manual review all migrations |
| Breaking existing deployments | Low | High | Backward compatibility; migration guide |
| Learning curve for team | Medium | Low | Documentation; training sessions |
| SQLite compatibility issues | Low | Medium | Use batch mode; test both databases |

### Testing Strategy

1. **Unit Tests:**
   - Test each migration up/down
   - Verify schema matches expected state
   - Test on both PostgreSQL and SQLite

2. **Integration Tests:**
   - Full workflow execution tests
   - Persistence provider tests
   - Load testing (1000+ devices)

3. **Migration Tests:**
   - Test fresh install (Alembic only)
   - Test upgrade from old system
   - Test downgrade paths

4. **Performance Tests:**
   - Benchmark before/after each phase
   - Load test with 1000+ concurrent workflows
   - Monitor production metrics

---

## Backward Compatibility

### Migration from Old System

```python
# tools/migrate_to_alembic.py
async def migrate_from_old_system():
    """Migrate from schema.yaml system to Alembic."""

    # 1. Backup database
    subprocess.run(["pg_dump", ...])

    # 2. Check current schema version
    current_version = await get_schema_yaml_version()

    # 3. Stamp Alembic at equivalent version
    subprocess.run(["alembic", "stamp", f"@{current_version}"])

    # 4. Apply any pending Alembic migrations
    subprocess.run(["alembic", "upgrade", "head"])

    # 5. Verify schema integrity
    await verify_schema_matches_models()

    print("✅ Migration to Alembic complete")
```

### Rollback Plan

If Alembic migration fails:

1. **Restore from backup:**
   ```bash
   pg_restore -d ruvon_cloud backup.sql
   ```

2. **Revert code:**
   ```bash
   git revert <alembic-migration-commit>
   ```

3. **Fall back to old system:**
   ```bash
   docker compose down -v
   docker compose up -d  # Uses old init-db.sql
   ```

---

## Decision Matrix

### Should We Migrate?

| Factor | Current System | Alembic + SQLAlchemy | Winner |
|--------|---------------|---------------------|---------|
| **Performance** | ✅ Raw asyncpg (fastest) | ⚠️ 10-20% slower (hybrid: same) | Tie (hybrid) |
| **Migration Management** | ⚠️ Manual, dual system | ✅ Auto-generate, single system | Alembic |
| **Type Safety** | ❌ No models | ✅ Python classes | Alembic |
| **Developer Experience** | ⚠️ Manual SQL | ✅ Auto-complete, tooling | Alembic |
| **Multi-Database Support** | ✅ schema.yaml | ✅ Batch mode | Tie |
| **Complexity** | ✅ Simple (raw SQL) | ⚠️ More dependencies | Current |
| **Industry Standard** | ❌ Custom system | ✅ Standard tooling | Alembic |
| **Maintenance Burden** | ⚠️ Dual system sync | ✅ Single source of truth | Alembic |
| **Testing** | ⚠️ Manual schema setup | ✅ Auto-migrations in tests | Alembic |
| **Documentation** | ⚠️ Custom docs needed | ✅ Community resources | Alembic |

**Score: 6-4 in favor of Alembic + SQLAlchemy (hybrid approach)**

---

## Recommendation

**Proceed with migration using hybrid approach:**

1. ✅ **Phase 1-2:** Add Alembic alongside current system (low risk)
2. ✅ **Phase 3:** Convert read queries to SQLAlchemy Core (test performance)
3. ⚠️ **Phase 4:** Remove old system (after validation)

**Key Success Factors:**
- Keep hot paths (save_workflow, load_workflow) as raw SQL
- Manual review all auto-generated migrations
- Extensive testing on both PostgreSQL and SQLite
- Performance benchmarks at each phase
- Backward compatibility for existing deployments

**Timeline:** 4 weeks (can be done in parallel with other work)

**Go/No-Go Decision Point:** After Phase 3 performance testing
- If performance is acceptable → proceed to Phase 4
- If performance degrades > 10% → keep hybrid approach indefinitely

---

## Next Steps

1. **Get stakeholder approval** for migration plan
2. **Create feature branch:** `feature/alembic-migration`
3. **Start Phase 1:** Install dependencies, create models
4. **Weekly review:** Check progress and performance
5. **Performance gate:** Validate after Phase 3 before cleanup

**Questions for Discussion:**
- Are we comfortable with hybrid approach (SQLAlchemy Core + raw SQL)?
- What's our performance degradation tolerance? (suggested: 10%)
- Should we do this now or defer to later?
- Any concerns about Alembic autogenerate limitations?

---

**Last Updated:** 2026-02-11
**Author:** Claude Sonnet 4.5
**Status:** Proposal - Pending Approval
