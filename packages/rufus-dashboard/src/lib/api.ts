import type {
  WorkflowListResponse,
  WorkflowStatusResponse,
  WorkflowExecution,
  DeviceListResponse,
  Device,
  AuditQueryResponse,
  Policy,
  DeviceCommand,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_RUFUS_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(
  path: string,
  token: string | undefined,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail ?? msg;
    } catch {}
    throw new ApiError(res.status, msg);
  }

  return res.json() as Promise<T>;
}

// ── Workflow API ─────────────────────────────────────────────────────────────

export async function listWorkflows(
  token: string,
  params: { status?: string; type?: string; limit?: number; page?: number; since?: string } = {}
): Promise<WorkflowListResponse> {
  const q = new URLSearchParams();
  if (params.status) q.set("status", params.status);
  if (params.type)   q.set("workflow_type", params.type);
  if (params.limit)  q.set("limit", String(params.limit));
  // Server uses `offset`, not `page`
  if (params.page)   q.set("offset", String(((params.page ?? 1) - 1) * (params.limit ?? 50)));
  if (params.since)  q.set("since", params.since);
  // Server returns { total, workflows } envelope
  const raw = await apiFetch<{ total: number; workflows: Record<string, unknown>[] }>(
    `/api/v1/workflows/executions?${q}`,
    token
  );
  const workflows = raw.workflows.map((wf) => ({
    workflow_id: (wf.id ?? wf.workflow_id) as string,
    workflow_type: wf.workflow_type as string,
    status: wf.status as WorkflowExecution["status"],
    current_step: (wf.current_step ?? null) as string | null,
    started_at: (wf.created_at ?? wf.updated_at ?? new Date().toISOString()) as string,
    completed_at: (wf.completed_at ?? null) as string | null,
    state: (wf.state ?? {}) as Record<string, unknown>,
    error: (wf.error ?? null) as string | null,
    owner: (wf.owner_id ?? wf.owner ?? null) as string | null,
  }));
  return { workflows, total: raw.total, page: params.page ?? 1, page_size: params.limit ?? 50 };
}

export async function getWorkflow(token: string, id: string): Promise<WorkflowStatusResponse> {
  const [raw, auditRaw] = await Promise.all([
    apiFetch<Record<string, unknown>>(`/api/v1/workflow/${id}/status`, token),
    apiFetch<Record<string, unknown>[]>(`/api/v1/workflow/${id}/audit`, token).catch(() => []),
  ]);
  return {
    workflow_id: raw.workflow_id as string,
    status: raw.status as WorkflowStatusResponse["status"],
    current_step: (raw.current_step_name ?? raw.current_step ?? null) as string | null,
    current_step_info: (raw.current_step_info ?? null) as WorkflowStatusResponse["current_step_info"],
    state: (raw.state ?? {}) as Record<string, unknown>,
    steps_config: (raw.steps_config ?? []) as WorkflowStatusResponse["steps_config"],
    audit_log: (Array.isArray(auditRaw) ? auditRaw : []).map((e) => ({
      timestamp: e.timestamp as string,
      event:     e.event_type as string,
      step:      e.step_name as string | undefined,
      details:   { old: e.old_status, new: e.new_status, ...((e.details as Record<string, unknown>) ?? {}) },
    })) as WorkflowStatusResponse["audit_log"],
    workflow_type: raw.workflow_type as string | undefined,
  };
}

// The server returns an array: [{ type: string, description: string, ... }]
// Normalize to { types: string[] } for the dropdown
export async function getWorkflowTypes(token: string): Promise<{ types: string[] }> {
  const raw = await apiFetch<Array<{ type: string }>>("/api/v1/workflows", token);
  return { types: raw.map((w) => w.type) };
}

export function startWorkflow(
  token: string,
  body: { workflow_type: string; initial_data?: Record<string, unknown>; dry_run?: boolean }
): Promise<{ workflow_id: string; status: string }> {
  return apiFetch("/api/v1/workflow/start", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function resumeWorkflow(
  token: string,
  id: string,
  userInput: Record<string, unknown>
): Promise<unknown> {
  return apiFetch(`/api/v1/workflow/${id}/resume`, token, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function nextWorkflowStep(
  token: string,
  id: string,
  userInput: Record<string, unknown> = {}
): Promise<unknown> {
  // Server expects `input_data` (WorkflowStepRequest), not `user_input`
  return apiFetch(`/api/v1/workflow/${id}/next`, token, {
    method: "POST",
    body: JSON.stringify({ input_data: userInput }),
  });
}

export function retryWorkflow(token: string, id: string): Promise<unknown> {
  return apiFetch(`/api/v1/workflow/${id}/retry`, token, { method: "POST" });
}

export function cancelWorkflow(token: string, id: string): Promise<unknown> {
  // No dedicated cancel endpoint on server — best-effort via retry (will 404 gracefully)
  return apiFetch(`/api/v1/workflow/${id}/cancel`, token, { method: "POST" });
}

export function rewindWorkflow(token: string, id: string): Promise<unknown> {
  return apiFetch(`/api/v1/workflow/${id}/rewind`, token, { method: "POST" });
}

export async function getWorkflowLogs(token: string, id: string): Promise<{ logs: unknown[] }> {
  // Server returns bare array; normalize to { logs }
  const raw = await apiFetch<unknown[] | { logs?: unknown[] }>(`/api/v1/workflow/${id}/logs`, token);
  if (Array.isArray(raw)) return { logs: raw };
  return { logs: (raw as { logs?: unknown[] }).logs ?? [] };
}

// ── Device API ───────────────────────────────────────────────────────────────

function normalizeDevice(raw: Record<string, unknown>): Device {
  return {
    device_id:        raw.device_id as string,
    device_type:      (raw.device_type ?? "unknown") as string,
    merchant_id:      (raw.merchant_id ?? "unknown") as string,
    status:           (raw.status ?? "unknown") as Device["status"],
    // Server stores last_heartbeat_at, normalize to last_heartbeat
    last_heartbeat:   (raw.last_heartbeat ?? raw.last_heartbeat_at ?? null) as string | null,
    firmware_version: (raw.firmware_version ?? null) as string | null,
    sdk_version:      (raw.sdk_version ?? null) as string | null,
    pending_saf_count: (raw.pending_saf_count ?? 0) as number,
    metadata:         (raw.metadata ?? raw.config ?? {}) as Record<string, unknown>,
  };
}

export async function listDevices(token: string): Promise<DeviceListResponse> {
  const raw = await apiFetch<{ devices: Record<string, unknown>[]; total: number }>(
    "/api/v1/devices",
    token
  );
  return {
    devices: (raw.devices ?? []).map(normalizeDevice),
    total:   raw.total ?? 0,
  };
}

export async function getDevice(token: string, id: string): Promise<Device> {
  const raw = await apiFetch<Record<string, unknown>>(`/api/v1/devices/${id}`, token);
  return normalizeDevice(raw);
}

export function sendDeviceCommand(
  token: string,
  deviceId: string,
  command: { command_type: string; payload: Record<string, unknown>; priority?: number }
): Promise<DeviceCommand> {
  return apiFetch(`/api/v1/devices/${deviceId}/commands`, token, {
    method: "POST",
    body: JSON.stringify(command),
  });
}

export async function listDeviceCommands(token: string, deviceId: string): Promise<{ commands: DeviceCommand[] }> {
  const raw = await apiFetch<{ commands: Array<Record<string, unknown>>; total: number }>(
    `/api/v1/devices/${deviceId}/commands`,
    token
  );
  const commands = (raw.commands ?? []).map((c) => ({
    command_id:   c.command_id as string,
    device_id:    deviceId,
    command_type: c.command_type as string,
    payload:      (c.command_data ?? {}) as Record<string, unknown>,
    status:       (c.status ?? "pending") as DeviceCommand["status"],
    created_at:   c.created_at as string,
    executed_at:  (c.completed_at ?? c.sent_at ?? null) as string | null,
  }));
  return { commands };
}

// ── Audit API ────────────────────────────────────────────────────────────────

export async function queryAuditLogs(
  token: string,
  params: { from?: string; to?: string; event_type?: string; entity_id?: string; limit?: number; page?: number } = {}
): Promise<AuditQueryResponse> {
  // Server endpoint is POST /api/v1/audit/query with a JSON body
  const body: Record<string, unknown> = {};
  if (params.from)       body.start_time = params.from;
  if (params.to)         body.end_time   = params.to;
  if (params.event_type) body.event_types = [params.event_type];
  if (params.entity_id)  body.device_id  = params.entity_id;
  if (params.limit)      body.limit      = params.limit;
  if (params.page)       body.offset     = ((params.page ?? 1) - 1) * (params.limit ?? 50);

  const raw = await apiFetch<{ entries: unknown[]; total_count?: number }>(
    "/api/v1/audit/query",
    token,
    { method: "POST", body: JSON.stringify(body) }
  );
  // Normalize to AuditQueryResponse shape
  const entries = (raw.entries ?? []) as AuditQueryResponse["logs"];
  return { logs: entries, total: raw.total_count ?? entries.length };
}

export async function exportAuditLogs(
  token: string,
  format: "json" | "csv",
  params: Record<string, string> = {}
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}/api/v1/audit/export`, {
    method: "POST",
    headers,
    body: JSON.stringify({ format, ...params }),
  });

  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail ?? msg;
    } catch {}
    throw new ApiError(res.status, msg);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `audit-export.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Policy API ───────────────────────────────────────────────────────────────

function normalizePolicy(raw: Record<string, unknown>): Policy {
  return {
    policy_id:   (raw.policy_id ?? raw.id ?? "") as string,
    name:        (raw.name ?? raw.policy_name ?? "") as string,
    description: (raw.description ?? "") as string,
    status:      ((raw.status as string ?? "DRAFT").toUpperCase()) as Policy["status"],
    rules:       (raw.rules ?? []) as Policy["rules"],
    created_at:  (raw.created_at ?? "") as string,
    updated_at:  (raw.updated_at ?? "") as string,
  };
}

export async function listPolicies(token: string): Promise<{ policies: Policy[] }> {
  // Server returns bare array of Policy objects with `policy_name` and `id` fields
  const raw = await apiFetch<Record<string, unknown>[] | { policies?: Record<string, unknown>[] }>(
    "/api/v1/policies",
    token
  );
  const arr = Array.isArray(raw) ? raw : (raw.policies ?? []);
  return { policies: arr.map(normalizePolicy) };
}

export function createPolicy(
  token: string,
  body: {
    policy_name: string;
    description?: string;
    version?: string;
    rules: Array<{ condition: string; artifact: string; priority?: number; description?: string }>;
  }
): Promise<Record<string, unknown>> {
  return apiFetch("/api/v1/policies", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updatePolicyStatus(
  token: string,
  policyId: string,
  status: "active" | "paused" | "archived"
): Promise<{ status: string; new_status: string }> {
  return apiFetch(`/api/v1/policies/${policyId}/status?new_status=${status}`, token, {
    method: "PUT",
  });
}

// ── Worker Fleet API ─────────────────────────────────────────────────────────

export interface WorkerSummary {
  worker_id: string;
  hostname: string;
  region: string;
  zone: string;
  capabilities: Record<string, unknown>;
  status: string;
  sdk_version: string | null;
  last_heartbeat: string | null;
  pending_command_count: number;
}

export interface WorkerCommand {
  command_id: string;
  worker_id: string | null;
  command_type: string;
  command_data: Record<string, unknown>;
  status: string;
  priority: string;
  created_at: string | null;
  delivered_at: string | null;
  executed_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
}

export async function listWorkers(
  token: string | undefined,
  params?: { status?: string; region?: string; limit?: number; offset?: number }
): Promise<{ workers: WorkerSummary[]; total: number }> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.region) q.set("region", params.region);
  if (params?.limit)  q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  return apiFetch(`/api/v1/workers?${q}`, token);
}

export async function getWorkerById(
  token: string | undefined,
  workerId: string
): Promise<WorkerSummary> {
  return apiFetch(`/api/v1/workers/${encodeURIComponent(workerId)}`, token);
}

export function sendWorkerCommand(
  token: string | undefined,
  workerId: string,
  body: { command_type: string; command_data?: Record<string, unknown>; priority?: string; expires_in_seconds?: number }
): Promise<{ command_id: string; worker_id: string; status: string }> {
  return apiFetch(`/api/v1/workers/${encodeURIComponent(workerId)}/commands`, token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function broadcastWorkerCommand(
  token: string | undefined,
  body: { target_filter?: Record<string, unknown>; command_type: string; command_data?: Record<string, unknown>; priority?: string; expires_in_seconds?: number }
): Promise<{ command_id: string; status: string; broadcast: boolean }> {
  return apiFetch("/api/v1/workers/broadcast", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listWorkerCommands(
  token: string | undefined,
  workerId: string,
  params?: { status?: string; limit?: number; offset?: number }
): Promise<{ commands: WorkerCommand[]; total: number }> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.limit)  q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  return apiFetch(`/api/v1/workers/${encodeURIComponent(workerId)}/commands?${q}`, token);
}

export function cancelWorkerCommand(
  token: string | undefined,
  commandId: string
): Promise<{ command_id: string; status: string }> {
  return apiFetch(`/api/v1/workers/commands/${encodeURIComponent(commandId)}`, token, {
    method: "DELETE",
  });
}

// ── Metrics API ───────────────────────────────────────────────────────────────

export function getMetrics(token: string): Promise<Record<string, unknown>> {
  return apiFetch("/api/v1/metrics/summary", token);
}

export function getSystemHealth(token: string): Promise<{ workers: WorkerSummary[] }> {
  return listWorkers(token);
}

// ── Schedule API ─────────────────────────────────────────────────────────────

export interface Schedule {
  schedule_id: string;
  schedule_name: string;
  device_id: string | null;
  command_type: string;
  schedule_type: string;
  status: "pending" | "active" | "paused" | "completed" | "cancelled" | "failed";
  cron_expression: string | null;
  timezone: string | null;
  next_execution_at: string | null;
  last_execution_at: string | null;
  execution_count: number;
  max_executions: number | null;
  created_at: string;
}

export async function listSchedules(
  token: string,
  params: { device_id?: string; status?: string; limit?: number } = {}
): Promise<{ schedules: Schedule[]; count: number }> {
  const q = new URLSearchParams();
  if (params.device_id) q.set("device_id", params.device_id);
  if (params.status)    q.set("status", params.status);
  if (params.limit)     q.set("limit", String(params.limit));
  return apiFetch(`/api/v1/schedules?${q}`, token);
}

export function createSchedule(
  token: string,
  body: {
    schedule_name: string;
    command_type: string;
    schedule_type: string;
    device_id?: string;
    cron_expression?: string;
    execute_at?: string;
    max_executions?: number;
    command_data?: Record<string, unknown>;
  }
): Promise<{ schedule_id: string; status: string }> {
  return apiFetch("/api/v1/schedules", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function pauseSchedule(token: string, id: string): Promise<unknown> {
  return apiFetch(`/api/v1/schedules/${id}/pause`, token, { method: "POST" });
}

export function resumeSchedule(token: string, id: string): Promise<unknown> {
  return apiFetch(`/api/v1/schedules/${id}/resume`, token, { method: "POST" });
}

export function cancelSchedule(token: string, id: string): Promise<unknown> {
  return apiFetch(`/api/v1/schedules/${id}/cancel`, token, { method: "POST" });
}

// ── Rate Limit API (Admin) ────────────────────────────────────────────────────

export interface RateLimitRule {
  rule_name: string;
  resource_pattern: string;
  scope: string;
  limit_per_window: number;
  window_seconds: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export async function listRateLimits(
  token: string,
  is_active?: boolean
): Promise<{ rules: RateLimitRule[]; total: number }> {
  const q = is_active !== undefined ? `?is_active=${is_active}` : "";
  return apiFetch(`/api/v1/admin/rate-limits${q}`, token);
}

export function createRateLimitRule(
  token: string,
  body: {
    rule_name: string;
    resource_pattern: string;
    scope: string;
    limit_per_window: number;
    window_seconds: number;
    is_active?: boolean;
  }
): Promise<{ rule_name: string; status: string }> {
  return apiFetch("/api/v1/admin/rate-limits", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateRateLimitRule(
  token: string,
  ruleName: string,
  body: { limit_per_window?: number; window_seconds?: number; is_active?: boolean }
): Promise<{ rule_name: string; status: string }> {
  return apiFetch(`/api/v1/admin/rate-limits/${encodeURIComponent(ruleName)}`, token, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

// ── Webhook API ───────────────────────────────────────────────────────────────

export interface Webhook {
  webhook_id: string;
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
  created_at?: string;
}

export interface WebhookDelivery {
  delivery_id: string;
  event_type: string;
  status_code: number | null;
  success: boolean;
  attempted_at: string;
  error_message?: string | null;
}

export async function listWebhooks(
  token: string,
  is_active?: boolean
): Promise<{ webhooks: Webhook[]; total: number }> {
  const q = is_active !== undefined ? `?is_active=${is_active}` : "";
  return apiFetch(`/api/v1/webhooks${q}`, token);
}

export function createWebhook(
  token: string,
  body: { name: string; url: string; events: string[]; secret?: string }
): Promise<{ webhook_id: string; status: string }> {
  return apiFetch("/api/v1/webhooks", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteWebhook(token: string, id: string): Promise<unknown> {
  return apiFetch(`/api/v1/webhooks/${id}`, token, { method: "DELETE" });
}

export async function getWebhookDeliveries(
  token: string,
  webhookId: string,
  limit = 5
): Promise<{ deliveries: WebhookDelivery[]; total: number }> {
  return apiFetch(`/api/v1/webhooks/${webhookId}/deliveries?limit=${limit}`, token);
}

export function testWebhook(
  token: string,
  body: { url: string; event_type: string; event_data?: Record<string, unknown>; secret?: string }
): Promise<{ status: string; url: string }> {
  return apiFetch("/api/v1/webhooks/test", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ── Device Registration ───────────────────────────────────────────────────────

export function registerDevice(
  token: string,
  body: {
    device_id: string;
    device_type: string;
    device_name: string;
    merchant_id: string;
    firmware_version: string;
    sdk_version: string;
    location?: string;
    capabilities?: string[];
  }
): Promise<{ device_id: string; api_key: string; config_url: string; sync_url: string }> {
  return apiFetch("/api/v1/devices/register", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ── Device SAF Transactions ───────────────────────────────────────────────────

export interface SafTransaction {
  transaction_id: string;
  amount: number | null;
  currency: string | null;
  status: string;
  created_at: string;
  synced_at: string | null;
}

export async function getDeviceSafTransactions(
  token: string,
  deviceId: string
): Promise<{ transactions: SafTransaction[] }> {
  try {
    const raw = await apiFetch<{ transactions?: SafTransaction[] } | SafTransaction[]>(
      `/api/v1/devices/${deviceId}/saf`,
      token
    );
    if (Array.isArray(raw)) return { transactions: raw };
    return { transactions: (raw as { transactions?: SafTransaction[] }).transactions ?? [] };
  } catch {
    // Endpoint may not exist in all deployments — return empty list
    return { transactions: [] };
  }
}

// ── Config Rollout ────────────────────────────────────────────────────────────

export function startConfigRollout(
  token: string,
  body: { policy_id?: string; target_devices?: string[]; rollout_strategy?: string }
): Promise<{ workflow_id: string; status: string; rollout_outcome?: string }> {
  return apiFetch("/api/v1/config/rollout", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getRolloutStatus(
  token: string,
  policyId?: string
): Promise<{ total_devices: number; status_breakdown: Record<string, number>; by_policy: Record<string, Record<string, number>> }> {
  const q = policyId ? `?policy_id=${encodeURIComponent(policyId)}` : "";
  return apiFetch(`/api/v1/rollout/status${q}`, token);
}

// ── Workflow Definitions (DB-backed, hot-reload) ──────────────────────────────

export interface WorkflowDefinition {
  id: number;
  workflow_type: string;
  version: number;
  is_active: boolean;
  description: string | null;
  uploaded_by: string | null;
  created_at: string | null;
  yaml_content?: string;
  resolved_config?: Record<string, unknown> | null;
}

export function listWorkflowDefinitions(
  token: string
): Promise<WorkflowDefinition[]> {
  return apiFetch("/api/v1/admin/workflow-definitions", token);
}

export function getWorkflowDefinition(
  token: string,
  workflowType: string
): Promise<WorkflowDefinition> {
  return apiFetch(
    `/api/v1/admin/workflow-definitions/${encodeURIComponent(workflowType)}`,
    token
  );
}

export function getWorkflowDefinitionHistory(
  token: string,
  workflowType: string
): Promise<WorkflowDefinition[]> {
  return apiFetch(
    `/api/v1/admin/workflow-definitions/${encodeURIComponent(workflowType)}/history`,
    token
  );
}

export function uploadWorkflowDefinition(
  token: string,
  body: { workflow_type: string; yaml_content: string; description?: string }
): Promise<WorkflowDefinition> {
  return apiFetch("/api/v1/admin/workflow-definitions", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchWorkflowDefinition(
  token: string,
  workflowType: string,
  yaml_content: string
): Promise<WorkflowDefinition> {
  return apiFetch(
    `/api/v1/admin/workflow-definitions/${encodeURIComponent(workflowType)}`,
    token,
    { method: "PATCH", body: JSON.stringify({ yaml_content }) }
  );
}

export function deleteWorkflowDefinition(
  token: string,
  workflowType: string
): Promise<{ workflow_type: string; status: string }> {
  return apiFetch(
    `/api/v1/admin/workflow-definitions/${encodeURIComponent(workflowType)}`,
    token,
    { method: "DELETE" }
  );
}

// ── Server Commands ───────────────────────────────────────────────────────────

export interface ServerCommand {
  id: string;
  command: string;
  payload: Record<string, unknown>;
  status: string;
  result: Record<string, unknown> | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export function listServerCommands(
  token: string,
  limit = 50
): Promise<ServerCommand[]> {
  return apiFetch(`/api/v1/admin/server/commands?limit=${limit}`, token);
}

export function sendServerCommand(
  token: string,
  body: {
    command: "reload_workflows" | "gc_caches" | "update_code" | "restart";
    payload?: Record<string, unknown>;
  }
): Promise<{ id: string; command: string; status: string }> {
  return apiFetch("/api/v1/admin/server/commands", token, {
    method: "POST",
    body: JSON.stringify({ payload: {}, ...body }),
  });
}

export function cancelServerCommand(
  token: string,
  commandId: string
): Promise<{ id: string; status: string }> {
  return apiFetch(
    `/api/v1/admin/server/commands/${encodeURIComponent(commandId)}/cancel`,
    token,
    { method: "PATCH" }
  );
}

// ── Push workflow definition to edge devices ─────────────────────────────────

export function pushWorkflowToDevices(
  token: string,
  body: {
    workflow_type: string;
    version: number;
    yaml_content: string;
    target_filter?: Record<string, string>;
  }
): Promise<{ command_id: string; status: string; broadcast: boolean }> {
  return apiFetch("/api/v1/devices/commands/broadcast", token, {
    method: "POST",
    body: JSON.stringify({
      command: "update_workflow",
      command_data: {
        workflow_type: body.workflow_type,
        version: body.version,
        yaml_content: body.yaml_content,
      },
      target_filter: body.target_filter ?? {},
    }),
  });
}
