# How to Deploy and Use the Rufus Dashboard

This guide covers deploying the Rufus Dashboard, logging in, assigning roles, and using each page of the management UI. It assumes you already have the Rufus API server running.

---

## Prerequisites

- Docker Compose with the Rufus stack running (`rufus-server`, `rufus-worker`, `postgres`, `redis`)
- A Keycloak instance **or** any OIDC-compatible identity provider
- The `rufus-dashboard` Docker image (`ruhfuskdev/rufus-dashboard:1.0.0rc5`)

---

## Deploying the Dashboard

Add the `rufus-dashboard` service to your compose file:

```yaml
rufus-dashboard:
  image: ruhfuskdev/rufus-dashboard:1.0.0rc5
  ports: ["3000:3000"]
  environment:
    NEXT_PUBLIC_RUFUS_API_URL: http://localhost:8000   # baked at build time
    NEXTAUTH_URL: http://localhost:3000
    NEXTAUTH_SECRET: change-me-in-production
    KEYCLOAK_ISSUER: http://localhost:8080/realms/rufus
    KEYCLOAK_ID: rufus-dashboard
    KEYCLOAK_SECRET: your-keycloak-client-secret
  depends_on: [rufus-server]
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_RUFUS_API_URL` | Yes | Base URL of the Rufus REST API (baked into the image at build time; default: `http://localhost:8000`) |
| `NEXTAUTH_URL` | Yes | Public URL of the dashboard itself |
| `NEXTAUTH_SECRET` | Yes | Random string used to sign session tokens (minimum 32 chars) |
| `KEYCLOAK_ISSUER` | Yes | OIDC issuer URL, e.g. `http://keycloak:8080/realms/rufus` |
| `KEYCLOAK_ID` | Yes | OIDC client ID registered in Keycloak |
| `KEYCLOAK_SECRET` | Yes | OIDC client secret |

> If you need a custom API URL baked into the image, rebuild from source with `--build-arg NEXT_PUBLIC_RUFUS_API_URL=https://api.example.com`.

A full Keycloak compose configuration is provided at `docker/docker-compose.keycloak.yml`.

---

## Logging In

1. Open `http://localhost:3000` in your browser.
2. Click **Sign In** — you are redirected to Keycloak.
3. Enter your Keycloak credentials and complete the login flow.
4. You are redirected back to the dashboard Overview page.

If you see a redirect loop, check [Troubleshooting](#troubleshooting) below.

---

## Role Reference

Rufus uses five roles. Assign them to users or groups in Keycloak under the `rufus-dashboard` client roles.

| Role | Access |
|------|--------|
| `SUPER_ADMIN` | Everything — Admin panel, policy management, server commands |
| `FLEET_MANAGER` | Devices, Workers, Policies (read), Schedules |
| `WORKFLOW_OPERATOR` | Workflows, Approvals, Schedules, Workers (read) |
| `AUDITOR` | Workflows (read), Devices (read), Audit log, Policies (read) |
| `READ_ONLY` | Workflows and Devices (read-only) |

Roles are propagated via JWT claims included in every API request. A user with no assigned role lands on the Overview page but sees no data.

---

## Navigating the UI

### Overview

The home page for all roles. Shows five live KPI cards:

- **Active Workflows** — workflows currently in `RUNNING` or `PENDING_*` state
- **Online Workers** — Celery workers that have sent a heartbeat in the last 60 seconds
- **Pending Approvals** — workflows paused at a `HUMAN_IN_LOOP` step
- **Registered Devices** — total devices in the registry
- **Recent Failures** — workflows that entered `FAILED` status in the last 24 hours

Cards auto-refresh every 30 seconds.

---

### Workflows

Available to `WORKFLOW_OPERATOR` and above. Use this page to:

- **Filter** by status, workflow type, or date range
- **Start** a new workflow — select type, paste initial state JSON
- **Resume** a paused workflow by supplying `user_input` JSON
- **Cancel** or **Retry** a failed workflow
- **Debug** — open the step-through stepper to inspect each step's input/output and state delta
- **DAG view** — click the graph icon to render the workflow definition as a ReactFlow DAG
- **Audit trail** — expand any workflow row to see the full event log

---

### Approvals

Available to `WORKFLOW_OPERATOR` and above. This page shows all workflows currently paused at a `HUMAN_IN_LOOP` step.

For each pending approval:
1. Click the row to expand the approval request context (the step's description and current state snapshot).
2. Add optional notes.
3. Click **Approve** or **Reject**.

Approved workflows resume immediately; rejected workflows transition to `FAILED`.

#### Domain-Specific Review Panels (v1.0.0rc5)

The Approvals page renders specialised panels based on `workflow_type`, replacing the generic JSON textarea for known workflow types:

| Workflow Type | Panel | What it Shows |
|---------------|-------|---------------|
| `FraudCaseReview` | **FraudReviewPanel** | Transaction details, risk score, flagged typologies, merchant, Approve / Reject with notes |
| `LoanApplication` | **LoanReviewPanel** | Credit score bar, fraud check badge, applicant profile, underwriting recommendation, KYC status dots; Approve Loan / Reject Loan buttons |

Both panels also render inline in the **Workflows** console (`ConsoleDetailPanel`) when a workflow is in `WAITING_HUMAN` state — analysts can approve directly from the workflow detail view without navigating to the Approvals page.

Panel selection is driven by `workflow_type` in the workflow execution record.

---

### Devices

Available to `FLEET_MANAGER` and above. The device registry shows every edge device that has ever connected.

Per-device detail page shows:
- Last heartbeat timestamp and connectivity status
- Installed workflow versions (from the last config sync)
- Command history — commands sent and their results
- **Send Command** button — trigger a one-off device command (e.g. `sync_now`, `update_workflow`)

---

### Workers

Available to `FLEET_MANAGER` and above (read-only for `WORKFLOW_OPERATOR`). Shows the live Celery worker fleet.

**9 command types** can be sent to individual workers or broadcast to the whole fleet:

| Command | Effect |
|---------|--------|
| `restart` | Gracefully restart the worker process |
| `pool_restart` | Restart the worker's process pool without full restart |
| `drain` | Stop accepting new tasks; finish current tasks then exit |
| `update_code` | Pull latest code and restart |
| `update_config` | Reload configuration from the server |
| `pause_queue` | Stop consuming from the task queue |
| `resume_queue` | Resume consuming from the task queue |
| `set_concurrency` | Change the worker's concurrency level |
| `check_health` | Return a health snapshot (memory, queue depth, active tasks) |

Use **Broadcast** to send a command to all workers simultaneously (e.g., `reload_workflows` after pushing a new definition).

---

### Policies

Available to `FLEET_MANAGER` and above. Create, edit, and delete fraud rules and config policies that are pushed to edge devices.

Each policy has:
- **Name** and **description**
- **Type** (`fraud_rule`, `config_override`, `floor_limit`)
- **Payload** — JSON body interpreted by the edge agent
- **Assigned devices** — push to specific devices or all devices

---

### Schedules

Available to `ADMIN` and `WORKFLOW_OPERATOR`. Create cron-based workflow schedules.

Each schedule entry specifies:
- **Workflow type** to start
- **Cron expression** (standard 5-field or quartz 6-field)
- **Timezone**
- **Max runs** (leave blank for indefinite)
- **Initial state** JSON passed to each triggered workflow

---

### Audit

Available to `ADMIN` and `AUDITOR`. The full compliance log of every workflow event.

- Filter by workflow ID, status transition, step name, date range, or actor
- Click any row to see the full before/after state diff
- **Export** — download the filtered result set as JSON for compliance reporting

---

### Admin

`SUPER_ADMIN` only. Two tabs:

**Definitions tab** — manage live workflow YAML:
- Upload a YAML file or paste content into the inline editor
- Click **Preview DAG** to render the step graph with ReactFlow
- Edit DECISION step conditions in the side panel without touching raw YAML
- **Push to Devices** — broadcasts the definition to all connected edge devices via the `update_workflow` server command
- **Activate** — makes a definition the default for new workflow instances on the server

**Server Commands tab** — trigger maintenance operations:
- `reload_workflows` — hot-reload all workflow definitions without restarting
- `gc_caches` — flush import and template caches
- `update_code` — pull latest code and reload (requires code volume mount)
- `restart` — gracefully restart all workers

---

## Live Workflow Updates (Admin → Server Tab)

This step-by-step covers the full flow for updating a workflow without redeployment:

1. **Open Admin → Definitions** in the dashboard.
2. Click **New Definition** or select an existing one.
3. Paste or type the updated YAML into the editor.
4. Click **Preview DAG** — verify the graph matches your intent.
5. If the workflow has DECISION steps, click a DECISION node in the DAG to open the condition editor and update route conditions inline.
6. Click **Save** — the definition is stored in the `workflow_definitions` table on the server.
7. Click **Push to Devices** — the server broadcasts an `update_workflow` command to all registered edge devices. Each device's `ConfigManager` receives the YAML and reloads it into `WorkflowBuilder`.
8. Click **Activate** — new workflow instances on the server now use this definition.
9. Open **Admin → Server Commands**, select `reload_workflows`, and click **Send** — all Celery workers hot-reload definitions without restarting.
10. Verify: start a new workflow of the updated type and confirm the new steps appear in the DAG view on the Workflows page.

---

## Troubleshooting

### Auth redirect loop (login page keeps reloading)

- Confirm `NEXTAUTH_URL` matches the exact URL you are using in the browser (including port).
- Check that `KEYCLOAK_ISSUER` is reachable from **inside** the dashboard container. Use the container-internal hostname (e.g. `http://keycloak:8080/realms/rufus`) not the host machine URL.
- Ensure `sslRequired` is set to `none` in the Keycloak realm for development (HTTP) deployments.

### API unreachable (dashboard shows "Failed to fetch")

- Confirm `NEXT_PUBLIC_RUFUS_API_URL` points to the correct API host. This value is baked into the image at build time — if the URL is wrong, you must rebuild or use the default `http://localhost:8000`.
- Check that `rufus-server` is healthy: `curl http://localhost:8000/health` should return `{"status":"ok"}`.

### CORS errors in browser console

- The Rufus API server reads `CORS_ORIGINS` from the environment. Add the dashboard origin: `CORS_ORIGINS=http://localhost:3000`.
- Restart the API server after changing `CORS_ORIGINS`.

### Keycloak "HTTPS required" error

- This is a realm-level setting, not a server flag. Set `sslRequired` to `none` in your realm JSON before import, or update it via the Keycloak Admin Console under **Realm Settings → General → Require SSL**.

### Workers page shows no workers

- Workers register on startup. If the page is empty, confirm at least one `rufus-worker` container is running and connected to the same PostgreSQL and Redis instances as the server.
- Check worker logs for `Registered worker` confirmation.
