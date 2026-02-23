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

## Pattern: data_region Routes Sub-Workflow Tasks to Orphan Queue
**Context:** `StartSubWorkflowDirective(data_region="onsite-london")` in user step function
**Anti-Pattern:** Setting `data_region` to a named region without a worker listening to that queue — child workflow inherits `data_region`, all its async/parallel tasks dispatch to that queue (e.g., `onsite-london`), workers only consume `default`
**Symptom:** Parent stuck in `PENDING_SUB_WORKFLOW` indefinitely; child stuck in `PENDING_ASYNC`; worker logs go silent after chord dispatch; `LLEN default=0` but `onsite-london` queue has tasks sitting in Redis
**Diagnosis:** `docker exec test-redis redis-cli keys "*"` — look for unexpected queue names with entries; compare against queues workers actually listen to
**Correction:** Remove `data_region` (routes to `default`) OR start a worker with `-Q onsite-london`; flush orphaned queue with `redis-cli DEL <queue-name>`
**Verification:** `LLEN onsite-london` = 0 after flush; fresh workflow completes the parallel step
