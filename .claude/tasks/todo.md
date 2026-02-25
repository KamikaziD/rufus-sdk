# PARALLEL Step Batching (`batch_size`)

## Tasks
- [x] Add `batch_size: int = 0` field to `ParallelWorkflowStep` (`src/rufus/models.py`)
- [x] Implement sequential batch dispatch loop in PARALLEL handler (`src/rufus/workflow.py` ~line 714)
  - Celery guard: logs warning and falls back to single dispatch if `CeleryExecutionProvider` detected
- [x] Write `tests/sdk/test_parallel_batching.py` (4 tests — all pass)
- [x] Update `docs/reference/configuration/yaml-schema.md` — added `batch_size` field + description
- [x] Update `docs/explanation/parallel-execution.md` — added "Pattern 5: Batching Large Lists" section
- [x] Update `.claude/TECHNICAL_INFORMATION.md` §4 — added dynamic fan-out example with `batch_size`

## Review
- 4/4 new tests pass; 120 pre-existing passing tests still pass
- 15 pre-existing failures in `test_javascript.py` (missing `rufus.javascript` module) — unrelated

---

# Phase 2 Dogfooding — PolicyRollout Workflow

## Tasks

- [x] Create `src/rufus_server/steps/policy_rollout_steps.py`
  - PolicyRolloutState model
  - validate_policy, persist_policy, compensate_persist_policy, finalize_policy_rollout
  - init_services() injection
- [x] Create `config/policy_rollout_workflow.yaml`
- [x] Add PolicyRollout entry to `config/workflow_registry.yaml`
- [x] Add `init_policy_rollout_services` call in `startup_event()` (main.py)
- [x] Add `POST /api/v1/policies/rollout` endpoint (main.py)
- [x] Add boundary comment to `policy_engine.py` (PolicyEvaluator)
- [x] Add boundary comment to `device_service.py` (DeviceService)
- [x] Create `tests/sdk/test_policy_rollout.py` (8 tests, all pass)
- [x] Doc fixes (README.md + self-hosting.md) — no future-tense matches found, no-op

## Review

All 8 new tests pass. Full SDK suite: 116 passed, 22 skipped, 15 pre-existing
JS failures (rufus.javascript module doesn't exist) unchanged.

Endpoint added at `/api/v1/policies/rollout` — does NOT replace existing
`POST /api/v1/policies` to preserve backward compatibility with existing tests.
