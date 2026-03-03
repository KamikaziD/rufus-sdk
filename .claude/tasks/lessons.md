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

## Pattern: Docker Bind-Mounts Bypass Python .pyc Cache Via touch, Not Deletion
**Context:** Patching installed Python packages in a pre-built Docker image via bind-mounted `.py` files (test docker-compose)
**Anti-Pattern:** Trying to `find ... -name '*.pyc' -delete` or `chmod` the `__pycache__` directory — the directories are owned by root inside the image, so non-root container user gets "Permission denied"
**Correction:** `touch` the mounted source files before starting uvicorn: `touch /usr/local/lib/python3.11/site-packages/pkg/patched.py`. Python validates pyc by mtime+size stored in the pyc header; a newer mtime on the source triggers recompile from source, and if the container can't write the new pyc it just uses the in-memory compiled version
**Verification:** No `ModuleNotFoundError` from old cached code; log shows expected behavior from the patched module

## Pattern: rufus-server Image Missing celery+redis — Must Install at Startup for Celery Backend
**Context:** Running `ruhfuskdev/rufus-server:latest` with `WORKFLOW_EXECUTION_BACKEND: celery`
**Anti-Pattern:** Image only has fastapi/uvicorn/asyncpg; `CeleryExecutionProvider.__init__` imports `from rufus.celery_app import celery_app` which imports `from celery import Celery` — crash at startup
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
**Anti-Pattern:** `test: ["CMD-SHELL", "curl -sf http://localhost:8080/realms/rufus || exit 1"]` — Keycloak 24.0 base image has no `curl` or `wget`; healthcheck always fails
**Correction:** Use bash's built-in `/dev/tcp` pseudo-device: `test: ["CMD", "bash", "-c", "(echo > /dev/tcp/localhost/8080) 2>/dev/null"]`. Note: must use `CMD` (not `CMD-SHELL`) to invoke bash explicitly, since `/bin/sh` in the image is not bash and doesn't support `/dev/tcp`
**Verification:** `docker inspect <container> --format "{{.State.Health.Status}}"` returns `healthy`

## Pattern: Keycloak "HTTPS Required" Is a Realm-Level Setting, Not Server-Level
**Context:** Next-auth OIDC discovery from inside Docker to `host.docker.internal:8080` returning `{"error":"HTTPS required"}`
**Anti-Pattern:** Only setting server-level flags (`KC_HTTP_ENABLED=true`, `KC_HOSTNAME_STRICT=false`, `KC_HOSTNAME_STRICT_HTTPS=false`, `KC_PROXY=edge`) — these don't fix it because the "HTTPS required" is enforced at the REALM level (default: `sslRequired=external`, meaning non-loopback IPs must use HTTPS)
**Correction:** Set `"sslRequired": "none"` in the realm JSON before first import, OR use `kcadm.sh update realms/<name> -s sslRequired=NONE` on a running instance. Also add `KC_PROXY: edge` to the Keycloak service as defense-in-depth.
**Verification:** `docker exec <dashboard> node -e "fetch('http://host.docker.internal:8080/realms/rufus/.well-known/openid-configuration').then(r=>r.json()).then(d=>console.log(d.issuer))"` returns the issuer URL instead of `{"error":"HTTPS required"}`

## Pattern: Keycloak Realm JSON Rejects Bash Variable Expansion in redirectUris
**Context:** Keycloak 24.0 realm JSON import
**Anti-Pattern:** `"${RUFUS_DASHBOARD_URL:+${RUFUS_DASHBOARD_URL}/*}"` in `redirectUris` — Keycloak validates each URI and rejects bash-style parameter expansion as an invalid URI format; throws `ERROR: Invalid client rufus-dashboard: A redirect URI is not a valid URI` and crashes
**Correction:** Only put literal URIs in redirectUris (e.g., `"http://localhost:3000/*"`); add production URIs via Keycloak Admin Console or a separate realm import step
**Verification:** Keycloak logs show `Realm 'rufus' imported` and `KC-SERVICES0032: Import finished successfully`

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
**Context:** Rufus dashboard API client (`packages/rufus-dashboard/src/lib/api.ts`) against `rufus_server/main.py`
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
**Correction:** Always verify column names against `src/rufus/db_schema/database.py` (or `docker exec … psql … \d <table>`). Actual `workflow_audit_log` columns: `old_status`, `new_status`, `details`, `timestamp`
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
**Context:** Multi-stage Next.js Dockerfile (`Dockerfile.rufus-dashboard-prod`) — COPY public/ in runner stage
**Anti-Pattern:** `COPY --from=builder /app/public ./public` — if the project has no `public/` directory, Docker buildx throws `failed to calculate checksum of ref ...: "/app/public": not found` and aborts the build
**Correction:** Check whether the project actually has a `public/` directory before adding the COPY line. If absent, omit it entirely — Next.js doesn't require `public/` and will serve `/_next/static/` directly from `.next/`.
**Verification:** `docker buildx build` completes without checksum error; `npm run start` serves the app

## Pattern: Sub-package `python -m build` Fails sdist for `../../` Relative Paths — Use `--wheel`
**Context:** Building `packages/rufus-sdk-edge/` and `packages/rufus-sdk-server/` sub-packages
**Anti-Pattern:** `python -m build` (builds both sdist and wheel) — sdist extraction validates that files don't escape the temp dir; `readme = "../../README.md"` resolves to a path outside the temp dir, raising `tarfile.OutsideDestinationError`
**Correction:** `python -m build --wheel` — skips sdist entirely; wheel build via Hatchling uses `force-include` which resolves paths correctly
**Verification:** `dist/*.whl` created successfully; no tarfile error

## Pattern: Alembic upgrade head Fails on Pre-Existing Tables — Stamp + Raw SQL as Escape Hatch
**Context:** Migration `a1b2c3d4e5f6` trying to create ~15 tables that were already created outside Alembic (init-db.sql, manual runs)
**Anti-Pattern:** Trying to fix all conflicts in the migration file and re-run — each run hits a new `DuplicateTable` in a transactional DDL block, rolling back everything, requiring another round-trip
**Correction:** Create only the missing table(s) directly via `asyncpg` with `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`, then stamp: `INSERT INTO alembic_version (version_num) VALUES ('<rev>') ON CONFLICT DO NOTHING`. Worker container has psycopg2; server container does not.
**Verification:** `SELECT version_num FROM alembic_version` shows the new revision; target endpoint returns 200
