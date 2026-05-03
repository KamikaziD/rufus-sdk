# Lessons Learned

## Pattern: WASM Binary Build — py2wasm IS pip-installable but requires Python 3.11+
**Context:** `src/ruvon_edge/sidecar/wasm/apply_config.wasm` — compiled WASM binary for the sandboxed deployment sidecar `ApplyChange` step
**Anti-Pattern (corrected):** Earlier lesson said "Neither py2wasm nor wasi-sdk are pip-installable". This was WRONG. `pip install py2wasm>=2.6.2` works and auto-downloads wasi-sdk during first run. However, py2wasm 2.6.x requires **Python 3.11+** — it fails on 3.10 with "Python version '3.10' is not supported". Always invoke via `python3.11 -m py2wasm` or `/path/to/python3.11/bin/py2wasm`.
**Additional Anti-Pattern:** `config_applier.py` had `if __name__ == "__wasm__": wasm_main()` — this guard NEVER fires because WASI sets `__name__` to `"__main__"`, not `"__wasm__"`. Binary ran clean (exit 0) but produced no output. Fix: `if __name__ == "__main__": wasm_main()`.
**Additional Anti-Pattern:** `build_wasm._build_with_py2wasm()` passed `--entry wasm_main` flag which does not exist in py2wasm — causes exit code 2. py2wasm takes only `filename` and `-o OUTPUT`.
**Additional Anti-Pattern:** wasmtime Python bindings use `WasiConfig.stdin_file = "/path"` (property, string path) NOT `stdin_bytes` or `WasiFile.from_fileobj()` which don't exist.
**Correction:** `pip install py2wasm>=2.6.2` then `python3.11 -m py2wasm config_applier.py -o apply_config.wasm`. Binary is ~25MB (CPython embedded). Commit the binary so it travels with the source. The `.sha256` hash file is used for staleness detection. Tests use subprocess mock for the no-toolchain path; the binary test uses file-based stdin/stdout with temp files.
**Verification:** `tests/edge/test_sidecar_wasm.py` — 9/9 passing. Binary at `src/ruvon_edge/sidecar/wasm/apply_config.wasm` (25MB). Test verifies hot-swap proposal produces `{"outcome": ..., "method": "hot_swap"}` on stdout.

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

## Pattern: PyPI CDN Propagation Takes 1-3 Minutes Per Package, Not 15 Seconds
**Context:** Docker build after twine upload to PyPI in multi-arch (amd64+arm64) build
**Anti-Pattern:** Starting Docker build immediately after twine reports success — PyPI CDN nodes can still show the old version list for 1-3+ minutes; different packages propagate at different rates
**Correction:** (1) Check each package individually via `curl -s "https://pypi.org/pypi/<pkg>/json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sorted(d['releases'].keys())[-3:])"` before building. (2) If Docker build fails with "could not find version", prune the buildx cache (`docker buildx prune --builder ruvon-builder --force`) then retry once all 3 packages are confirmed indexed.
**Verification:** All 3 `curl` commands return 0.7.x as the last version before starting Docker build

## Pattern: Docker Layer Cache Silently Ships Wrong Version
**Context:** Version bump — bumping `pyproject.toml` + `__init__.py` then running the Docker build script
**Anti-Pattern:** Running `build-production-images.sh` without `--no-cache` after a version bump — Docker reuses the cached `pip install ruvon-sdk==<old>` layer, producing images tagged `0.5.2` that silently run `0.5.1` inside
**Correction:** (1) Update the version pin in all three Dockerfiles as part of the version bump step, *before* building. (2) Always pass `--no-cache` to the Docker build after a version bump so the pip install layer is forced to re-run
**Verification:** `docker run --rm ruhfuskdev/ruvon-server:0.5.2 python -c "import ruvon; print(ruvon.__version__)"` must print the new version

## Pattern: All Version Locations Must Be Updated Together
**Context:** Version bump flow for this project (v0.6.0+)
**Anti-Pattern:** Missing any of the canonical version locations — now there are more: root `pyproject.toml`, both sub-package `pyproject.toml` files (`packages/ruvon-edge/`, `packages/ruvon-server/`), all four `__init__.py` files (`ruvon`, `ruvon_edge`, `ruvon_server`, `ruvon_cli`), and all three Dockerfiles.
**Correction:** Full version bump checklist: (1) root `pyproject.toml`, (2) `packages/ruvon-edge/pyproject.toml`, (3) `packages/ruvon-server/pyproject.toml`, (4) all four `__init__.py` files, (5) all three Dockerfiles — then commit, build with `--no-cache`, push. Run `pytest tests/test_package_versions.py` to catch drift.
**Verification:** `pytest tests/test_package_versions.py -v` passes; `grep version packages/*/pyproject.toml pyproject.toml` shows consistent version in all three pyproject files; `grep ruvon-sdk docker/Dockerfile.ruvon-*-prod` shows new version in all Dockerfiles

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
**Anti-Pattern:** `patch("ruvon.utils.postgres_executor.pg_executor")` alone — this patches the source module but `celery.py` already has its own binding via `from ruvon.utils.postgres_executor import pg_executor`; the celery module sees the old object
**Correction:** Patch where it is used: `patch("ruvon.implementations.execution.celery.pg_executor")` — this replaces the binding in the module under test
**Verification:** Mock's `assert_called_once` passes; no `AttributeError: module ... does not have the attribute`

## Pattern: workflow.next_step() Always Requires user_input Argument
**Context:** Writing new SDK tests that call `next_step()` directly
**Anti-Pattern:** `await wf.next_step()` — `user_input` is a required positional argument; omitting it raises `TypeError: next_step() missing 1 required positional argument`
**Correction:** Always pass `await wf.next_step(user_input={})` even when no input is needed; use a populated dict for HUMAN_IN_LOOP steps
**Verification:** Test runs without TypeError

## Pattern: Poetry 2.x and Hatchling Both Reject ../../ Paths in packages= — Use force-include
**Context:** Mono-repo sub-packages (`packages/ruvon-edge/`) whose source lives in `../../src/ruvon_edge`
**Anti-Pattern:** `packages = [{ include = "ruvon_edge", from = "../../src" }]` (Poetry) or `packages = ["../../src/ruvon_edge"]` (Hatchling) — both raise `ValueError: path must be relative` because build backends refuse to traverse outside the project root for security
**Correction:** Use Hatchling as build backend with `[tool.hatch.build.targets.wheel.force-include]` — `force-include` resolves paths via `os.path.normpath(root / source)`, which correctly handles `../../` without the relative-path validation:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel.force-include]
"../../src/ruvon_edge" = "ruvon_edge"
```
Also switch from `[tool.poetry]` metadata to `[project]` (PEP 621) since Hatchling reads the latter.
**Verification:** `python -m build --wheel` from the sub-package dir succeeds; `unzip -l dist/*.whl | grep "\.py"` shows only the intended package files

## Pattern: Use git (not gh) for GitHub Releases
**Context:** Creating a GitHub release as part of the version bump / release chore
**Anti-Pattern:** `gh release create v0.6.1 ...` — the `gh` CLI returns `401 Unauthorized / Bad credentials` in this environment; it does not have a valid GitHub token configured
**Correction:** Create GitHub releases via the GitHub web UI at https://github.com/KamikaziD/ruvon-sdk/releases/new, or use the raw GitHub API with `curl` if a token is available. Never use `gh release create`.
**Verification:** Release appears at https://github.com/KamikaziD/ruvon-sdk/releases without a 401 error

## Pattern: Docker Bind-Mounts Bypass Python .pyc Cache Via touch, Not Deletion
**Context:** Patching installed Python packages in a pre-built Docker image via bind-mounted `.py` files (test docker-compose)
**Anti-Pattern:** Trying to `find ... -name '*.pyc' -delete` or `chmod` the `__pycache__` directory — the directories are owned by root inside the image, so non-root container user gets "Permission denied"
**Correction:** `touch` the mounted source files before starting uvicorn: `touch /usr/local/lib/python3.11/site-packages/pkg/patched.py`. Python validates pyc by mtime+size stored in the pyc header; a newer mtime on the source triggers recompile from source, and if the container can't write the new pyc it just uses the in-memory compiled version
**Verification:** No `ModuleNotFoundError` from old cached code; log shows expected behavior from the patched module

## Pattern: ruvon-server Image Missing celery+redis — Must Install at Startup for Celery Backend
**Context:** Running `ruhfuskdev/ruvon-server:latest` with `WORKFLOW_EXECUTION_BACKEND: celery`
**Anti-Pattern:** Image only has fastapi/uvicorn/asyncpg; `CeleryExecutionProvider.__init__` imports `from ruvon.celery_app import celery_app` which imports `from celery import Celery` — crash at startup
**Correction 1:** Make the `CeleryExecutionProvider` import lazy in `main.py` (inside the `if execution_backend == 'celery':` block, not at module top level)
**Correction 2:** Add `pip install celery redis --quiet --no-cache-dir` to the container startup command in the test compose
**Verification:** Server logs show `INFO: Application startup complete.` and `GET /health` returns 200

## Pattern: next.config.ts Not Supported in Next.js 14 (only 15+)
**Context:** Next.js 14 dashboard in Docker container
**Anti-Pattern:** Creating `next.config.ts` (TypeScript) — Next.js 14.x throws `Error: Configuring Next.js via 'next.config.ts' is not supported`
**Correction:** Use `next.config.mjs` (ES module) with `/** @type {import('next').NextConfig} */` JSDoc annotation; remove the `import type` line
**Verification:** `next dev` starts without config format error

## Pattern: Keycloak 24 Image Has No curl or wget — Use bash /dev/tcp for Healthcheck
**Context:** Docker Compose healthcheck for Keycloak container
**Anti-Pattern:** `test: ["CMD-SHELL", "curl -sf http://localhost:8080/realms/ruvon || exit 1"]` — Keycloak 24.0 base image has no `curl` or `wget`; healthcheck always fails
**Correction:** Use bash's built-in `/dev/tcp` pseudo-device: `test: ["CMD", "bash", "-c", "(echo > /dev/tcp/localhost/8080) 2>/dev/null"]`. Note: must use `CMD` (not `CMD-SHELL`) to invoke bash explicitly, since `/bin/sh` in the image is not bash and doesn't support `/dev/tcp`
**Verification:** `docker inspect <container> --format "{{.State.Health.Status}}"` returns `healthy`

## Pattern: Keycloak "HTTPS Required" Is a Realm-Level Setting, Not Server-Level
**Context:** Next-auth OIDC discovery from inside Docker to `host.docker.internal:8080` returning `{"error":"HTTPS required"}`
**Anti-Pattern:** Only setting server-level flags (`KC_HTTP_ENABLED=true`, `KC_HOSTNAME_STRICT=false`, `KC_HOSTNAME_STRICT_HTTPS=false`, `KC_PROXY=edge`) — these don't fix it because the "HTTPS required" is enforced at the REALM level (default: `sslRequired=external`, meaning non-loopback IPs must use HTTPS)
**Correction:** Set `"sslRequired": "none"` in the realm JSON before first import, OR use `kcadm.sh update realms/<name> -s sslRequired=NONE` on a running instance. Also add `KC_PROXY: edge` to the Keycloak service as defense-in-depth.
**Verification:** `docker exec <dashboard> node -e "fetch('http://host.docker.internal:8080/realms/ruvon/.well-known/openid-configuration').then(r=>r.json()).then(d=>console.log(d.issuer))"` returns the issuer URL instead of `{"error":"HTTPS required"}`

## Pattern: Keycloak Realm JSON Rejects Bash Variable Expansion in redirectUris
**Context:** Keycloak 24.0 realm JSON import
**Anti-Pattern:** `"${RUVON_DASHBOARD_URL:+${RUVON_DASHBOARD_URL}/*}"` in `redirectUris` — Keycloak validates each URI and rejects bash-style parameter expansion as an invalid URI format; throws `ERROR: Invalid client ruvon-dashboard: A redirect URI is not a valid URI` and crashes
**Correction:** Only put literal URIs in redirectUris (e.g., `"http://localhost:3000/*"`); add production URIs via Keycloak Admin Console or a separate realm import step
**Verification:** Keycloak logs show `Realm 'ruvon' imported` and `KC-SERVICES0032: Import finished successfully`

## Pattern: next-auth v5 beta.25 oauth4webapi HTTPS Enforcement on userInfoRequest
**Context:** next-auth v5 beta.25 OAuth provider (`type: "oauth"`) with HTTP Keycloak token/userinfo endpoints in Docker dev
**Anti-Pattern:** Setting `userinfo: "http://keycloak:8080/..."` string — auth.js routes this through `oauth4webapi.userInfoRequest()` which throws `OperationProcessingError: only requests to HTTPS are allowed` even though `authorizationCodeGrantRequest` already has `[allowInsecureRequests]: true`. The two branches have inconsistent HTTPS enforcement.
**Correction:** Provide a custom `userinfo.request` async function instead of a URL string — this bypasses oauth4webapi's enforcement using a plain `fetch`:
```typescript
userinfo: {
  url: `${KC_INTERNAL}/protocol/openid-connect/userinfo`,
  async request({ tokens }) {
    const res = await fetch(`${KC_INTERNAL}/protocol/openid-connect/userinfo`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    return res.json();
  },
},
```
**Verification:** No `CallbackRouteError` / `OperationProcessingError` in dashboard logs; `GET /api/auth/callback/keycloak` returns 302 to `/` after successful Keycloak login

## Pattern: next-auth v5 Server Action signIn() Drops OAuth State Cookies (CSRF)
**Context:** next-auth v5 beta.25 login page using a Server Action form (`"use server"` inline) to call `signIn("keycloak")`
**Anti-Pattern:** Inline server action form — Next.js Server Action redirect doesn't reliably forward the `Set-Cookie` headers for `authjs.state` / `authjs.pkce.code_verifier` to the browser; Keycloak redirects back and `validateCSRF` sees missing state cookie → `MissingCSRF` error
**Correction:** Use a `"use client"` `LoginButton` component that calls `signIn("keycloak", { callbackUrl })` from `"next-auth/react"` — client-side flow properly fetches CSRF token then POSTs to `/api/auth/signin/keycloak`, receiving cookies in the response before following the Keycloak redirect
**Verification:** `GET /api/auth/callback/keycloak` is reached after Keycloak login with no MissingCSRF error in logs

## Pattern: docker compose restart Does Not Pick Up Changed Environment Variables
**Context:** Updating environment variables in docker-compose.yml then restarting containers
**Anti-Pattern:** `docker compose restart <service>` — restarts the existing container process without re-reading the compose file; changed env vars are silently ignored
**Correction:** `docker compose up -d <service>` — detects config changes and recreates the container with the new environment
**Verification:** `docker exec <container> sh -c "echo $THE_VAR"` shows the new value

## Pattern: Next.js 14 params Is a Plain Object — Never use use(params) in Client Components
**Context:** Dynamic route `[id]/page.tsx` client components in Next.js 14 App Router
**Anti-Pattern:** `params: Promise<{ id: string }>` + `const { id } = use(params)` — `use()` only accepts a Promise or React Context; passing a plain object causes `An unsupported type was passed to use(): [object Object]` crash at runtime. This pattern is Next.js 15 only.
**Correction:** In Next.js 14 client components, `params` arrives as a plain object: `params: { id: string }` + `const { id } = params;`
**Verification:** `GET /workflows/[id]` renders without React error boundary crash

## Pattern: Server API Response Shapes Must Be Verified Before Using in Dashboard
**Context:** Ruvon dashboard API client (`packages/ruvon-dashboard/src/lib/api.ts`) against `ruvon_server/main.py`
**Key mismatches found:**
- `GET /api/v1/workflows/executions` returns bare array, not `{workflows, total, page, page_size}`; uses `offset` not `page`
- `GET /api/v1/workflow/{id}/status` returns `current_step_name` (not `current_step`); lacks `steps_config`, `current_step_info`, `audit_log`
- `POST /api/v1/workflow/{id}/next` body key is `input_data` (not `user_input`)
- `POST /api/v1/workflow/{id}/cancel` does NOT exist on server
- `GET /api/v1/policies` returns bare array (not `{policies: []}`)
- `GET /api/v1/workers/status` does NOT exist; real path is `GET /api/v1/admin/workers`
- Audit: server endpoint is `POST /api/v1/audit/query` with JSON body (not `GET /api/v1/audit` with query params)
- Devices: DB column is `last_heartbeat_at`, normalize to `last_heartbeat` in client
**Correction:** Normalize all responses in `api.ts` — wrap bare arrays, remap field names, fix HTTP methods
**Verification:** Workflow list renders, detail page loads, device fleet shows correct status

## Pattern: next-auth v5 auth() Wrapper Blocks Unauthenticated Requests Before Middleware Handler
**Context:** Playwright E2E tests using custom `x-test-bypass` header with `auth((req) => {...})` middleware pattern
**Anti-Pattern:** Putting bypass header check only inside the `auth()` wrapped handler function — the `auth()` wrapper itself has an implicit `authorized` callback that redirects unauthenticated requests to signIn before the handler executes
**Correction (1):** Add an `authorized` callback to `NextAuth({callbacks: {authorized}})` that returns `true` when `PLAYWRIGHT_TEST_BYPASS=true` env var is set and `x-test-bypass: true` header is present — or just return `true` for all requests and let the middleware handler manage redirects
**Correction (2):** Server components (layout.tsx) that call `await auth()` and redirect must also check the bypass: import `{ headers }` from `"next/headers"`, check `headers().get("x-test-bypass")`, skip `redirect("/login")` in bypass mode
**Note:** In Next.js 14, `headers()` from `next/headers` is synchronous (NOT async); do not `await` it
**Verification:** `npx playwright test` — all authenticated-page tests pass without the login page appearing

## Pattern: Playwright Test Assertions Must Match Actual Rendered Text
**Context:** Writing smoke tests before seeing the actual UI rendering
**Anti-Pattern:** Guessing heading text (`/approvals/i`, `/new workflow/i`) or using `getByText("Workflows")` without strict-mode consideration
**Correction:** Run tests once, read the `error-context.md` page snapshots (in `test-results/*/`) to see the exact rendered text, then update assertions to match. Common mismatches found: "Approval Queue" (not "Approvals"), "Start Workflow" (not "New Workflow"). Also `getByText` in strict mode fails if multiple elements match — prefer `getByRole('heading')` for unique heading assertions.
**Verification:** All 8 smoke tests pass in `npx playwright test` output

## Pattern: data_region Routes Sub-Workflow Tasks to Orphan Queue
**Context:** `StartSubWorkflowDirective(data_region="onsite-london")` in user step function
**Anti-Pattern:** Setting `data_region` to a named region without a worker listening to that queue — child workflow inherits `data_region`, all its async/parallel tasks dispatch to that queue (e.g., `onsite-london`), workers only consume `default`
**Symptom:** Parent stuck in `PENDING_SUB_WORKFLOW` indefinitely; child stuck in `PENDING_ASYNC`; worker logs go silent after chord dispatch; `LLEN default=0` but `onsite-london` queue has tasks sitting in Redis
**Diagnosis:** `docker exec test-redis redis-cli keys "*"` — look for unexpected queue names with entries; compare against queues workers actually listen to
**Correction:** Remove `data_region` (routes to `default`) OR start a worker with `-Q onsite-london`; flush orphaned queue with `redis-cli DEL <queue-name>`
**Verification:** `LLEN onsite-london` = 0 after flush; fresh workflow completes the parallel step

## Pattern: Server API Response Shapes Change — Always Verify Against DB Schema, Not Migration Script
**Context:** `GET /api/v1/workflow/{id}/audit` returning 500 after adding audit fetch to dashboard
**Anti-Pattern:** Writing SQL column names by reading a migration file (`old_state`, `new_state`, `metadata`, `logged_at`) without checking the actual table definition — the SQLAlchemy `database.py` is the source of truth; the migration may reference renamed columns
**Correction:** Always verify column names against `src/ruvon/db_schema/database.py` (or `docker exec … psql … \d <table>`). Actual `workflow_audit_log` columns: `old_status`, `new_status`, `details`, `timestamp`
**Verification:** `curl .../audit` returns `[]` (not 500); postgres logs show no "column does not exist" errors

## Pattern: Bind-Mounted site-packages Require Container Restart, Not touch
**Context:** Patching `main.py` and `api_models.py` via bind mount in `docker-compose.test-async.yml`
**Anti-Pattern:** Using `docker exec … touch <file>` to bust pyc cache on a running uvicorn server started without `--reload` — uvicorn only re-imports modules on startup; touch has no effect on a live process
**Correction:** `docker restart <container>` (or `docker compose up -d --force-recreate <service>`) to pick up source changes. Also: if a new file needs to be bind-mounted, add it to the compose volumes AND to the startup `touch` command so pyc is busted on next start
**Verification:** `curl .../status` response includes the new fields (`steps_config`, `current_step_info`)

## Pattern: Alembic Migration Index Names Must Be Globally Unique Across All Tables
**Context:** Running migration `a1b2c3d4e5f6` which creates `command_audit_log`
**Anti-Pattern:** Reusing index names like `ix_audit_event_type` across multiple tables — PostgreSQL index names are schema-scoped (not table-scoped), so creating the same name on a second table raises `DuplicateTable: relation "ix_audit_event_type" already exists`
**Correction:** Prefix indexes with the table abbreviation: `ix_cmd_audit_event_type` for `command_audit_log` vs `ix_audit_event_type` for `workflow_audit_log`
**Verification:** Migration runs without `DuplicateTable` error; `SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ix_%audit%'` shows distinct names

## Pattern: Next.js Dockerfile COPY public/ Fails When Directory Doesn't Exist
**Context:** Multi-stage Next.js Dockerfile (`Dockerfile.ruvon-dashboard-prod`) — COPY public/ in runner stage
**Anti-Pattern:** `COPY --from=builder /app/public ./public` — if the project has no `public/` directory, Docker buildx throws `failed to calculate checksum of ref ...: "/app/public": not found` and aborts the build
**Correction:** Check whether the project actually has a `public/` directory before adding the COPY line. If absent, omit it entirely — Next.js doesn't require `public/` and will serve `/_next/static/` directly from `.next/`.
**Verification:** `docker buildx build` completes without checksum error; `npm run start` serves the app

## Pattern: Sub-package `python -m build` Fails sdist for `../../` Relative Paths — Use `--wheel`
**Context:** Building `packages/ruvon-edge/` and `packages/ruvon-server/` sub-packages
**Anti-Pattern:** `python -m build` (builds both sdist and wheel) — sdist extraction validates that files don't escape the temp dir; `readme = "../../README.md"` resolves to a path outside the temp dir, raising `tarfile.OutsideDestinationError`
**Correction:** `python -m build --wheel` — skips sdist entirely; wheel build via Hatchling uses `force-include` which resolves paths correctly
**Verification:** `dist/*.whl` created successfully; no tarfile error

## Pattern: Missing Table/Column Errors → Check Alembic Revisions First
**Context:** Any server error containing "relation does not exist" or "column does not exist" (PostgreSQL) or "no such table/column" (SQLite)
**Anti-Pattern:** Immediately diving into Python source code, checking service files, or adding workarounds — the missing object almost always means a migration was never applied, not that the code is wrong.
**Correction:** Before touching any code, run this diagnostic sequence:
  1. `SELECT version_num FROM alembic_version;` — what is the DB currently stamped at?
  2. Compare against the HEAD revision in `src/ruvon/alembic/versions/` (latest file by down_revision chain)
  3. If they differ, a migration file exists in source but was never applied to this DB
  4. Root cause is usually: older Docker image (missing migration files in site-packages), or DB created before the migration was written
  5. Fix: ensure the migration file is visible to Alembic (bind-mount the versions/ directory in test compose) then re-run `alembic upgrade head`
**Verification:** `SELECT version_num FROM alembic_version` matches the HEAD revision ID; error disappears without any code changes

## Pattern: SQLite INTEGER → PostgreSQL String Mismatch on Edge Sync INSERT
**Context:** `POST /api/v1/devices/{device_id}/sync/workflows` — inserting SQLite-sourced rows into PostgreSQL via asyncpg
**Anti-Pattern:** Passing `wf.get("current_step", 0)` (int) directly to asyncpg for a `String(200)` PG column → `DataError: invalid input for query argument $5: 0 (expected str, got int)`
**Root Cause:** SQLite schema has `current_step INTEGER`; PostgreSQL schema has `current_step String(200)` (stores step *name*, not index). `SELECT *` from SQLite returns Python int, which asyncpg rejects for a varchar column.
**Correction:** Cast to string: `str(wf.get("current_step", 0))` before passing to asyncpg
**Verification:** `POST /sync/workflows` returns 200; edge logs show `[WorkflowSync] Synced N workflows`

## Pattern: .env Must Never Be Committed — Add to .gitignore Before Staging
**Context:** Staging `.env` as part of a bulk `git add .env` in the release commit
**Anti-Pattern:** `git add .env` alongside source files — the file is tracked, modified to include a real GitHub PAT, and GitHub push protection blocks the push with `GH013: Repository rule violations found`
**Correction:** (1) Add `.env` to `.gitignore` before ever staging it. (2) Run `git rm --cached .env` to stop tracking it. (3) If already committed: soft-reset the commit, unstage .env, re-commit without it. Do NOT use `--no-verify` to bypass push protection.
**Verification:** `git status` shows `.env` as untracked (??); `git push` succeeds without GH013 error

## Pattern: buf generate Fails on betterproto-Specific Proto Options — Remove Them
**Context:** Running `buf generate` after adding `option python_betterproto_package = "..."` to `.proto` files
**Anti-Pattern:** Embedding `option python_betterproto_package = "ruvon.proto.gen"` in the `.proto` file itself — buf's linter rejects it with `field python_betterproto_package of google.protobuf.FileOptions does not exist`; protoc also rejects it with `Option unknown`
**Correction:** Remove the option from `.proto` files entirely — it's redundant since `buf.gen.yaml` already carries `opt: python_package=ruvon.proto.gen`. betterproto reads the opt from buf, not from the proto file.
**Verification:** `buf generate --path src/ruvon/proto` exits 0; generated `*.py` and `*_pb2.py` appear in `gen/`

## Pattern: buf generate Requires Remote Plugin Access — Use protoc as Fallback
**Context:** Running `buf generate` when buf is installed but plugins aren't cached/available
**Anti-Pattern:** Relying only on `buf generate` in CI or offline — the betterproto plugin (`buf.build/community/danielgtaylor-python-betterproto`) is fetched from the buf registry; fails with "plugin not found" when registry is unreachable
**Correction:** Add a `make proto-protoc` target that uses local `protoc --python_out=` for the google.protobuf `_pb2.py` files. betterproto codegen still requires buf; document both paths in the Makefile.
**Verification:** `make proto-protoc` generates `*_pb2.py` files; benchmark shows google.protobuf ~50× faster encode than betterproto at same wire size

## Pattern: google.protobuf bytes Fields Require Python bytes, Not str
**Context:** Constructing `WorkflowRecord` proto message with `state_json` field
**Anti-Pattern:** `WorkflowRecord(state_json="{\"key\": \"value\"}")` — google.protobuf raises `TypeError: expected bytes, str found` for `bytes` proto fields
**Correction:** Encode strings before assigning: `WorkflowRecord(state_json=state_str.encode())`. betterproto accepts str for bytes fields but google.protobuf is strict.
**Verification:** `WR_pb.FromString(wf_pb.SerializeToString())` round-trips without TypeError

## Pattern: DTO-Returning load_workflow Must Be Unwrapped Before Dict .get() Calls
**Context:** `events.py _publish_full_workflow_state()` calling `.get()` on the result of `persistence.load_workflow()`
**Anti-Pattern:** Assuming `load_workflow()` always returns a plain dict — it returns a `WorkflowRecord` msgspec.Struct; calling `.get("status")` on it raises `AttributeError: 'WorkflowRecord' object has no attribute 'get'`
**Correction:** Check the return type and convert: `if hasattr(raw, "__struct_fields__"): workflow_dict = msgspec.to_builtins(raw)`. This is a general pattern: any code receiving the result of `load_workflow()` must handle both dict and Struct return types.
**Verification:** No `Failed to publish full workflow state` errors in server logs; Redis pub/sub delivers workflow state to dashboard WebSocket clients

## Pattern: Wrapping Per-Row INSERT Loop in asyncpg Transaction Breaks Per-Row Error Handling
**Context:** `device_service.sync_transactions()` — proposal to wrap INSERT loop in `async with conn.transaction():`
**Anti-Pattern:** Adding `async with conn.transaction():` around a loop that has per-row `try/except` — if any INSERT raises an exception, asyncpg marks the transaction as broken; no further queries can execute; remaining rows are silently skipped; partial `accepted`/`rejected` lists are returned but nothing commits
**Correction:** Keep the existing pattern (each INSERT auto-commits individually) for per-row error tolerance. Only wrap in a transaction if you're willing to accept all-or-nothing semantics (which SAF sync is not).
**Verification:** A batch with one bad row still accepts all valid rows; `accepted` list has the correct entries

## Pattern: asyncpg Batch UPDATE column = ANY($n::uuid[]) Fails When Column Is varchar
**Context:** `device_service._get_pending_commands()` batch-updating `device_commands.status` for a list of IDs
**Anti-Pattern:** `WHERE command_id = ANY($2::uuid[])` — if `command_id` is `character varying` (not `uuid`), asyncpg raises `operator does not exist: character varying = uuid`; PostgreSQL cannot compare varchar to uuid without an explicit cast
**Correction:** Match the cast to the actual column type: `WHERE command_id = ANY($2::text[])`. Always check the DB schema (`\d device_commands`) before writing array-cast SQL.
**Verification:** NATSBridge heartbeat handler no longer logs `operator does not exist: character varying = uuid`

## Pattern: aiosqlite Connection Must Be Closed Before pytest-asyncio Tears Down Per-Test Event Loop
**Context:** `tests/edge/test_agent_wasm_integration.py` — tests that call `agent.start()` which opens an aiosqlite connection internally
**Anti-Pattern:** Starting the agent (which opens `aiosqlite.connect(":memory:")`) inside a test without a matching `await conn.close()` in teardown. pytest-asyncio creates and closes a new event loop per test; aiosqlite's background I/O thread has pending futures bound to the old loop → the loop never shuts down → test suite hangs indefinitely (confirmed 18+ hours)
**Correction:** Wrap test setup/teardown in an `asynccontextmanager` that calls `await agent.persistence.close()` in the `finally` block. Also explicitly `.close()` any coroutines passed to `mock asyncio.create_task` to suppress "never awaited" warnings.
**Pattern:**
```python
@asynccontextmanager
async def started_agent():
    agent = make_agent()
    await _start_agent_minimal(agent)
    try:
        yield agent
    finally:
        if agent.persistence:
            await agent.persistence.close()
        agent._is_running = False
```
**Verification:** Full test suite runs in <5s with no hanging processes; `ps aux | grep pytest` shows no zombie processes

## Pattern: CLI Tests That Invoke Infinite-Loop Daemons Must Be Skipped
**Context:** `tests/cli/test_zombie_commands.py` — `test_zombie_daemon_custom_interval` and `test_zombie_daemon_with_db_url`
**Anti-Pattern:** Using `cli_runner.invoke(app, ["zombie-daemon", ...], input="\n")` hoping that `"\n"` as stdin causes the daemon to exit — the zombie-daemon command runs an infinite polling loop; stdin input is not monitored; `cli_runner.invoke` blocks forever
**Correction:** Mark both tests `@pytest.mark.skip(reason="Daemon runs indefinitely - cannot be tested without signal injection")`. Only test daemon behavior via unit tests that mock the sleep loop, not via CLI invocation.
**Verification:** `pytest tests/cli/test_zombie_commands.py` completes in 0.06s; full suite shows 4 passed 6 skipped for that file

## Pattern: New API Request Fields That Expand a Protocol Must Be Optional
**Context:** `DeviceHeartbeatRequest.vector_advisory` in `api_models.py` — added in RUVON Phase 5
**Anti-Pattern:** Adding `vector_advisory: Dict[str, Any]` (required field) — all deployed edge agents that don't know about RUVON start failing heartbeat POSTs with 422 Unprocessable Entity the moment the server is updated
**Correction:** Always add new request body fields as `Optional[...] = Field(default=None)`. The server handles `None` gracefully (skip the DB write), and old agents continue working without modification. Only promote to required after a coordinated fleet upgrade.
**Verification:** An old-format heartbeat `{"device_status": "online", "metrics": {}}` returns 200 on the updated server; no 422 errors in logs

## Pattern: Topology Queries Should JOIN the Device Registry in One Query, Not N Lookups
**Context:** `device_service.get_mesh_topology()` — extended in RUVON Phase 5 to include relay_server_url, mesh_advisory per node
**Anti-Pattern:** Fetching relay metadata with a separate `SELECT ... WHERE device_id = $1` inside a loop over nodes — O(N) round-trips to the DB for a fleet of N devices, making topology queries slow under load
**Correction:** Extend the existing `SELECT device_id, device_type FROM edge_devices WHERE device_id = ANY($1::text[])` to also fetch `relay_server_url, mesh_advisory` in the same query. Build lookup dicts (`relay_url_map`, `advisory_map`) and join in Python. One DB round-trip regardless of fleet size.
**Verification:** `get_mesh_topology()` for 100 devices generates 2 SQL queries (edges + device metadata), not 102

## Pattern: Leaderboards Should Sort by the Computed Score, Not the Raw Activity Count
**Context:** `browser_demo_2/worker.js` LEADERBOARD message — extended in RUVON Phase 5
**Anti-Pattern:** Sorting heroes by `relayLoadTotal` (lifetime relay count) — a device that was busy relaying for a long time but is now degraded (low C, overloaded P) ranks above a fresh, healthy device with fewer relays but a higher current vector score
**Correction:** Sort by `vectorScore = 0.50C + 0.15/H + 0.25U + 0.10P`. Include both `count` (for display) and `score` (for sorting) in each hero entry. The leaderboard then reflects current capability, not historical busyness.
**Verification:** When a high-relay device goes offline (C=0.0), its score drops to ≈0.025 and it falls to the bottom of the leaderboard regardless of relay count

## Pattern: Circuit Breakers Must Have a Half-Open Recovery State
**Context:** `peer_relay.py` MeshRouter per-peer failure tracking for RUVON mesh routing
**Anti-Pattern:** `return failures >= threshold` — once a peer accumulates N failures it is permanently skipped; a device that was temporarily offline and has recovered is never re-probed
**Correction:** Three-state check using `last_fail` timestamp: CLOSED (failures < threshold) → OPEN (failures ≥ threshold AND last_fail within cooldown) → HALF-OPEN (failures ≥ threshold AND last_fail > cooldown seconds ago, allow one probe). A successful half-open probe resets failures to 0 (→ CLOSED); a failed probe updates `last_fail` (restarts the cooldown, stays OPEN). Store `_CB_HALF_OPEN_SECS` as a named constant at module level for easy tuning.
**Verification:** After 3 failures, peer is skipped; after cooldown elapses, one probe is allowed; success restores normal routing

## Pattern: Network Self-Registration Must Re-Check Each Sync Cycle, Not Just At Startup
**Context:** `agent._register_relay_server()` — RUVON peer relay URL stored in cloud DB
**Anti-Pattern:** Calling `_register_relay_server()` once in `start()` via `asyncio.create_task()` — if DHCP assigns a new IP between restarts or during a long run, the cloud holds a stale URL; other devices probe a dead address and take 3× 2s timeouts before the circuit opens
**Correction:** (1) Use outbound-route IP detection (`socket.connect("8.8.8.8", 80); getsockname()[0]`) instead of `getfqdn()` — gives the actual LAN IP even on multi-homed hosts. (2) Cache the last-registered host in `edge_sync_state["relay_server_host"]`; compare before each cloud POST (no-op when stable = single SQLite read). (3) Call `_register_relay_server()` at the end of `_refresh_mesh_peers()` so it fires every online sync cycle.
**Verification:** Change LAN IP; within one sync interval the cloud record updates and probes resume succeeding

## Pattern: Distributed Election Tie-Breaking Requires Deterministic Per-Device Backoff
**Context:** `agent._run_election()` — RUVON Local Master election when cloud is unreachable
**Anti-Pattern:** Fixed 500ms self-promotion timeout for all devices — two devices with identical leadership scores both wait 500ms, both see no objection, both self-promote → dual-master split-brain
**Correction:** Seed the backoff from the device ID: `seed = int(hashlib.sha256(device_id.encode()).hexdigest()[:8], 16); backoff_ms = 100 + (seed % 400)`. This gives each device a unique, stable wait time (100–500ms). Apply the same tie-break in the claim endpoint: `incoming_wins = score > my_score OR (score == my_score AND incoming_device_id < device_id)`. The lexicographically lower device_id always wins ties — consistent across all nodes without coordination.
**Verification:** Two equal-score devices always elect the same one (lower device_id) regardless of timing

## Pattern: PostgreSQL state Column Is TEXT, Not JSONB — Cast Before Extracting Fields
**Context:** `GET /api/v1/metrics/edge-impact` — aggregating `amount` from `workflow_executions.state`
**Anti-Pattern:** `state_data->>'action'` or `state->>'field'` — column `state_data` doesn't exist; `state` is `TEXT`, not `JSONB`; the `->>`/`->` operators only work on `jsonb`; raises `column "state_data" does not exist` or `operator does not exist: text ->> unknown`
**Correction:** Cast to json first: `(state::json)->>'action'` and `((state::json)->>'amount')::numeric`. Use `COALESCE(SUM(...), 0)` to handle rows where the field is absent.
**Verification:** `GET /metrics/edge-impact` returns non-zero values; no `operator does not exist` in postgres logs

## Pattern: TypeScript null vs undefined — API JSON Returns null, Not undefined
**Context:** `NodeTooltip` in fleet-topology — guarding optional RUVON fields like `vector_score`
**Anti-Pattern:** `if (node.vector_score !== undefined)` — JSON serialization converts Python `None` to JSON `null`, which deserializes to JavaScript `null`, not `undefined`. `null !== undefined` is `true`, so the guard passes and `.toFixed(3)` crashes with `Cannot read properties of null`
**Correction:** Use loose equality `!= null` which catches both `null` and `undefined`: `if (node.vector_score != null)`. Apply the same guard everywhere: leaderboard sort, stats bar count, tooltip rendering.
**Verification:** No `Cannot read properties of null` crash in browser console; tooltip renders correctly for devices without VectorAdvisory

## Pattern: Canvas Z-Order — Draw Overlapping Elements in a Second Pass, Not Inline
**Context:** Fleet topology canvas — rendering ★ local master badge on top of all nodes
**Anti-Pattern:** Drawing the star inside the node render loop at `r * 1.1` px offset (radius-relative, as small as 4px) — any subsequent node draw call covers it; star is invisible when nodes overlap
**Correction:** Add a dedicated second render pass after the node loop. Draw all decorations (stars, badges) at a fixed size (18px) with a dark stroke for contrast and gold glow:
```typescript
ctx.font = `bold 18px sans-serif`;
for (const node of masterNodes) {
  ctx.strokeStyle = "rgba(0,0,0,0.85)"; ctx.lineWidth = 3;
  ctx.strokeText("★", pos.x, pos.y - 18);
  ctx.fillStyle = "#ffd700";
  ctx.fillText("★", pos.x, pos.y - 18);
}
```
This guarantees z-order — stars are always on top regardless of node rendering order.
**Verification:** ★ is visible on every local master node; not covered by adjacent nodes

## Pattern: Alembic upgrade head Fails on Pre-Existing Tables — Stamp + Raw SQL as Escape Hatch
**Context:** Migration `a1b2c3d4e5f6` trying to create ~15 tables that were already created outside Alembic (init-db.sql, manual runs)
**Anti-Pattern:** Trying to fix all conflicts in the migration file and re-run — each run hits a new `DuplicateTable` in a transactional DDL block, rolling back everything, requiring another round-trip
**Correction:** Create only the missing table(s) directly via `asyncpg` with `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`, then stamp: `INSERT INTO alembic_version (version_num) VALUES ('<rev>') ON CONFLICT DO NOTHING`. Worker container has psycopg2; server container does not.
**Verification:** `SELECT version_num FROM alembic_version` shows the new revision; target endpoint returns 200

## Pattern: Edit Tool new_string Must Use Real Newlines, Not \n Escape Sequences
**Context:** Adding a multi-line HTML section to `architecture.html` via the Edit tool
**Anti-Pattern:** Writing `\n` as a two-character escape sequence inside the `new_string` parameter — the Edit tool writes them as literal backslash-n characters in the file. The browser renders `\n` as visible text: section headings show correctly but paragraph text, pre blocks, and table rows all display `\n` scattered through the content.
**Correction:** Always use actual newlines (press Enter) inside `new_string` blocks. When a large multi-line block needs to be inserted, use the Write tool to rewrite the whole file, or use a Bash heredoc + Python script to do the replacement. The Edit tool's `new_string` is not a string literal in a programming language — it does not interpret escape sequences.
**Verification:** Open the HTML file in a browser and confirm no visible `\n` characters appear in rendered text; `python3 -c "print(open('file.html').read().count('\\\\n'))"` returns 0

## Pattern: FastAPI Route Precedence — Sub-Router Stub Shadows Real Handler
**Context:** `device_approvals.py` had a stub `POST /{device_id}/heartbeat` route; real handler in `main.py` registered later
**Anti-Pattern:** Assuming FastAPI evaluates all routes and picks the "best match" — it returns the **first** match. A stub in a sub-router included early silently intercepts all requests, returning a partial response without touching the DB. In this case `last_heartbeat_at` stayed NULL, every device showed OFFLINE.
**Correction:** Search all routers for duplicate path patterns before diagnosing server-side logic. Remove any stub routes that were added for scaffolding.
**Verification:** `grep -r "heartbeat" src/ruvon_server/api/` — only one route definition should match the heartbeat path. After removal, DB shows non-NULL `last_heartbeat_at` for active devices.

## Pattern: asyncpg Requires Naive Datetime for TIMESTAMP WITHOUT TIME ZONE Columns
**Context:** Changing `datetime.utcnow()` to `datetime.now(timezone.utc)` in `device_service.py`
**Anti-Pattern:** Passing a timezone-aware `datetime` object to asyncpg for a `TIMESTAMP WITHOUT TIME ZONE` column — asyncpg raises `DataError: can't subtract offset-naive and offset-aware datetimes` and the INSERT/UPDATE fails silently (or crashes the endpoint).
**Correction:** `datetime.now(timezone.utc).replace(tzinfo=None)` — correct UTC time, tzinfo stripped so asyncpg accepts it.
**Verification:** `process_heartbeat` completes without DataError; `last_heartbeat_at` shows a non-NULL timestamp in the DB.

## Pattern: Load Test Metrics Pipeline — Every Scenario Loop Must Call metrics_callback
**Context:** `_saf_sync_scenario` was one-shot; progress reporter showed `req=0` for the entire 300s test.
**Anti-Pattern:** Forgetting to call `await self.metrics_callback(device_id, self.metrics)` inside a scenario loop — `orchestrator._aggregated_metrics` is only populated via this callback, so the progress reporter and final results stay at zero.
**Correction:** Every scenario loop body must call `metrics_callback` after incrementing counters. Also ensure the scenario is duration-bounded (loop until `end_time`) not one-shot.
**Verification:** Progress output shows rising `req=` count throughout the test window, not a flat zero.

## Pattern: Throughput Targets Need Effective-Duration Denominator for Jittered Scenarios
**Context:** CONFIG_POLL scenario adds startup jitter (0–60s) before first poll; wall-clock duration was 422s for a 300s test.
**Anti-Pattern:** Dividing total requests by raw `duration_seconds` — startup jitter + trailing sleep inflate wall time by up to 2×poll_interval, making a perfectly healthy scenario appear to fail its throughput target.
**Correction:** `effective_duration = max(results.duration_seconds - poll_interval, 1)` removes the ramp and tail, matching how the heartbeat scenario accounts for stagger. Apply to CONFIG_POLL and any scenario with startup jitter.
**Verification:** Effective req/s matches the per-device rate visible in the rolling progress output.

## Pattern: Bounded SAF Transaction Pool Prevents Docker Disk Exhaustion Under Load
**Context:** 1000 devices each generating 50–150 unique transactions per cycle → 2.1M rows, 1.27GB in 5 min → Docker virtual disk exhausted, PostgreSQL `pg_subtrans` writes failed.
**Anti-Pattern:** Generating unique transaction IDs every cycle — each cycle adds N rows permanently, DB grows unboundedly. At 1000 devices this exhausts Docker's default 60GB virtual disk in a single test run.
**Correction:** Build a fixed transaction pool once per device (e.g. 50 rows). Re-send the same pool each cycle — server deduplicates via `ON CONFLICT (idempotency_key) DO NOTHING`. DB stays bounded; test measures HTTP/auth/idempotency throughput accurately.
**Verification:** `SELECT count(*) FROM saf_transactions` stays bounded (≤ devices × pool_size) throughout a 300s test at 1000 devices.
