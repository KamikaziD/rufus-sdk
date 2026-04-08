# Migration Notes

Version-to-version migration guides for upgrading Ruvon SDK.

---

## Table of Contents

- [Upgrading to 0.6.0](#upgrading-to-060)
- [Upgrading to 0.5.0](#upgrading-to-050)
- [Upgrading to 0.4.2](#upgrading-to-042)
- [Upgrading to 0.4.1](#upgrading-to-041)
- [Upgrading to 0.4.0](#upgrading-to-040)
- [Upgrading to 0.3.0](#upgrading-to-030)
- [Upgrading to 0.1.2](#upgrading-to-012)
- [Upgrading to 0.1.1](#upgrading-to-011)
- [Future Migrations](#future-migrations)
- [Breaking Changes Policy](#breaking-changes-policy)

---

## Upgrading to 1.0.0rc4 / rc5

**From:** 1.0.0rc3 or earlier
**Date:** 2026-03-16 (rc4) · 2026-03-18 (rc5)

### New Alembic Migrations

Two new migrations are included. Run `alembic upgrade head` after deploying:

| Migration | Description |
|-----------|-------------|
| `i4j5k6l7m8n9` | Adds `workflow_id TEXT` column to `saf_transactions` table — links SAF records to source workflow execution |
| `j5k6l7m8n9o0` | Adds `device_id TEXT` column to `device_configs` table — enables per-device configuration overrides |

```bash
alembic upgrade head
```

### No Breaking Changes

Both migrations are additive (new nullable columns). Existing data is unaffected. No Python import changes required.

### SAF Table Change (rc4)

The `SyncManager` now uses `saf_pending_transactions` instead of the `tasks` table. This ensures SAF records survive workflow purge (the `tasks` table has `ON DELETE CASCADE` on the `workflow_executions` FK). If you have custom code querying `tasks` for pending SAF transactions, migrate to `saf_pending_transactions`.

---

## Upgrading to 0.6.0

**From:** 0.5.x
**Date:** 2026-02-27

### Summary

v0.6.0 splits the monolithic `ruvon-sdk` wheel into three separate packages. **No Python import changes are required** — the package names (`ruvon`, `ruvon_edge`, `ruvon_server`, `ruvon_cli`) are unchanged. Only the `pip install` command changes depending on your deployment target.

### Install Command Changes

**Before (0.5.x):**
```bash
pip install 'ruvon-sdk==0.5.4'                    # installs everything — 9.3 MB
```

**After (0.6.0+):**
```bash
# Edge device — installs only core + edge agent (~500 KB total)
pip install 'ruvon-sdk==0.6.0' 'ruvon-edge[edge]==0.6.0'

# Cloud server — installs core + server package
pip install 'ruvon-sdk==0.6.0' 'ruvon-server[server,auth]==0.6.0'

# Celery worker
pip install 'ruvon-sdk==0.6.0' 'ruvon-server[celery]==0.6.0'

# Dev (all packages from source)
pip install -e ".[postgres,performance,cli]"
pip install -e "packages/ruvon-edge[edge]"
pip install -e "packages/ruvon-server[server,celery,auth]"
```

### Breaking Changes

**None for existing code.** All Python imports (`from ruvon import ...`, `from ruvon_edge import ...`, etc.) continue to work unchanged.

**Docker Compose / deployment scripts** must be updated if they reference the old monolithic extras:
- `ruvon-sdk[server]` → install `ruvon-server[server]` separately
- `ruvon-sdk[celery]` → install `ruvon-server[celery]` separately
- `ruvon-sdk[edge]` → install `ruvon-edge[edge]` separately

### Action Required

1. Update your `pip install` command or `requirements.txt` to reference the appropriate sub-package
2. If using the production Docker images, pull the new `0.6.0` tags — they use the split install internally
3. Run `pytest tests/test_package_versions.py` to verify version consistency

---

## Upgrading to 0.5.0

**From:** 0.4.x
**Date:** 2026-02-24

### Summary

v0.5.0 consolidates all PostgreSQL tables under Alembic management. No Python API changes.

### Database Schema (IMPORTANT)

**Run the new migration:**

```bash
cd src/ruvon
alembic upgrade head
```

This creates 27 previously-unmanaged tables and adds 13 columns to `device_commands` (retry fields, batch/broadcast links). The migration is safe to run on existing databases.

**`init-db.sql` no longer creates tables.** It only installs PostgreSQL extensions (`uuid-ossp`, `pg_trgm`). If you used `init-db.sql` as your schema setup script, switch to running `alembic upgrade head` instead.

**New edge tables (SQLite)** — three new tables are created automatically when `SQLitePersistenceProvider` starts: `saf_pending_transactions`, `device_config_cache`, `edge_sync_state`. No manual action required.

### Breaking Changes

**None.** Python API unchanged.

### Action Required

1. Run `alembic upgrade head` on your PostgreSQL database
2. If using `init-db.sql` as a setup script, replace it with `alembic upgrade head`
3. Set `RUVON_ENCRYPTION_KEY` if not already set (required for workflow decryption)

---

## Upgrading to 0.4.2

**From:** 0.4.1 or earlier
**Date:** 2026-02-23

### Summary

Bug fix release. No breaking changes.

### Breaking Changes

**None.**

### Optional Actions

- Add `RUVON_CUSTOM_ROUTERS` env var to mount custom API routes (introduced in v0.4.0)

---

## Upgrading to 0.4.1

**From:** 0.4.0 or earlier
**Date:** 2026-02-23

### Summary

Swagger UI is now grouped by tag (14 groups). No breaking changes.

### Breaking Changes

**None.**

### Notes

Swagger UI at `/docs` now shows routes grouped by functional area (Workflows, Devices, Commands, etc.) for easier navigation.

---

## Upgrading to 0.4.0

**From:** 0.3.x
**Date:** 2026-02-23

### Summary

Adds `RUVON_CUSTOM_ROUTERS` for user-defined API extensions. No breaking changes.

### Breaking Changes

**None.**

### New Feature

```bash
export RUVON_CUSTOM_ROUTERS="myapp.api.custom_router"
```

Mount additional FastAPI routers on startup without modifying core server code.

---

## Upgrading to 0.3.0

**From:** 0.1.x
**Date:** 2026-02-13

### Summary

Version 0.3.0 is a **feature release with full backward compatibility**. No code changes required.

### What's New

- Debug UI at `http://localhost:8000/debug`
- Docker/Kubernetes deployment templates
- Database seeding and cleanup tools
- Enhanced error messages
- Complete feature parity analysis

### Breaking Changes

**None.** This is a backwards-compatible release.

### Action Required

**None.** Existing code and configurations will continue to work.

### Optional Actions

1. **Try the Debug UI**
   ```bash
   # Start Ruvon Server
   uvicorn ruvon_server.main:app --reload

   # Visit http://localhost:8000/debug
   ```

2. **Use Database Seeding for Testing**
   ```bash
   python tools/seed_data.py --db postgresql://localhost/ruvon
   ```

3. **Review Deployment Templates**
   - See `docker/README.md` for Docker Compose setup
   - See `k8s/` directory for Kubernetes manifests

### Deprecations

**None.**

### Known Issues

- Debug UI requires JavaScript enabled
- Docker deployment requires manual environment variable configuration

---

## Upgrading to 0.1.2

**From:** 0.1.1 or 0.1.0
**Date:** 2026-01-15

### Summary

Bug fix release addressing Pydantic warnings and PostgreSQL compatibility.

### Breaking Changes

**None.**

### Fixes

1. **Pydantic Protected Namespace Warning**
   - Suppressed warning for `AIInferenceConfig` model
   - No code changes required

2. **PostgreSQL `current_step` Field**
   - Converted to `VARCHAR` for better compatibility
   - Existing databases continue to work
   - No migration needed

### Action Required

**None.** Just upgrade:

```bash
pip install --upgrade ruvon
```

### Database Changes

**No migration required.** Schema changes are backwards compatible.

---

## Upgrading to 0.1.1

**From:** 0.1.0
**Date:** 2026-01-15

### Summary

Bug fix release correcting package metadata.

### Breaking Changes

**None.**

### Fixes

1. **Missing Dependencies**
   - Added missing packages to `pyproject.toml`
   - Dependencies now auto-install correctly

2. **Package Name Correction**
   - Changed from `ruvon-edge` to `ruvon`
   - Pip install now works correctly: `pip install ruvon`

### Action Required

**Update installation command** (if installing fresh):

```bash
# Old (incorrect)
pip install ruvon-edge

# New (correct)
pip install ruvon
```

Existing installations continue to work.

---

## Future Migrations

### Upgrading to 1.0.0 (Planned Q2 2026)

**Expected Changes:**

1. **API Stability Guarantee**
   - After 1.0.0, no breaking changes in minor releases
   - Pre-1.0 (0.x) may have minor API changes

2. **Potential Breaking Changes** (will be announced):
   - Provider interface enhancements (new required methods)
   - CLI command restructuring for consistency
   - Configuration file format updates

**Migration Support:**

- Detailed migration guide will be provided
- Automated migration scripts for configuration
- Deprecation warnings in 0.9.x releases
- 3-month deprecation period before removal

### Upgrading to 1.1.0 and Beyond

**Post-1.0 Guarantee:**

- **No breaking changes** in minor releases (1.x.0)
- **New features** are additive only
- **Deprecations** announced at least one major version in advance
- **Migration guides** provided for all major versions

---

## Breaking Changes Policy

### Pre-1.0 (Current: v0.x)

**Minor API changes possible** in any release. We will:

1. **Document all changes** in changelog
2. **Provide migration guide** for breaking changes
3. **Announce in release notes** with upgrade path
4. **Keep breaking changes minimal** - only when necessary

### Post-1.0 (Future: v1.x+)

**No breaking changes in minor releases.** We guarantee:

1. **Semantic Versioning**
   - Major (X.0.0): Breaking changes
   - Minor (0.X.0): New features, backwards compatible
   - Patch (0.0.X): Bug fixes, backwards compatible

2. **Deprecation Process**
   - Feature marked deprecated in version N
   - Deprecation warnings in code
   - Feature removed in version N+1 (major version)
   - Minimum 3 months between deprecation and removal

3. **Migration Support**
   - Automated migration tools where possible
   - Detailed migration guides
   - Code examples for common patterns
   - Community support during migration

---

## Common Migration Patterns

### Database Migrations

**When schema changes:**

```bash
# Check current migration status
cd src/ruvon
alembic current

# View pending migrations
alembic history

# Apply migrations (dry-run first)
alembic upgrade head --sql  # View SQL that will run
alembic upgrade head        # Apply migrations

# Rollback if needed
alembic downgrade -1        # Rollback one migration
```

**Backup before migrating:**

```bash
# PostgreSQL backup
pg_dump -h localhost -U ruvon ruvon_cloud > backup.sql

# SQLite backup
cp workflow.db workflow.db.backup
```

### Configuration File Updates

**When config format changes:**

```bash
# Backup existing config
cp ~/.ruvon/config.json ~/.ruvon/config.json.backup

# Reset to defaults (generates new format)
ruvon config reset

# Re-apply your settings
ruvon config set-persistence  # Interactive
ruvon config set-execution    # Interactive
```

### Code Updates

**Provider Interface Changes:**

If a provider interface adds required methods, you'll see:

```python
TypeError: Can't instantiate abstract class MyCustomProvider
with abstract method new_required_method
```

**Solution:** Implement the new method. Check migration guide for signature and expected behavior.

**Step Function Signature Changes:**

If step function signatures change, you'll see:

```python
TypeError: step_function() got an unexpected keyword argument 'new_param'
```

**Solution:** Update step function signatures. Migration guide will provide examples.

### Testing After Migration

**Recommended test checklist:**

```bash
# 1. Run test suite
pytest

# 2. Start a simple workflow
ruvon start MyWorkflow --data '{"test": true}'

# 3. Check workflow completed
ruvon show <workflow-id>

# 4. View logs
ruvon logs <workflow-id>

# 5. Check database
ruvon db stats
```

---

## Migration Support

### Getting Help

**If you encounter issues during migration:**

1. **Check the changelog** - `changelog.md`
2. **Review migration notes** - This document
3. **Search GitHub Issues** - Someone may have solved it
4. **Ask in Discussions** - Community support
5. **Open an issue** - If you found a bug

### Reporting Migration Issues

**When reporting migration problems, include:**

- **Versions:** Old version → New version
- **Environment:** Python version, OS, database type
- **Error message:** Full traceback
- **Steps to reproduce:** What you were doing
- **Configuration:** Relevant config files (redact secrets)

### Rollback Support

**If migration fails, you can rollback:**

```bash
# Restore database backup
psql -h localhost -U ruvon ruvon_cloud < backup.sql

# Reinstall previous version
pip install ruvon==0.1.2  # Example: rollback to 0.1.2

# Restore config backup
cp ~/.ruvon/config.json.backup ~/.ruvon/config.json
```

---

## Deprecation Notices

### Current Deprecations

**None currently.**

### Future Deprecations

**Will be announced in:**
- Release notes
- Changelog
- In-code warnings
- GitHub Discussions

**Deprecation timeline:**
- Announcement: Version N
- Warnings: Version N (runtime deprecation warnings)
- Removal: Version N+1 (major version bump)
- Support period: Minimum 3 months

---

## Version Compatibility Matrix

| Ruvon Version | Python | PostgreSQL | SQLite | Redis | Celery |
|---------------|--------|------------|--------|-------|--------|
| 0.6.0         | 3.9+   | 12+        | 3.35+  | 6.0+  | 5.3+   |
| 0.5.0         | 3.9+   | 12+        | 3.35+  | 6.0+  | 5.3+   |
| 0.4.2         | 3.9+   | 12+        | 3.35+  | 6.0+  | 5.3+   |
| 0.4.1         | 3.9+   | 12+        | 3.35+  | 6.0+  | 5.3+   |
| 0.4.0         | 3.9+   | 12+        | 3.35+  | 6.0+  | 5.3+   |
| 0.3.0         | 3.10+  | 12+        | 3.35+  | 6.0+  | 5.3+   |
| 0.1.2         | 3.10+  | 12+        | 3.35+  | 6.0+  | 5.3+   |
| 0.1.0         | 3.10+  | 12+        | 3.35+  | 6.0+  | 5.3+   |

**Note:** Ruvon SDK is tested against these versions. Older versions may work but are not officially supported.

**Last Updated:** 2026-02-24

---

## Questions?

- 📖 [Changelog](/docs/appendices/changelog.md)
- 💬 [GitHub Discussions](https://github.com/your-org/ruvon-sdk/discussions)
- 🐛 [Report Issues](https://github.com/your-org/ruvon-sdk/issues)

---

**Last Updated:** 2026-02-27
**Next Review:** Each release
