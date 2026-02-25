# Lessons Learned

## Pattern: Celery Task Signature Mismatch for Parallel Tasks
**Context:** Celery parallel tasks (chord header) in `dispatch_parallel_tasks`
**Anti-Pattern:** `async def verify_id_agent(state, context: StepContext, *args, **kwargs)` — Celery calls `check_arguments` eagerly when building chord signatures; `context` is required but not provided, crashes before queuing
**Correction:** `def verify_id_agent(state: dict, workflow_id: str)` — sync, no context, matches `func.s(state=..., workflow_id=...)` signature in `dispatch_parallel_tasks`
**Verification:** Worker logs show tasks received and completed; no `TypeError: missing 1 required positional argument`

## Pattern: @app.websocket() Does Not Accept tags= Argument
**Context:** Adding OpenAPI `tags=[...]` to all FastAPI route decorators
**Anti-Pattern:** `@app.websocket("/path", tags=["Group"])` — FastAPI's `websocket()` decorator does not support `tags=`, causes `TypeError` at import time crashing the server
**Correction:** Remove `tags=` from all `@app.websocket()` decorators; only HTTP method decorators (get/post/put/delete/patch) support tags
**Verification:** Server starts without `TypeError: FastAPI.websocket() got an unexpected keyword argument 'tags'`

## Pattern: Docker Layer Cache Silently Ships Wrong Version
**Context:** Version bump — bumping `pyproject.toml` + `__init__.py` then running the Docker build script
**Anti-Pattern:** Running `build-production-images.sh` without `--no-cache` after a version bump — Docker reuses the cached `pip install rufus-sdk==<old>` layer, producing images tagged `0.5.2` that silently run `0.5.1` inside
**Correction:** (1) Update the version pin in all three Dockerfiles as part of the version bump step, *before* building. (2) Always pass `--no-cache` to the Docker build after a version bump so the pip install layer is forced to re-run
**Verification:** `docker run --rm ruhfuskdev/rufus-server:0.5.2 python -c "import rufus; print(rufus.__version__)"` must print the new version

## Pattern: Dockerfiles Are a Third Canonical Version Location
**Context:** Version bump flow for this project
**Anti-Pattern:** Treating `pyproject.toml` and `src/rufus/__init__.py` as the only two files to update — the three production Dockerfiles (`Dockerfile.rufus-*-prod`) each pin `rufus-sdk==<version>` and must be updated in the same commit
**Correction:** Version bump checklist: (1) `pyproject.toml`, (2) `src/rufus/__init__.py`, (3) all three Dockerfiles — then commit, tag, build with `--no-cache`, push
**Verification:** `grep rufus-sdk docker/Dockerfile.rufus-*-prod` shows the new version in all three files before building

## Pattern: data_region Routes Sub-Workflow Tasks to Orphan Queue
**Context:** `StartSubWorkflowDirective(data_region="onsite-london")` in user step function
**Anti-Pattern:** Setting `data_region` to a named region without a worker listening to that queue — child workflow inherits `data_region`, all its async/parallel tasks dispatch to that queue (e.g., `onsite-london`), workers only consume `default`
**Symptom:** Parent stuck in `PENDING_SUB_WORKFLOW` indefinitely; child stuck in `PENDING_ASYNC`; worker logs go silent after chord dispatch; `LLEN default=0` but `onsite-london` queue has tasks sitting in Redis
**Diagnosis:** `docker exec test-redis redis-cli keys "*"` — look for unexpected queue names with entries; compare against queues workers actually listen to
**Correction:** Remove `data_region` (routes to `default`) OR start a worker with `-Q onsite-london`; flush orphaned queue with `redis-cli DEL <queue-name>`
**Verification:** `LLEN onsite-london` = 0 after flush; fresh workflow completes the parallel step
