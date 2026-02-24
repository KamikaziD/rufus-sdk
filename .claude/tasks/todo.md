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
