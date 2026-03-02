// ── Workflow Types ──────────────────────────────────────────────────────────

export type WorkflowStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "FAILED_ROLLED_BACK"
  | "FAILED_WORKER_CRASH"
  | "CANCELLED"
  | "WAITING_HUMAN"
  | "PENDING_ASYNC"
  | "PENDING_SUB_WORKFLOW"
  | "WAITING_CHILD_HUMAN_INPUT"
  | "FAILED_CHILD_WORKFLOW";

export interface WorkflowExecution {
  workflow_id: string;
  workflow_type: string;
  status: WorkflowStatus;
  current_step: string | null;
  started_at: string;
  completed_at: string | null;
  state: Record<string, unknown>;
  error: string | null;
  owner: string | null;
}

export interface WorkflowListResponse {
  workflows: WorkflowExecution[];
  total: number;
  page: number;
  page_size: number;
}

export interface StepInfo {
  name: string;
  type: string;
  description?: string;
  input_schema?: Record<string, unknown>;
}

export interface WorkflowStatusResponse {
  workflow_id: string;
  status: WorkflowStatus;
  current_step: string | null;
  current_step_info: StepInfo | null;
  state: Record<string, unknown>;
  steps_config: StepConfig[];
  audit_log: AuditEntry[];
  // Optional fields returned by server but not always present
  workflow_type?: string;
  parent_execution_id?: string;
  blocked_on_child_id?: string;
}

export interface StepConfig {
  name: string;
  type: string;
  description?: string;
  next?: string;
  routes?: Record<string, string>;
  tasks?: string[];
}

export interface AuditEntry {
  timestamp: string;
  event: string;
  step?: string;
  details?: Record<string, unknown>;
}

// ── Device Types ────────────────────────────────────────────────────────────

export type DeviceStatus = "online" | "offline" | "maintenance" | "unknown";

export interface Device {
  device_id: string;
  device_type: string;
  merchant_id: string;
  status: DeviceStatus;
  last_heartbeat: string | null;
  firmware_version: string | null;
  sdk_version: string | null;
  pending_saf_count: number;
  metadata: Record<string, unknown>;
}

export interface DeviceListResponse {
  devices: Device[];
  total: number;
}

export interface DeviceCommand {
  command_id: string;
  device_id: string;
  command_type: string;
  payload: Record<string, unknown>;
  status: "pending" | "sent" | "acknowledged" | "failed";
  created_at: string;
  executed_at: string | null;
}

// ── Policy Types ─────────────────────────────────────────────────────────────

export type PolicyStatus = "ACTIVE" | "PAUSED" | "ARCHIVED";

export interface Policy {
  policy_id: string;
  name: string;
  description: string;
  status: PolicyStatus;
  rules: PolicyRule[];
  created_at: string;
  updated_at: string;
}

export interface PolicyRule {
  rule_id: string;
  condition: string;
  action: string;
  priority: number;
}

// ── Audit Types ──────────────────────────────────────────────────────────────

export interface AuditLog {
  log_id: string;
  timestamp: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  actor: string;
  details: Record<string, unknown>;
}

export interface AuditQueryResponse {
  logs: AuditLog[];
  total: number;
}

// ── Auth / RBAC Types ────────────────────────────────────────────────────────

export type RufusRole =
  | "SUPER_ADMIN"
  | "FLEET_MANAGER"
  | "WORKFLOW_OPERATOR"
  | "AUDITOR"
  | "READ_ONLY";

export interface RufusUser {
  id: string;
  name: string;
  email: string;
  roles: RufusRole[];
  org_id?: string;
  accessToken: string;
}
