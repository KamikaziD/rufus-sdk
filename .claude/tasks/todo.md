# Rufus Dashboard — React/Next.js UI (v0.7.0 candidate)

## Phase 1 — Scaffold + Auth ✅
- [x] Create `packages/rufus-dashboard/package.json`
- [x] Create `packages/rufus-dashboard/tsconfig.json` + `next.config.ts` + `tailwind.config.ts`
- [x] Create root app layout + globals.css + providers.tsx
- [x] Create `src/lib/auth.ts` (next-auth v5 + Keycloak)
- [x] Create `src/middleware.ts` (route protection + RBAC)
- [x] Create `src/lib/roles.ts` (RBAC matrix + NAV_ITEMS)
- [x] Create `src/lib/api.ts` (typed API client)
- [x] Create `src/types/index.ts` (shared TypeScript types)
- [x] Create login page + auth callback route
- [x] Create Sidebar + Topbar + RoleGate + StatusBadge + LiveIndicator
- [x] Add Keycloak service to `docker/docker-compose.yml`
- [x] Create `docker/keycloak/rufus-realm.json`
- [x] Update `docker/.env.example` with Keycloak + Next.js vars
- [x] Add CORS `localhost:3000` to `src/rufus_server/main.py`

## Phase 2 — Workflow Features ✅
- [x] Overview page (KPI cards + sparklines + recent executions)
- [x] `/workflows` — executions table with filters + pagination
- [x] `/workflows/new` — start workflow form
- [x] `/workflows/[id]` — detail: Steps + DAG + State + Logs + HITL tabs
- [x] `/workflows/[id]/debug` — debug stepper with state diff
- [x] `WorkflowDAG`, `HitlForm`, `StepTimeline`, `StatePanel`, `DebugStepper`
- [x] `useWorkflow`, `useWorkflowStream` hooks

## Phase 3 — Device Management ✅
- [x] `/devices` — DeviceGrid with polling + status filters
- [x] `/devices/[id]` — device detail (Overview, Commands, Config tabs)
- [x] `CommandSender` component + `useDevice` hook
- [x] `/approvals` — HITL Approval Queue
- [x] `ApprovalQueue` component + `useApprovals` hook

## Phase 4 — Advanced Features ✅
- [x] `/policies` — policies list
- [x] `ConfigPushWizard` (4-step wizard)
- [x] `/audit` — audit log query + pagination + export button
- [x] `/schedules` + `/admin` (workers tab) pages
- [x] `KpiCards`, `WorkflowChart` components

## Phase 5 — Polish + Docs ✅
- [x] `packages/rufus-dashboard/README.md`
- [x] shadcn/ui primitive stubs (Button, Card, Badge inline)
- [x] Dark mode CSS variables in globals.css

## Phase 6 — Stub Completion + Browser Tests ✅
- [x] `src/app/(dashboard)/schedules/page.tsx` — full CRUD (list, pause/resume/cancel, create)
- [x] `src/app/(dashboard)/admin/page.tsx` — Rate Limits + Webhooks tabs implemented
- [x] `src/app/(dashboard)/devices/page.tsx` — Registration modal (Radix Dialog)
- [x] `src/app/(dashboard)/devices/[id]/page.tsx` — SAF Transactions tab added
- [x] `src/components/devices/ConfigPushWizard.tsx` — submit wired, live polling progress panel
- [x] `src/lib/api.ts` — 15 new typed functions (schedules, rate limits, webhooks, SAF, rollout)
- [x] `src/lib/hooks/useSchedules.ts` — new hook file created
- [x] `src/components/ui/dialog.tsx` — Radix Dialog wrapper
- [x] TypeScript type-check → 0 errors
- [x] Production build → 0 errors (13 pages)
- [x] Playwright smoke tests (8/8 passing)

### Key Fixes Required for Tests
- `src/lib/auth.ts` — `authorized` callback returns `true` to let middleware handler run bypass logic
- `src/app/(dashboard)/layout.tsx` — check `x-test-bypass` header via `headers()` to skip `redirect("/login")` in bypass mode
- `e2e/smoke.spec.ts` — updated assertions to match actual headings ("Approval Queue", "Start Workflow", role heading selector)

## Phase 7 — Dashboard Completion + Infrastructure (2026-03-02) ✅
- [x] **Audit export** — `exportAuditLogs()` fetches blob + triggers browser download; format select (JSON/CSV) + onClick wired to Export button in audit/page.tsx
- [x] **GET /api/v1/devices/{device_id}/commands** — new endpoint in main.py; calls `device_service.list_commands()`; `limit`/`offset`/`status` query params; tags: Commands
- [x] **listDeviceCommands()** stub replaced — real apiFetch; normalizes `command_data→payload`, `completed_at→executed_at`, injects `device_id`
- [x] **listPolicies()** normalization — maps `id→policy_id`, `policy_name→name`, lowercase status→uppercase
- [x] **createPolicy() + updatePolicyStatus()** added to api.ts
- [x] **policies/page.tsx** — Create Policy button + Radix Dialog modal (policy_name, description, condition, artifact); Activate/Pause/Archive action buttons per row; useMutation hooks
- [x] **rufus_test/docker-compose.test-async.yml** created — postgres, redis, rufus-server (ruhfuskdev images); server command: pip install psycopg2-binary + alembic upgrade head + uvicorn; bind-mounts for main.py + api_models.py
- [x] **build-production-images.sh** — migrated from `docker build` to `docker buildx build --platform linux/amd64,linux/arm64 --push`; auto-creates `rufus-builder` buildx instance; single-arch `--load` fallback for local testing
- [x] TypeScript type-check → 0 errors

## Review

### Proof of Work
**56 files created** in `packages/rufus-dashboard/`:
- 6 config/build files (package.json, tsconfig, next.config, tailwind, postcss, .env.example)
- 13 app route files (login, dashboard layout, 10 pages, auth API route)
- 21 component files (ui/, shared/, layouts/, workflows/, devices/, approvals/, metrics/)
- 8 lib files (auth, api, roles, utils, 4 hooks)
- 1 types file, 1 middleware file, 1 README

**Backend changes (3 files):**
- `src/rufus_server/main.py` — CORSMiddleware added (localhost:3000)
- `docker/docker-compose.yml` — Keycloak service added
- `docker/keycloak/rufus-realm.json` — 5 roles, 5 seed users (all pw: rufus-dev)
- `docker/.env.example` — Keycloak + Next.js + CORS vars

### Next Steps (user-facing)
1. `cd packages/rufus-dashboard && npm install`
2. `cp .env.example .env.local` and fill `NEXTAUTH_SECRET`
3. Start backend: `cd docker && docker compose up -d` (includes Keycloak)
4. Start dashboard: `npm run dev` → http://localhost:3000
5. Login with seed user `operator` / `rufus-dev`
