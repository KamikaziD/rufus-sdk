# Phase 3 Go/No-Go Decision: Alembic + SQLAlchemy Migration

**Date:** 2026-02-11
**Decision:** ✗ **NO-GO** for SQLAlchemy Core query layer
**Outcome:** Keep hybrid approach indefinitely

---

## Executive Summary

After benchmarking SQLAlchemy Core queries against raw SQL, the performance degradation exceeds our 10% threshold. **We recommend keeping raw SQL for all queries** while continuing to use SQLAlchemy models for Alembic migrations only.

---

## Benchmark Results

### Baseline Performance (Raw SQL)

| Operation | Mean | P95 | P99 | Throughput |
|-----------|------|-----|-----|------------|
| save_workflow | 0.447 ms | 0.498 ms | 0.654 ms | 2,238 ops/sec |
| load_workflow | 0.433 ms | 0.582 ms | 1.414 ms | 2,309 ops/sec |
| list_workflows | 0.986 ms | 1.095 ms | 1.856 ms | 1,015 ops/sec |

### SQLAlchemy Core Performance (list_workflows)

| Metric | Raw SQL | SQLAlchemy Core | Difference |
|--------|---------|-----------------|------------|
| **Mean** | 0.521 ms | 0.758 ms | **+45.4%** |
| **Median** | 0.510 ms | 0.722 ms | **+41.7%** |
| **P95** | 0.636 ms | 0.872 ms | **+37.1%** |
| **P99** | 1.393 ms | 1.862 ms | **+33.7%** |
| **Throughput** | 1,919 ops/sec | 1,320 ops/sec | **-31.2%** |

**Result:** 45% performance degradation - **FAIL**

---

## Technical Findings

### Why SQLAlchemy Core is Slower

1. **Query Compilation Overhead**
   - SQLAlchemy must parse, analyze, and compile the query AST
   - Even with caching, this adds ~0.2-0.3ms per query

2. **Parameter Binding Incompatibility**
   - SQLAlchemy uses `%(name)s` style parameters
   - asyncpg expects `$1, $2, $3` style parameters
   - Conversion or `literal_binds=True` adds significant overhead

3. **Abstraction Layers**
   - Additional Python objects (Select, Column, Table) vs raw strings
   - Memory allocation and GC pressure
   - Type checking and validation overhead

### What We Tried

1. ✗ **SQLAlchemy Core with literal_binds** - 45% slower
2. ✗ **SQLAlchemy Core with parameter extraction** - Syntax errors with asyncpg
3. ✗ **Query string caching** - Still 20-30% overhead from compilation

---

## Decision Rationale

### Go Criteria (Not Met)
- ✗ Performance degradation < 10%
- ✗ Seamless asyncpg integration
- ✗ Minimal code changes

### No-Go Justification
- **45% performance degradation** is unacceptable for hot paths
- Raw SQL is already **type-safe** through TypedDict and runtime validation
- **Alembic works fine** with SQLAlchemy models for migrations only
- Development velocity not significantly impacted by raw SQL

---

## Recommended Approach: Hybrid Model

### ✓ Use SQLAlchemy For (Phase 2 Complete)
- [x] Alembic migration generation
- [x] Schema definition (single source of truth)
- [x] Cross-database type mapping (PostgreSQL ↔ SQLite)
- [x] IDE autocomplete for table/column names

### ✓ Keep Raw SQL For (Current State)
- [x] All query operations (save, load, list, etc.)
- [x] Performance-critical paths
- [x] Complex queries with PostgreSQL-specific features
- [x] Direct asyncpg connection pool usage

---

## Deliverables Completed

### Phase 1 ✅
- SQLAlchemy models created (`src/rufus/db_schema/`)
- Dependencies added (sqlalchemy, alembic)
- Models match existing schema

### Phase 2 ✅
- Alembic initialized and configured
- Baseline migration created (047d1ed10688)
- 3 new tables added (workflow_audit_log, workflow_heartbeats, workflow_metrics)
- Dual database support (PostgreSQL + SQLite)
- Migration successfully applied

### Phase 3 ✅ (Decision Made)
- Performance benchmarks completed
- SQLAlchemy Core tested and measured
- Go/No-Go decision: **NO-GO**
- Hybrid approach validated

### Phase 4 ❌ (Not Proceeding)
- Will NOT remove old migration files
- Will NOT convert queries to SQLAlchemy
- Alembic and raw SQL coexist indefinitely

---

## Benefits Achieved

### ✓ From Alembic + SQLAlchemy Models
1. **Migration Management**
   - Auto-generate migrations: `alembic revision --autogenerate`
   - Version tracking in database
   - Rollback capability

2. **Schema Definition**
   - Single source of truth (`db_schema/database.py`)
   - Type-safe column references
   - Cross-database compatibility

3. **Developer Experience**
   - IDE autocomplete for table/column names
   - Type hints for schema objects
   - Clear migration history

### ✓ From Raw SQL (Retained)
1. **Performance**
   - Zero abstraction overhead
   - Direct asyncpg usage
   - Optimized query plans

2. **Flexibility**
   - PostgreSQL-specific features (LISTEN/NOTIFY, FOR UPDATE SKIP LOCKED)
   - Complex CTEs and window functions
   - Full control over query execution

3. **Simplicity**
   - No ORM learning curve
   - Transparent SQL in code reviews
   - Easy debugging

---

## Conclusion

The hybrid approach provides the **best of both worlds**:
- **Alembic** for migration management and schema evolution
- **Raw SQL** for runtime query performance

We achieve **100% of the migration management benefits** with **0% performance degradation** by keeping queries as raw SQL.

**Status:** Phase 3 complete. No further action required.

---

## Appendix: Benchmark Scripts

- `tests/benchmarks/phase3_benchmark.py` - Baseline raw SQL performance
- `tests/benchmarks/phase3_sqlalchemy_test.py` - SQLAlchemy Core comparison

**Run benchmarks:**
```bash
python tests/benchmarks/phase3_benchmark.py
python tests/benchmarks/phase3_sqlalchemy_test.py
```
