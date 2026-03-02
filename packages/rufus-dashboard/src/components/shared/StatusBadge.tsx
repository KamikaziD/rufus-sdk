import { Badge } from "@/components/ui/badge";
import type { WorkflowStatus, DeviceStatus } from "@/types";

const WORKFLOW_STATUS_MAP: Record<WorkflowStatus, { label: string; variant: "default" | "success" | "destructive" | "warning" | "info" | "secondary" | "outline" }> = {
  PENDING:                  { label: "Pending",          variant: "secondary" },
  RUNNING:                  { label: "Running",          variant: "info" },
  COMPLETED:                { label: "Completed",        variant: "success" },
  FAILED:                   { label: "Failed",           variant: "destructive" },
  FAILED_ROLLED_BACK:       { label: "Rolled Back",      variant: "destructive" },
  FAILED_WORKER_CRASH:      { label: "Worker Crash",     variant: "destructive" },
  CANCELLED:                { label: "Cancelled",        variant: "secondary" },
  WAITING_HUMAN:            { label: "Awaiting Input",   variant: "warning" },
  PENDING_ASYNC:            { label: "Async",            variant: "info" },
  PENDING_SUB_WORKFLOW:     { label: "Sub-Workflow",     variant: "info" },
  WAITING_CHILD_HUMAN_INPUT:{ label: "Child HITL",       variant: "warning" },
  FAILED_CHILD_WORKFLOW:    { label: "Child Failed",     variant: "destructive" },
};

const DEVICE_STATUS_MAP: Record<DeviceStatus, { label: string; variant: "success" | "destructive" | "warning" | "secondary" }> = {
  online:      { label: "Online",      variant: "success" },
  offline:     { label: "Offline",     variant: "destructive" },
  maintenance: { label: "Maintenance", variant: "warning" },
  unknown:     { label: "Unknown",     variant: "secondary" },
};

export function WorkflowStatusBadge({ status }: { status: WorkflowStatus }) {
  const config = WORKFLOW_STATUS_MAP[status] ?? { label: status, variant: "secondary" as const };
  return <Badge variant={config.variant}>{config.label}</Badge>;
}

export function DeviceStatusBadge({ status }: { status: DeviceStatus }) {
  const config = DEVICE_STATUS_MAP[status] ?? { label: status, variant: "secondary" as const };
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
