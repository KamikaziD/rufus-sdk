# Documentation & Functionality Alignment Plan
## Rufus SDK - Fresh Install Validation & Testing

**Created**: 2026-02-11
**Status**: Ready for Review
**Goal**: Ensure documentation matches reality and fresh installs work flawlessly

---

## Executive Summary

This plan validates the Rufus SDK installation, migration, and testing process from a **clean slate** (no existing database, no containers). We'll follow the documentation step-by-step, identify gaps, fix issues, and update documentation for accuracy.

### Scope
1. ✅ Fresh pip install of Rufus SDK
2. ✅ Docker container setup (PostgreSQL + Rufus Server)
3. ✅ Database migrations (both SQLite and PostgreSQL)
4. ✅ Test data seeding for load tests
5. ✅ Documentation accuracy verification
6. ✅ Fix any broken workflows

---

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
2. [Fresh Install Workflow](#2-fresh-install-workflow)
3. [Migration Strategy Validation](#3-migration-strategy-validation)
4. [Test Data Seeding](#4-test-data-seeding)
5. [Issues Identified](#5-issues-identified)
6. [Fixes Required](#6-fixes-required)
7. [Documentation Updates](#7-documentation-updates)
8. [Validation Checkpoints](#8-validation-checkpoints)
9. [Execution Timeline](#9-execution-timeline)

---

## 1. Current State Assessment

### 1.1 Existing Files & Structure

**Installation Files**:
- ✅ `pyproject.toml` - Poetry-based package configuration
- ✅ `requirements.txt` - Pip dependencies (71 lines)
- ✅ `setup.py` - **MISSING** (relies on pyproject.toml only)

**Docker Configuration**:
- ✅ `docker/docker-compose.yml` - PostgreSQL + Rufus Server
- ✅ `docker/Dockerfile.server` - FastAPI server image
- ✅ `docker/init-db.sql` - Database initialization (850+ lines)
- ⚠️ `.env.example` - Present but not referenced in docker-compose.yml

**Migrations**:
- ✅ `migrations/schema.yaml` - Unified schema definition (v2.0.0)
- ✅ `migrations/002_postgres_standardized.sql` - PostgreSQL migration
- ✅ `migrations/003_sqlite_fixed.sql` - SQLite migration
- ✅ `tools/migrate.py` - Migration manager
- ⚠️ **Dual system**: Docker uses `init-db.sql`, CLI uses `migrations/`

**Documentation**:
- ✅ `README.md` - Project overview
- ✅ `CLAUDE.md` - Comprehensive guide (55KB)
- ✅ `QUICKSTART.md` - 2-minute installation guide (397 lines)
- ✅ `ENV_CONFIGURATION.md` - Environment variable guide
- ⚠️ No `INSTALL.md` or `SETUP.md` (relies on QUICKSTART.md)

**Test Infrastructure**:
- ✅ `tests/cli/conftest.py` - Pytest fixtures with in-memory SQLite
- ✅ `tests/load/run_load_test.py` - Load testing suite
- ✅ `tests/load/device_simulator.py` - Edge device simulation
- ❌ **No seed data scripts** - tests use ad-hoc data generation

**Examples**:
- ✅ `examples/sqlite_task_manager/` - Zero-setup demo
- ✅ `examples/loan_application/` - Complex workflow
- ✅ `examples/payment_terminal/` - POS terminal
- ✅ `examples/edge_deployment/` - Edge device setup

### 1.2 Key Findings

**What Works Well**:
1. ✅ SQLite auto-initialization (`auto_init=True`) enables zero-setup development
2. ✅ Unified schema definition (`schema.yaml`) with type mappings
3. ✅ CLI commands (`rufus db init`, `rufus db migrate`) are user-friendly
4. ✅ Docker setup includes health checks
5. ✅ Comprehensive examples for different use cases

**What Needs Clarification**:
1. ⚠️ **Dual migration systems**: `docker/init-db.sql` vs. `migrations/*.sql`
   - Which one is authoritative?
   - When to use which?
   - Are they in sync?

2. ⚠️ **No explicit seed data mechanism**:
   - Load tests generate data on-the-fly
   - No fixtures for common test scenarios
   - No "default admin user" or "demo data" option

3. ⚠️ **Docker environment variables**:
   - `docker-compose.yml` hardcodes DB credentials
   - `.env.example` exists but not used by Docker
   - Inconsistent with ENV_CONFIGURATION.md guidance

4. ⚠️ **Migration execution order**:
   - Docker runs `init-db.sql` on container start
   - CLI expects to run migrations manually
   - What if Docker already initialized schema?

---

## 2. Fresh Install Workflow

### 2.1 Clean Slate Prerequisites

**Starting State**:
```bash
# Verify clean state
docker ps -a  # Should show no rufus containers
docker volume ls  # Should show no rufus volumes
ls ~/.rufus/  # Should not exist or be empty
ls /Users/kim/PycharmProjects/rufus/.venv/  # Should not exist
```

**System Requirements**:
- Python 3.11+ installed
- Docker Desktop running
- Git repository cloned
- No existing Rufus configuration

### 2.2 Installation Path 1: Development (SQLite)

**Goal**: Get working Rufus environment in <5 minutes

```bash
# Step 1: Navigate to project
cd /Users/kim/PycharmProjects/rufus

# Step 2: Install dependencies
pip install -r requirements.txt

# Step 3: Verify installation
python -c "import rufus; print(rufus.__version__)"

# Step 4: Run SQLite example (auto-initializes database)
python examples/sqlite_task_manager/simple_demo.py

# Expected Output:
# ✓ SQLite database auto-created at workflow.db
# ✓ Migrations applied automatically
# ✓ Workflow executes successfully
# ✓ Output shows task progression
```

**Success Criteria**:
- ✅ No manual migration commands needed
- ✅ Example runs without errors
- ✅ Database file created with correct schema
- ✅ Workflow completes with `COMPLETED` status

**Validation Commands**:
```bash
# Check database was created
ls -lh examples/sqlite_task_manager/workflow.db

# Check schema was applied
sqlite3 examples/sqlite_task_manager/workflow.db ".tables"
# Expected: workflow_executions, tasks, workflow_audit_log, etc.

# Check workflow completed
sqlite3 examples/sqlite_task_manager/workflow.db \
  "SELECT status FROM workflow_executions ORDER BY created_at DESC LIMIT 1;"
# Expected: COMPLETED
```

### 2.3 Installation Path 2: Docker + PostgreSQL

**Goal**: Production-like environment with PostgreSQL

```bash
# Step 1: Navigate to Docker directory
cd /Users/kim/PycharmProjects/rufus/docker

# Step 2: Ensure no existing containers
docker compose down -v  # Remove containers AND volumes

# Step 3: Start containers
docker compose up -d

# Step 4: Wait for database initialization
docker compose logs -f postgres
# Wait for: "database system is ready to accept connections"

# Step 5: Verify database schema
docker exec -it rufus-postgres psql -U postgres -d rufus_cloud -c "\dt"

# Expected Output:
# List of relations showing: workflow_executions, edge_devices, etc.

# Step 6: Verify Rufus server
curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

**Success Criteria**:
- ✅ PostgreSQL container starts successfully
- ✅ Database `rufus_cloud` created
- ✅ Schema applied via `init-db.sql`
- ✅ Rufus server responds to health checks
- ✅ All tables present in database

**Validation Commands**:
```bash
# Check container health
docker compose ps
# Expected: All services "Up" and "healthy"

# Check database schema version
docker exec -it rufus-postgres psql -U postgres -d rufus_cloud \
  -c "SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 1;"
# Expected: Latest migration version

# Check connection from host
psql "postgresql://postgres:postgres@localhost:5433/rufus_cloud" -c "\dt"
```

### 2.4 Installation Path 3: CLI-Based Setup

**Goal**: Manual control over database initialization

```bash
# Step 1: Install Rufus CLI
pip install -r requirements.txt

# Step 2: Configure database URL
export RUFUS_DB_URL="postgresql://postgres:postgres@localhost:5433/rufus_cloud"
# OR: Create ~/.rufus/config.yaml with database URL

# Step 3: Initialize database
rufus db init --db-url "$RUFUS_DB_URL"

# Expected Output:
# ✓ Connected to database
# ✓ Schema migrations table created
# ✓ Applying migration 002_postgres_standardized.sql
# ✓ Database initialized successfully

# Step 4: Verify initialization
rufus db status --db-url "$RUFUS_DB_URL"

# Expected Output:
# Database: rufus_cloud (PostgreSQL)
# Applied migrations: 002_postgres_standardized.sql
# Schema version: 2.0.0
# Status: Up to date
```

**Success Criteria**:
- ✅ `rufus db init` completes without errors
- ✅ Migrations applied in correct order
- ✅ Schema matches `schema.yaml` definition
- ✅ `schema_migrations` table tracks versions

---

## 3. Migration Strategy Validation

### 3.1 Current Migration Systems

**System 1: Docker Init Script**
- **File**: `docker/init-db.sql`
- **Size**: 850+ lines
- **Purpose**: Initialize PostgreSQL on container first start
- **Trigger**: Docker entrypoint script
- **Pros**: Zero manual steps for Docker users
- **Cons**: Separate from unified migrations

**System 2: Unified Migrations**
- **Files**: `migrations/002_postgres_standardized.sql`, `003_sqlite_fixed.sql`
- **Source**: Generated from `migrations/schema.yaml`
- **Purpose**: Consistent schema across SQLite and PostgreSQL
- **Trigger**: Manual (`rufus db migrate`) or auto (SQLite `auto_init`)
- **Pros**: Single source of truth, version tracking
- **Cons**: Requires manual execution for PostgreSQL

### 3.2 Migration Comparison

**Task**: Compare `docker/init-db.sql` with `migrations/002_postgres_standardized.sql`

```bash
# Extract table definitions from both files
grep "CREATE TABLE" docker/init-db.sql | sort > /tmp/docker_tables.txt
grep "CREATE TABLE" migrations/002_postgres_standardized.sql | sort > /tmp/migration_tables.txt

# Compare
diff /tmp/docker_tables.txt /tmp/migration_tables.txt
```

**Expected Differences**:
- `docker/init-db.sql`: Includes edge-specific tables (edge_devices, device_commands, webhooks)
- `migrations/002_postgres_standardized.sql`: Core workflow tables only

**Analysis**:
- ⚠️ `docker/init-db.sql` is a **superset** of migrations
- ⚠️ Includes Rufus Edge and Rufus Server tables not in core SDK
- ✅ Core workflow tables are consistent

### 3.3 Recommended Migration Strategy

**Proposal**: Consolidate into single unified migration system

**Option A: Docker Uses Migrations (Recommended)**
```dockerfile
# In docker/docker-compose.yml, replace init-db.sql with migration runner
services:
  postgres:
    # ... existing config ...
    command: postgres
    # Remove init-db.sql

  rufus_server:
    depends_on:
      postgres:
        condition: service_healthy
    command: >
      sh -c "
        rufus db init --db-url postgresql://postgres:postgres@postgres:5432/rufus_cloud &&
        uvicorn rufus_server.main:app --host 0.0.0.0 --port 8000
      "
```

**Benefits**:
- ✅ Single source of truth (migrations/)
- ✅ Version tracking in schema_migrations table
- ✅ Consistent with CLI workflow
- ✅ Easier to maintain

**Option B: Keep Dual System (Current)**
- Keep `docker/init-db.sql` for Docker
- Keep `migrations/` for CLI and SQLite
- Document clearly when to use which

### 3.4 Migration Execution Validation

**Test 1: Fresh PostgreSQL Database**
```bash
# Drop and recreate database
docker exec -it rufus-postgres psql -U postgres -c "DROP DATABASE IF EXISTS rufus_cloud;"
docker exec -it rufus-postgres psql -U postgres -c "CREATE DATABASE rufus_cloud;"

# Run migration via CLI
rufus db init --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud"

# Verify schema
docker exec -it rufus-postgres psql -U postgres -d rufus_cloud -c "\dt"

# Expected: All core workflow tables present
```

**Test 2: SQLite Auto-Init**
```bash
# Remove existing database
rm -f /tmp/test_rufus.db

# Create persistence provider with auto_init=True
python3 << 'EOF'
import asyncio
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

async def test():
    persistence = SQLitePersistenceProvider(db_path="/tmp/test_rufus.db", auto_init=True)
    await persistence.initialize()
    print("✓ Database initialized automatically")

asyncio.run(test())
EOF

# Verify schema
sqlite3 /tmp/test_rufus.db ".tables"
# Expected: workflow_executions, tasks, workflow_audit_log, etc.
```

**Test 3: Migration Idempotency**
```bash
# Run migration twice - should not error
rufus db migrate --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud"
rufus db migrate --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud"

# Expected: Second run shows "Already up to date"
```

---

## 4. Test Data Seeding

### 4.1 Current Test Data Approach

**Load Tests** (`tests/load/run_load_test.py`):
- Generates data on-the-fly using `device_simulator.py`
- Creates edge devices, transactions, workflows dynamically
- No pre-seeded data required

**Unit Tests** (`tests/cli/conftest.py`):
- Use in-memory SQLite (`:memory:`)
- Create fixtures per-test
- No persistent seed data

**Issue**: No mechanism for seeding **default data** for manual testing or demos.

### 4.2 Seed Data Requirements

**What Should Be Seeded**:

1. **Demo Workflows** (for `sqlite_task_manager` example):
   - Pre-created workflow definitions
   - Sample workflow executions (completed, in-progress, failed)
   - Audit logs showing workflow history

2. **Load Test Prerequisites** (for `tests/load/`):
   - Registration keys for device enrollment
   - Artifact versions for model updates
   - Webhook endpoints for testing

3. **Edge Device Fixtures** (for Docker/PostgreSQL):
   - 5-10 sample edge devices (registered, active)
   - Device commands (pending, executed)
   - Configuration versions

4. **Admin/Demo Users** (if implementing authentication):
   - Admin user with full permissions
   - Demo user with read-only access

### 4.3 Seed Data Implementation

**Approach**: Create `tools/seed_data.py` script

```python
# tools/seed_data.py
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider


async def seed_demo_workflows(persistence):
    """Seed sample workflows for demo/testing."""
    from datetime import datetime
    import uuid

    # Sample workflow 1: Completed task
    workflow_id = uuid.uuid4()
    await persistence.save_workflow(workflow_id, {
        "id": str(workflow_id),
        "workflow_type": "TaskManagement",
        "status": "COMPLETED",
        "state": {"task_name": "Setup development environment", "status": "done"},
        "created_at": datetime.now().isoformat(),
        "owner_id": "demo-user"
    })

    # Sample workflow 2: In-progress
    workflow_id2 = uuid.uuid4()
    await persistence.save_workflow(workflow_id2, {
        "id": str(workflow_id2),
        "workflow_type": "TaskManagement",
        "status": "ACTIVE",
        "state": {"task_name": "Review pull request", "status": "in_progress"},
        "created_at": datetime.now().isoformat(),
        "owner_id": "demo-user"
    })

    print(f"✓ Seeded {2} demo workflows")


async def seed_edge_devices(persistence):
    """Seed sample edge devices (PostgreSQL only)."""
    # Only seed if edge_devices table exists
    try:
        await persistence.conn.execute("""
            INSERT INTO edge_devices (device_id, registration_key, status, last_heartbeat)
            VALUES
                ('device-001', 'rufus-registration-key', 'active', NOW()),
                ('device-002', 'rufus-registration-key', 'active', NOW()),
                ('device-003', 'rufus-registration-key', 'inactive', NOW() - INTERVAL '1 day')
            ON CONFLICT (device_id) DO NOTHING;
        """)
        print(f"✓ Seeded 3 edge devices")
    except Exception as e:
        print(f"⚠ Skipping edge devices (table not found): {e}")


async def seed_registration_keys(persistence):
    """Seed registration keys for load tests."""
    # Create default registration key
    try:
        await persistence.conn.execute("""
            INSERT INTO registration_keys (key_value, max_uses, expires_at)
            VALUES ('rufus-registration-key', 1000, NOW() + INTERVAL '1 year')
            ON CONFLICT (key_value) DO NOTHING;
        """)
        print(f"✓ Seeded registration keys")
    except Exception as e:
        print(f"⚠ Skipping registration keys (table not found): {e}")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Seed Rufus database with test data")
    parser.add_argument("--db-url", required=True, help="Database URL")
    parser.add_argument("--type", choices=["all", "workflows", "edge", "keys"], default="all")
    args = parser.parse_args()

    # Determine database type
    if args.db_url.startswith("sqlite"):
        persistence = SQLitePersistenceProvider(db_path=args.db_url.replace("sqlite:///", ""))
    elif args.db_url.startswith("postgresql"):
        persistence = PostgresPersistenceProvider(db_url=args.db_url)
    else:
        raise ValueError("Unsupported database URL")

    await persistence.initialize()

    print(f"Seeding database: {args.db_url}")

    if args.type in ["all", "workflows"]:
        await seed_demo_workflows(persistence)

    if args.type in ["all", "edge"]:
        await seed_edge_devices(persistence)

    if args.type in ["all", "keys"]:
        await seed_registration_keys(persistence)

    await persistence.close()
    print("✓ Seeding complete")


if __name__ == "__main__":
    asyncio.run(main())
```

**Usage**:
```bash
# Seed SQLite database
python tools/seed_data.py --db-url "sqlite:///workflow.db" --type all

# Seed PostgreSQL (Docker)
python tools/seed_data.py \
  --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \
  --type all
```

### 4.4 Load Test Seeding Integration

**Modify `tests/load/run_load_test.py` to check for seed data**:

```python
# In tests/load/run_load_test.py, add pre-flight check

async def ensure_seed_data(db_url: str):
    """Ensure required seed data exists before running load tests."""
    persistence = PostgresPersistenceProvider(db_url=db_url)
    await persistence.initialize()

    # Check for registration key
    result = await persistence.conn.fetchval(
        "SELECT COUNT(*) FROM registration_keys WHERE key_value = 'rufus-registration-key'"
    )

    if result == 0:
        print("⚠ No registration key found. Seeding default data...")
        await persistence.conn.execute("""
            INSERT INTO registration_keys (key_value, max_uses, expires_at)
            VALUES ('rufus-registration-key', 10000, NOW() + INTERVAL '1 year');
        """)
        print("✓ Seeded registration key")

    await persistence.close()


# In main(), before running tests:
if args.db_url:
    await ensure_seed_data(args.db_url)
```

### 4.5 Seed Data Validation

**Test 1: Verify Demo Workflows**
```bash
# Run seed script
python tools/seed_data.py --db-url "sqlite:///demo.db" --type workflows

# Verify data
sqlite3 demo.db "SELECT workflow_type, status FROM workflow_executions;"

# Expected Output:
# TaskManagement|COMPLETED
# TaskManagement|ACTIVE
```

**Test 2: Verify Registration Keys**
```bash
# Seed PostgreSQL
python tools/seed_data.py \
  --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \
  --type keys

# Verify
psql "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \
  -c "SELECT key_value, max_uses FROM registration_keys;"

# Expected Output:
# key_value              | max_uses
# ---------------------- | --------
# rufus-registration-key | 1000
```

---

## 5. Issues Identified

### 5.1 Critical Issues

**Issue #1: Dual Migration Systems**
- **Severity**: Medium
- **Description**: `docker/init-db.sql` and `migrations/*.sql` serve same purpose but diverge
- **Impact**: Confusion for users, potential schema drift
- **Status**: Needs decision (consolidate or document clearly)

**Issue #2: No Seed Data Mechanism**
- **Severity**: Medium
- **Description**: Load tests assume seed data exists but provide no seeding script
- **Impact**: Load tests may fail on fresh install, manual testing difficult
- **Status**: Needs implementation (`tools/seed_data.py`)

**Issue #3: Docker Environment Variables**
- **Severity**: Low
- **Description**: `.env.example` exists but not used by `docker-compose.yml`
- **Impact**: Inconsistent with ENV_CONFIGURATION.md guidance
- **Status**: Needs update to docker-compose.yml

### 5.2 Documentation Gaps

**Gap #1: Migration System Explanation**
- **File**: CLAUDE.md, README.md
- **Issue**: Doesn't explain Docker vs. CLI migration difference
- **Recommendation**: Add section "Database Initialization Strategies"

**Gap #2: Fresh Install Workflow**
- **File**: QUICKSTART.md
- **Issue**: Assumes user knows to use SQLite OR Docker, not clear decision path
- **Recommendation**: Add flowchart for installation path selection

**Gap #3: Load Test Prerequisites**
- **File**: tests/load/README.md (if exists)
- **Issue**: Doesn't document seed data requirements
- **Recommendation**: Add "Setup" section with seeding instructions

**Gap #4: Docker Troubleshooting**
- **File**: docker/README.md (missing)
- **Issue**: No troubleshooting guide for Docker setup issues
- **Recommendation**: Create docker/README.md with common issues

### 5.3 Minor Issues

**Issue #4: SQLite Auto-Init Parameter**
- **Severity**: Low
- **Description**: `auto_init=True` is default but not documented prominently
- **Impact**: Users may not understand why no migration command needed
- **Status**: Add to QUICKSTART.md

**Issue #5: Poetry vs. Pip Confusion**
- **Severity**: Low
- **Description**: Project uses `pyproject.toml` (Poetry) but docs say `pip install -r requirements.txt`
- **Impact**: Developers may use wrong tool
- **Status**: Clarify in README.md

---

## 6. Fixes Required

### 6.1 Code Fixes

**Fix #1: Create Seed Data Script**
- **File**: `tools/seed_data.py` (new file)
- **Implementation**: See Section 4.3
- **Testing**: Verify on both SQLite and PostgreSQL
- **Timeline**: 2 hours

**Fix #2: Update Docker Compose for Environment Variables**
```yaml
# docker/docker-compose.yml
services:
  postgres:
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
      POSTGRES_DB: ${POSTGRES_DB:-rufus_cloud}
    ports:
      - "${POSTGRES_PORT:-5433}:5432"
```

- **File**: `docker/docker-compose.yml`
- **Testing**: Verify with and without .env file
- **Timeline**: 30 minutes

**Fix #3: Add Seed Data Check to Load Tests**
```python
# tests/load/run_load_test.py
async def main():
    # Add after argument parsing
    if args.db_url:
        await ensure_seed_data(args.db_url)

    # ... rest of main()
```

- **File**: `tests/load/run_load_test.py`
- **Testing**: Run load test on fresh database
- **Timeline**: 1 hour

**Fix #4: Consolidate Migration Systems (Optional)**
- **Approach**: Replace `docker/init-db.sql` with migration runner
- **Complexity**: Medium (requires Docker entrypoint changes)
- **Timeline**: 4 hours
- **Decision**: Defer to Phase 2 (document dual system for now)

### 6.2 Documentation Fixes

**Fix #5: Add Migration Systems Section to CLAUDE.md**
```markdown
## Database Initialization Strategies

Rufus supports three database initialization approaches:

### 1. SQLite Auto-Initialization (Recommended for Development)
SQLite databases auto-initialize on first use:

\`\`\`python
persistence = SQLitePersistenceProvider(db_path="workflow.db", auto_init=True)
await persistence.initialize()  # Schema created automatically
\`\`\`

**When to use**: Development, testing, demos

### 2. Docker Initialization (Recommended for Production)
Docker containers initialize PostgreSQL via init-db.sql:

\`\`\`bash
docker compose up -d  # Schema created on first start
\`\`\`

**When to use**: Production deployments, Docker-based development

### 3. CLI-Based Migration (Advanced)
Manual control via CLI commands:

\`\`\`bash
rufus db init --db-url postgresql://localhost/rufus
\`\`\`

**When to use**: Custom deployments, migration troubleshooting
```

- **File**: `CLAUDE.md` (Section: Database Schema Management)
- **Timeline**: 1 hour

**Fix #6: Update QUICKSTART.md with Installation Decision Tree**
```markdown
## Choose Your Installation Path

**Path 1: Quick Demo (2 minutes)**
- Use SQLite (no setup required)
- Run: `python examples/sqlite_task_manager/simple_demo.py`
- Best for: First-time users, demos

**Path 2: Full Development (5 minutes)**
- Use Docker + PostgreSQL
- Run: `cd docker && docker compose up -d`
- Best for: Active development, production-like testing

**Path 3: Custom Setup (10 minutes)**
- Manual database configuration
- Use: `rufus db init`
- Best for: Advanced users, custom deployments
```

- **File**: `QUICKSTART.md` (Section 1)
- **Timeline**: 1 hour

**Fix #7: Create docker/README.md**
```markdown
# Rufus Docker Setup

## Quick Start

\`\`\`bash
docker compose up -d
curl http://localhost:8000/health  # Should return {"status": "healthy"}
\`\`\`

## Troubleshooting

### Port 5433 Already in Use
\`\`\`bash
# Check what's using the port
lsof -i :5433

# Change port in docker-compose.yml or stop conflicting service
\`\`\`

### Database Not Initializing
\`\`\`bash
# Check logs
docker compose logs postgres

# Manually initialize
docker exec -it rufus-postgres psql -U postgres -d rufus_cloud -f /docker-entrypoint-initdb.d/init-db.sql
\`\`\`

### Containers Fail Health Checks
\`\`\`bash
# Increase health check timeout in docker-compose.yml
healthcheck:
  timeout: 10s
  retries: 5
\`\`\`
```

- **File**: `docker/README.md` (new file)
- **Timeline**: 1 hour

**Fix #8: Add Load Test Setup Section**
```markdown
# Load Testing Setup

## Prerequisites

1. **Database Seeding**:
   \`\`\`bash
   python tools/seed_data.py --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud"
   \`\`\`

2. **Environment Variables**:
   \`\`\`bash
   export RUFUS_DB_URL="postgresql://postgres:postgres@localhost:5433/rufus_cloud"
   export RUFUS_REGISTRATION_KEY="rufus-registration-key"
   \`\`\`

3. **Run Tests**:
   \`\`\`bash
   python tests/load/run_load_test.py --all --devices 100
   \`\`\`
```

- **File**: `tests/load/README.md` (new file)
- **Timeline**: 30 minutes

---

## 7. Documentation Updates

### 7.1 README.md Updates

**Current**: 150+ lines, focuses on problem/solution comparison
**Needed**: Add "Quick Start" section at top

```markdown
# Rufus SDK

## Quick Start

\`\`\`bash
# Install
pip install -r requirements.txt

# Run demo (SQLite, zero setup)
python examples/sqlite_task_manager/simple_demo.py

# Or use Docker (PostgreSQL)
cd docker && docker compose up -d
\`\`\`

[Full installation guide →](QUICKSTART.md)

## Problem Statement
...
```

### 7.2 CLAUDE.md Updates

**Section to Add**: "Fresh Install Validation"

```markdown
## Fresh Install Validation

To verify your Rufus installation:

1. **SQLite (Development)**:
   \`\`\`bash
   python examples/sqlite_task_manager/simple_demo.py
   # Expected: Workflow completes successfully
   \`\`\`

2. **Docker (Production)**:
   \`\`\`bash
   cd docker && docker compose up -d
   curl http://localhost:8000/health
   # Expected: {"status": "healthy"}
   \`\`\`

3. **CLI Commands**:
   \`\`\`bash
   rufus --version
   rufus config show
   # Expected: Config displayed without errors
   \`\`\`
```

### 7.3 ENV_CONFIGURATION.md Updates

**Add Docker Section**:

```markdown
## Docker Environment Variables

Docker Compose supports environment variable substitution:

\`\`\`yaml
# docker-compose.yml
services:
  postgres:
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
\`\`\`

Create `.env` file in `docker/` directory:

\`\`\`bash
# docker/.env
POSTGRES_PASSWORD=secure_password_here
POSTGRES_PORT=5433
\`\`\`

Docker will automatically load `.env` on `docker compose up`.
```

---

## 8. Validation Checkpoints

### 8.1 Checkpoint 1: Fresh Install (SQLite)

**Test**: Clean slate → working SQLite example

```bash
#!/bin/bash
set -e

echo "=== Checkpoint 1: SQLite Fresh Install ==="

# Clean slate
rm -rf /tmp/rufus_test
mkdir -p /tmp/rufus_test
cd /tmp/rufus_test

# Clone repo (or use existing)
git clone https://github.com/yourorg/rufus.git .

# Install
pip install -r requirements.txt

# Run example
python examples/sqlite_task_manager/simple_demo.py

# Validate
if [ -f "examples/sqlite_task_manager/workflow.db" ]; then
  echo "✓ Database created"
else
  echo "✗ Database not created"
  exit 1
fi

# Check schema
tables=$(sqlite3 examples/sqlite_task_manager/workflow.db ".tables")
if [[ "$tables" == *"workflow_executions"* ]]; then
  echo "✓ Schema applied"
else
  echo "✗ Schema not applied"
  exit 1
fi

echo "✓ Checkpoint 1 PASSED"
```

**Expected Duration**: 3-5 minutes
**Success Criteria**: Script exits with code 0

### 8.2 Checkpoint 2: Docker Setup

**Test**: Clean Docker → working PostgreSQL

```bash
#!/bin/bash
set -e

echo "=== Checkpoint 2: Docker Setup ==="

cd /Users/kim/PycharmProjects/rufus/docker

# Clean slate
docker compose down -v

# Start containers
docker compose up -d

# Wait for health checks
echo "Waiting for services to be healthy..."
timeout 60 bash -c 'until [ "$(docker compose ps --format json | jq -r ".[] | select(.Service == \"postgres\") | .Health")" == "healthy" ]; do sleep 2; done'

# Verify database
docker exec rufus-postgres psql -U postgres -d rufus_cloud -c "\dt" > /tmp/tables.txt

if grep -q "workflow_executions" /tmp/tables.txt; then
  echo "✓ Database schema initialized"
else
  echo "✗ Database schema not initialized"
  exit 1
fi

# Verify server
response=$(curl -s http://localhost:8000/health)
if [[ "$response" == *"healthy"* ]]; then
  echo "✓ Rufus server responding"
else
  echo "✗ Rufus server not responding"
  exit 1
fi

echo "✓ Checkpoint 2 PASSED"
```

**Expected Duration**: 2-3 minutes
**Success Criteria**: Script exits with code 0

### 8.3 Checkpoint 3: CLI Migrations

**Test**: Manual migration via CLI

```bash
#!/bin/bash
set -e

echo "=== Checkpoint 3: CLI Migrations ==="

# Use Docker PostgreSQL instance
export RUFUS_DB_URL="postgresql://postgres:postgres@localhost:5433/rufus_test"

# Create fresh database
docker exec rufus-postgres psql -U postgres -c "DROP DATABASE IF EXISTS rufus_test;"
docker exec rufus-postgres psql -U postgres -c "CREATE DATABASE rufus_test;"

# Run migration
rufus db init --db-url "$RUFUS_DB_URL"

# Verify status
rufus db status --db-url "$RUFUS_DB_URL" > /tmp/status.txt

if grep -q "Up to date" /tmp/status.txt; then
  echo "✓ Migrations applied"
else
  echo "✗ Migrations not applied"
  exit 1
fi

# Verify schema
docker exec rufus-postgres psql -U postgres -d rufus_test -c "\dt" > /tmp/tables.txt
if grep -q "workflow_executions" /tmp/tables.txt; then
  echo "✓ Schema correct"
else
  echo "✗ Schema incorrect"
  exit 1
fi

echo "✓ Checkpoint 3 PASSED"
```

**Expected Duration**: 1-2 minutes
**Success Criteria**: Script exits with code 0

### 8.4 Checkpoint 4: Seed Data

**Test**: Seed data script execution

```bash
#!/bin/bash
set -e

echo "=== Checkpoint 4: Seed Data ==="

# Create seed data script first (see Fix #1)
python tools/seed_data.py --db-url "sqlite:///test_seed.db" --type all

# Verify workflows
workflows=$(sqlite3 test_seed.db "SELECT COUNT(*) FROM workflow_executions;")
if [ "$workflows" -ge 2 ]; then
  echo "✓ Workflows seeded ($workflows found)"
else
  echo "✗ Workflows not seeded ($workflows found, expected >= 2)"
  exit 1
fi

# Verify registration keys (PostgreSQL only - will skip for SQLite)
python tools/seed_data.py \
  --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \
  --type keys

# Check key exists
key_count=$(docker exec rufus-postgres psql -U postgres -d rufus_cloud -t -c \
  "SELECT COUNT(*) FROM registration_keys WHERE key_value = 'rufus-registration-key';")

if [ "$key_count" -ge 1 ]; then
  echo "✓ Registration key seeded"
else
  echo "✗ Registration key not seeded"
  exit 1
fi

echo "✓ Checkpoint 4 PASSED"
```

**Expected Duration**: 1-2 minutes
**Success Criteria**: Script exits with code 0

### 8.5 Checkpoint 5: Load Test

**Test**: Load test execution with seed data

```bash
#!/bin/bash
set -e

echo "=== Checkpoint 5: Load Test ==="

# Ensure seed data exists
python tools/seed_data.py \
  --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \
  --type all

# Run mini load test (10 devices, 60 seconds)
cd tests/load
python run_load_test.py \
  --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud" \
  --devices 10 \
  --duration 60 \
  --scenario heartbeat

# Check results
if [ -f "results/scale_10/heartbeat_results.json" ]; then
  echo "✓ Load test completed"

  # Verify success rate
  success_rate=$(jq -r '.success_rate' results/scale_10/heartbeat_results.json)
  if (( $(echo "$success_rate > 0.95" | bc -l) )); then
    echo "✓ Success rate acceptable ($success_rate)"
  else
    echo "⚠ Success rate low ($success_rate)"
  fi
else
  echo "✗ Load test did not complete"
  exit 1
fi

echo "✓ Checkpoint 5 PASSED"
```

**Expected Duration**: 2-3 minutes
**Success Criteria**: Script exits with code 0, success rate >95%

---

## 9. Execution Timeline

### Phase 1: Preparation (Day 1, 2-3 hours)

**Tasks**:
1. Review this plan with team
2. Set up clean test environment
3. Document current state (screenshots, config files)
4. Create backup of existing data (if any)

**Deliverables**:
- ✅ Approved plan
- ✅ Clean test VM or environment
- ✅ Backup of current state

### Phase 2: Code Fixes (Day 1-2, 8 hours)

**Tasks**:
1. Create `tools/seed_data.py` (2 hours)
2. Update `docker-compose.yml` for env vars (30 min)
3. Add seed data check to load tests (1 hour)
4. Test all fixes on clean environment (2 hours)
5. Code review and adjustments (2.5 hours)

**Deliverables**:
- ✅ `tools/seed_data.py` implemented and tested
- ✅ Docker env vars working
- ✅ Load tests self-seeding
- ✅ All unit tests passing

### Phase 3: Documentation Updates (Day 2-3, 6 hours)

**Tasks**:
1. Update CLAUDE.md with migration strategies section (1 hour)
2. Update QUICKSTART.md with decision tree (1 hour)
3. Create `docker/README.md` (1 hour)
4. Create `tests/load/README.md` (30 min)
5. Update README.md with Quick Start (30 min)
6. Update ENV_CONFIGURATION.md with Docker section (30 min)
7. Review and edit all documentation (1.5 hours)

**Deliverables**:
- ✅ All documentation files updated
- ✅ Consistent terminology across docs
- ✅ Working links and references

### Phase 4: Validation (Day 3, 4 hours)

**Tasks**:
1. Run Checkpoint 1: SQLite Fresh Install (30 min)
2. Run Checkpoint 2: Docker Setup (30 min)
3. Run Checkpoint 3: CLI Migrations (30 min)
4. Run Checkpoint 4: Seed Data (30 min)
5. Run Checkpoint 5: Load Test (1 hour)
6. Fix any issues found (1 hour)
7. Re-run failed checkpoints (optional)

**Deliverables**:
- ✅ All checkpoints passing
- ✅ Validation report documenting results
- ✅ Known issues list (if any)

### Phase 5: Final Review (Day 3-4, 2 hours)

**Tasks**:
1. Update this plan with results
2. Document lessons learned
3. Create "Post-Implementation Review" section
4. Commit all changes to Git
5. Update project wiki/docs site

**Deliverables**:
- ✅ Updated plan with results
- ✅ Lessons learned document
- ✅ All changes committed
- ✅ Documentation site updated

---

## 10. Success Criteria

### Must-Have (Blocking)

- ✅ Fresh SQLite install works in <5 minutes
- ✅ Docker setup works in <5 minutes
- ✅ All migrations apply without errors
- ✅ Load tests run successfully on fresh database
- ✅ All 5 validation checkpoints pass

### Should-Have (Important)

- ✅ Seed data script works for both SQLite and PostgreSQL
- ✅ Documentation accurately reflects implementation
- ✅ No confusion between migration systems
- ✅ Docker environment variables work as documented

### Nice-to-Have (Optional)

- 🎯 Consolidated migration system (defer to Phase 2)
- 🎯 Automated validation CI/CD pipeline
- 🎯 Video walkthrough of fresh install process
- 🎯 Interactive installation wizard

---

## 11. Risks & Mitigation

### Risk 1: Breaking Changes to Docker Setup

**Impact**: High (production users affected)
**Probability**: Low
**Mitigation**:
- Test on separate branch first
- Maintain backward compatibility for 1 release
- Document migration path for existing users
- Provide rollback instructions

### Risk 2: Seed Data Script Breaks Existing Data

**Impact**: High (data loss)
**Probability**: Low
**Mitigation**:
- Use `ON CONFLICT DO NOTHING` in SQL
- Test on fresh database first
- Document backup procedure
- Add `--force` flag for destructive operations (opt-in)

### Risk 3: Documentation Updates Miss Edge Cases

**Impact**: Medium (user confusion)
**Probability**: Medium
**Mitigation**:
- Have 2+ people review docs
- Test on clean VM (not dev machine)
- Collect feedback from new users
- Iterate based on support questions

### Risk 4: Migration Consolidation Causes Downtime

**Impact**: High (service outage)
**Probability**: Low (only if we consolidate)
**Mitigation**:
- Defer consolidation to Phase 2
- Document dual system clearly for now
- Plan consolidation during maintenance window
- Provide rollback script

---

## 12. Next Steps

### Immediate Actions (Before Starting Work)

1. **Review this plan** with team/stakeholders
2. **Approve scope**: All fixes or subset?
3. **Assign ownership**: Who implements what?
4. **Schedule timeline**: When to start/complete?
5. **Set up test environment**: Clean VM or container

### First Tasks to Execute

1. **Create `tools/seed_data.py`** (Fix #1)
   - Most impactful fix
   - Unblocks load testing
   - Easy to test in isolation

2. **Run Checkpoint 1** (SQLite Fresh Install)
   - Validates current state
   - Quick win if it passes
   - Identifies immediate issues

3. **Update `docker-compose.yml`** (Fix #2)
   - Low risk, high value
   - Improves environment variable handling
   - Easy to test and rollback

### Post-Completion Actions

1. **Announce changes** to users via release notes
2. **Monitor support channels** for new issues
3. **Collect feedback** on documentation clarity
4. **Schedule Phase 2** if consolidation approved
5. **Celebrate success** 🎉

---

## Appendix A: File Locations

### Core Files

| File | Purpose | Status |
|------|---------|--------|
| `pyproject.toml` | Package configuration | ✅ Exists |
| `requirements.txt` | Pip dependencies | ✅ Exists |
| `docker/docker-compose.yml` | Docker orchestration | ✅ Exists, needs env var update |
| `docker/init-db.sql` | PostgreSQL initialization | ✅ Exists |
| `migrations/schema.yaml` | Unified schema definition | ✅ Exists |
| `migrations/002_postgres_standardized.sql` | PostgreSQL migration | ✅ Exists |
| `migrations/003_sqlite_fixed.sql` | SQLite migration | ✅ Exists |
| `tools/migrate.py` | Migration manager | ✅ Exists |
| `tools/seed_data.py` | Seed data script | ❌ To be created |

### Documentation Files

| File | Purpose | Status |
|------|---------|--------|
| `README.md` | Project overview | ✅ Exists, needs Quick Start |
| `QUICKSTART.md` | Installation guide | ✅ Exists, needs decision tree |
| `CLAUDE.md` | Comprehensive guide | ✅ Exists, needs migration section |
| `ENV_CONFIGURATION.md` | Environment variables | ✅ Exists, needs Docker section |
| `docker/README.md` | Docker troubleshooting | ❌ To be created |
| `tests/load/README.md` | Load test setup | ❌ To be created |

### Test Files

| File | Purpose | Status |
|------|---------|--------|
| `tests/cli/conftest.py` | Pytest fixtures | ✅ Exists |
| `tests/load/run_load_test.py` | Load test runner | ✅ Exists, needs seed check |
| `tests/load/device_simulator.py` | Device simulator | ✅ Exists |

---

## Appendix B: Command Reference

### Installation Commands

```bash
# SQLite (Development)
pip install -r requirements.txt
python examples/sqlite_task_manager/simple_demo.py

# Docker (Production)
cd docker && docker compose up -d

# CLI Setup
rufus db init --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud"
```

### Validation Commands

```bash
# Check SQLite schema
sqlite3 workflow.db ".tables"

# Check PostgreSQL schema
docker exec -it rufus-postgres psql -U postgres -d rufus_cloud -c "\dt"

# Check migration status
rufus db status --db-url "postgresql://postgres:postgres@localhost:5433/rufus_cloud"

# Run load test
python tests/load/run_load_test.py --devices 10 --duration 60 --scenario heartbeat
```

### Troubleshooting Commands

```bash
# Docker logs
docker compose logs -f postgres
docker compose logs -f rufus_server

# Database connection test
psql "postgresql://postgres:postgres@localhost:5433/rufus_cloud" -c "SELECT 1;"

# Reset Docker
docker compose down -v && docker compose up -d

# Clean SQLite
rm -f workflow.db && python examples/sqlite_task_manager/simple_demo.py
```

---

## Appendix C: Validation Scripts

All validation checkpoint scripts are provided in Section 8. To run all checkpoints:

```bash
#!/bin/bash
# run_all_checkpoints.sh

echo "=== Running All Validation Checkpoints ==="

./checkpoint1_sqlite.sh && \
./checkpoint2_docker.sh && \
./checkpoint3_cli.sh && \
./checkpoint4_seed.sh && \
./checkpoint5_load_test.sh

if [ $? -eq 0 ]; then
  echo "✓ All checkpoints PASSED"
else
  echo "✗ Some checkpoints FAILED"
  exit 1
fi
```

---

**End of Plan**

**Ready for Review**: Yes
**Estimated Total Effort**: 20-24 hours
**Timeline**: 3-4 days
**Risk Level**: Low-Medium
**Dependencies**: None
**Stakeholders**: Development team, DevOps, Documentation maintainers
