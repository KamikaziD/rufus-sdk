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

## Pattern: All Version Locations Must Be Updated Together
**Context:** Version bump flow for this project (v0.6.0+)
**Anti-Pattern:** Missing any of the canonical version locations — now there are more: root `pyproject.toml`, both sub-package `pyproject.toml` files (`packages/rufus-sdk-edge/`, `packages/rufus-sdk-server/`), all four `__init__.py` files (`rufus`, `rufus_edge`, `rufus_server`, `rufus_cli`), and all three Dockerfiles.
**Correction:** Full version bump checklist: (1) root `pyproject.toml`, (2) `packages/rufus-sdk-edge/pyproject.toml`, (3) `packages/rufus-sdk-server/pyproject.toml`, (4) all four `__init__.py` files, (5) all three Dockerfiles — then commit, build with `--no-cache`, push. Run `pytest tests/test_package_versions.py` to catch drift.
**Verification:** `pytest tests/test_package_versions.py -v` passes; `grep version packages/*/pyproject.toml pyproject.toml` shows consistent version in all three pyproject files; `grep rufus-sdk docker/Dockerfile.rufus-*-prod` shows new version in all Dockerfiles

## Pattern: Step Functions Used as Dotted-Path Tasks Must Be Module-Level
**Context:** Writing tests for `ThreadPoolExecutor` and `PARALLEL` steps using `WorkflowBuilder` dotted-path function references
**Anti-Pattern:** Defining `task_a` and `task_b` inside the test function body, then registering them as `"test_module.task_a"` — `importlib` cannot import names that only exist in a local function scope, crashes with `AttributeError: module has no attribute 'task_a'`
**Correction:** Move any function referenced by dotted path to module level in the test file (outside all functions/classes)
**Verification:** `importlib.import_module("tests.sdk.test_thread_pool_executor"); getattr(mod, "task_a")` succeeds without AttributeError

## Pattern: Jinja2 Template Context Is a Flat Dict (model_dump()), Not Nested Under "state"
**Context:** Writing FIRE_AND_FORGET tests with templates like `{{ state.recipient }}`
**Anti-Pattern:** `{{ state.recipient }}` or `{{ state.amount }}` — the template engine receives `state.model_dump()` (a flat dict), not an object with a `state` attribute
**Correction:** Use `{{ recipient }}` and `{{ amount }}` directly (top-level keys); there is no `state.` prefix in templates
**Verification:** `Jinja2TemplateEngine().render("Hello {{ recipient }}", context={"recipient": "Alice"})` returns `"Hello Alice"`

## Pattern: Mock Patch Path Must Match the Module That Owns the Binding
**Context:** Patching `pg_executor` in `celery.py` tests
**Anti-Pattern:** `patch("rufus.utils.postgres_executor.pg_executor")` alone — this patches the source module but `celery.py` already has its own binding via `from rufus.utils.postgres_executor import pg_executor`; the celery module sees the old object
**Correction:** Patch where it is used: `patch("rufus.implementations.execution.celery.pg_executor")` — this replaces the binding in the module under test
**Verification:** Mock's `assert_called_once` passes; no `AttributeError: module ... does not have the attribute`

## Pattern: workflow.next_step() Always Requires user_input Argument
**Context:** Writing new SDK tests that call `next_step()` directly
**Anti-Pattern:** `await wf.next_step()` — `user_input` is a required positional argument; omitting it raises `TypeError: next_step() missing 1 required positional argument`
**Correction:** Always pass `await wf.next_step(user_input={})` even when no input is needed; use a populated dict for HUMAN_IN_LOOP steps
**Verification:** Test runs without TypeError

## Pattern: Poetry 2.x and Hatchling Both Reject ../../ Paths in packages= — Use force-include
**Context:** Mono-repo sub-packages (`packages/rufus-sdk-edge/`) whose source lives in `../../src/rufus_edge`
**Anti-Pattern:** `packages = [{ include = "rufus_edge", from = "../../src" }]` (Poetry) or `packages = ["../../src/rufus_edge"]` (Hatchling) — both raise `ValueError: path must be relative` because build backends refuse to traverse outside the project root for security
**Correction:** Use Hatchling as build backend with `[tool.hatch.build.targets.wheel.force-include]` — `force-include` resolves paths via `os.path.normpath(root / source)`, which correctly handles `../../` without the relative-path validation:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel.force-include]
"../../src/rufus_edge" = "rufus_edge"
```
Also switch from `[tool.poetry]` metadata to `[project]` (PEP 621) since Hatchling reads the latter.
**Verification:** `python -m build --wheel` from the sub-package dir succeeds; `unzip -l dist/*.whl | grep "\.py"` shows only the intended package files

## Pattern: Use git (not gh) for GitHub Releases
**Context:** Creating a GitHub release as part of the version bump / release chore
**Anti-Pattern:** `gh release create v0.6.1 ...` — the `gh` CLI returns `401 Unauthorized / Bad credentials` in this environment; it does not have a valid GitHub token configured
**Correction:** Create GitHub releases via the GitHub web UI at https://github.com/KamikaziD/rufus-sdk/releases/new, or use the raw GitHub API with `curl` if a token is available. Never use `gh release create`.
**Verification:** Release appears at https://github.com/KamikaziD/rufus-sdk/releases without a 401 error

## Pattern: data_region Routes Sub-Workflow Tasks to Orphan Queue
**Context:** `StartSubWorkflowDirective(data_region="onsite-london")` in user step function
**Anti-Pattern:** Setting `data_region` to a named region without a worker listening to that queue — child workflow inherits `data_region`, all its async/parallel tasks dispatch to that queue (e.g., `onsite-london`), workers only consume `default`
**Symptom:** Parent stuck in `PENDING_SUB_WORKFLOW` indefinitely; child stuck in `PENDING_ASYNC`; worker logs go silent after chord dispatch; `LLEN default=0` but `onsite-london` queue has tasks sitting in Redis
**Diagnosis:** `docker exec test-redis redis-cli keys "*"` — look for unexpected queue names with entries; compare against queues workers actually listen to
**Correction:** Remove `data_region` (routes to `default`) OR start a worker with `-Q onsite-london`; flush orphaned queue with `redis-cli DEL <queue-name>`
**Verification:** `LLEN onsite-london` = 0 after flush; fresh workflow completes the parallel step
