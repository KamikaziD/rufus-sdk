# Beta Readiness Audit — Gap Closure

## Group 1 — Critical Doc Fixes
- [x] 1.1 Fix `initial_state_model` → `initial_state_model_path` in docs + TECHNICAL_INFORMATION.md
- [x] 1.2 Fix `PREFER_OLD` → `PREFER_EXISTING` in parallel-execution.md, step-types.md, TECHNICAL_INFORMATION.md
- [x] 1.3 Rewrite `docs/reference/api/step-context.md` (Pydantic BaseModel, correct fields)
- [x] 1.4 Fix `context.loop_state` → `context.loop_item`/`loop_index` in docs
- [x] 1.5 Add `allow_partial_success` to `ParallelWorkflowStep` + forward in workflow.py

## Group 2 — Remove Dead / Broken Code
- [x] 2.1 Remove JavaScript step type (models.py, builder.py, workflow.py, deleted test_javascript.py)
- [x] 2.2 Fix dead Redis import in CLI providers.py (ValueError with helpful message)

## Group 3 — Implement Missing Functionality
- [x] 3.1 CRON_SCHEDULE polling engine (tasks.py poll_scheduled_workflows, celery.py register_scheduled_workflow)
- [x] 3.2 Admin auth on 8 server endpoints (require_admin dependency, 8 routes wired)
- [x] 3.3 WebSocket device authentication (api_key query param validation)

## Group 4 — Documentation Fixes
- [x] 4.1 Merge strategy enum — all 6 values in FEATURES_AND_CAPABILITIES.md
- [x] 4.2 Add AI_INFERENCE step type to step-types.md
- [x] 4.3 Fix CRON_SCHEDULER → CRON_SCHEDULE in builder.py + docs + test_builder.py
- [x] 4.4 Document `saga_enabled` in yaml-schema.md
- [x] 4.5 Fix HTTP step broken example link (javascript_steps → quickstart)
- [x] 4.6 Update version numbers to 0.5.3 in README.md + FEATURES_AND_CAPABILITIES.md
- [x] 4.7 Add `description` field to common step fields table in yaml-schema.md
- [x] 4.8 Clarify `input_model` (YAML) vs `input_schema` (Python) in yaml-schema.md
- [x] 4.9 Update changelog for v0.5.3

## Group 5 — New Tests
- [x] 5.1 Create `tests/sdk/test_fire_and_forget.py` (3 tests)
- [x] 5.2 Create `tests/sdk/test_cron_schedule.py` (4 tests)
- [x] 5.3 Create `tests/sdk/test_expression_evaluator.py` (9 tests)
- [x] 5.4 Create `tests/sdk/test_template_engine.py` (10 tests)
- [x] 5.5 Create `tests/sdk/test_thread_pool_executor.py` (6 tests)

## Group 6 — CLI Currency
- [x] 6.1 Fix dead Redis import (covered by 2.2)
- [x] 6.3 CRON_SCHEDULER → CRON_SCHEDULE in builder.py (covered by 4.3)
- [x] 6.4 Change Celery NotImplementedError to ValueError in providers.py

## Review

### Proof of Work
- **138 tests pass** (106 pre-existing + 32 new), 0 failures
- JS cleanup: `grep -rn "JavaScriptWorkflowStep|JAVASCRIPT" src/ tests/` → 0 results
- `test_javascript.py` (742 lines) deleted
- `test_builder.py::test_build_steps_from_config` fixed (CRON_SCHEDULER → CRON_SCHEDULE)

### Files Changed (Code)
- `src/rufus/models.py` — removed JavaScriptConfig/JavaScriptWorkflowStep; added allow_partial_success
- `src/rufus/builder.py` — removed JAVASCRIPT branch; CRON_SCHEDULER→CRON_SCHEDULE; fixed import
- `src/rufus/workflow.py` — removed JS handler and import; forwarded allow_partial_success
- `src/rufus/tasks.py` — implemented poll_scheduled_workflows
- `src/rufus/implementations/execution/celery.py` — implemented register_scheduled_workflow; added pg_executor import
- `src/rufus_server/auth/dependencies.py` — added require_admin
- `src/rufus_server/auth/__init__.py` — exported require_admin
- `src/rufus_server/main.py` — 8 admin routes wired to require_admin; WebSocket auth added
- `src/rufus_cli/providers.py` — Redis ValueError; Celery ValueError

### Files Changed (Tests)
- `tests/sdk/test_builder.py` — fixed CRON_SCHEDULER → CRON_SCHEDULE
- `tests/sdk/test_javascript.py` — DELETED
- `tests/sdk/test_fire_and_forget.py` — NEW (3 tests)
- `tests/sdk/test_cron_schedule.py` — NEW (4 tests)
- `tests/sdk/test_expression_evaluator.py` — NEW (9 tests)
- `tests/sdk/test_template_engine.py` — NEW (10 tests)
- `tests/sdk/test_thread_pool_executor.py` — NEW (6 tests)

### Files Changed (Docs)
- `docs/reference/api/step-context.md` — complete rewrite
- `docs/reference/configuration/yaml-schema.md` — initial_state_model_path, saga_enabled, description, input_model note
- `docs/reference/configuration/step-types.md` — loop_item/loop_index, PREFER_EXISTING, AI_INFERENCE section
- `docs/explanation/parallel-execution.md` — PREFER_EXISTING fix
- `docs/FEATURES_AND_CAPABILITIES.md` — CRON_SCHEDULE, all 6 merge strategies, HTTP example fix, v0.5.3
- `docs/appendices/changelog.md` — v0.5.3 entry
- `README.md` — version 0.5.3
- `.claude/TECHNICAL_INFORMATION.md` — initial_state_model_path, PREFER_EXISTING
