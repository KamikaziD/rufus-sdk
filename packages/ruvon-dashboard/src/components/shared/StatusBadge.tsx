import type { WorkflowStatus, DeviceStatus } from "@/types";

interface BadgeConfig {
  label: string;
  cls: string;
}

const WORKFLOW_STATUS_MAP: Record<WorkflowStatus, BadgeConfig> = {
  PENDING:                   { label: "PENDING",       cls: "border-zinc-600 text-zinc-500 bg-zinc-800/50" },
  RUNNING:                   { label: "RUNNING",       cls: "border-amber-500/40 text-amber-400 bg-amber-500/10 animate-pulse" },
  COMPLETED:                 { label: "COMPLETED",     cls: "border-emerald-500/40 text-emerald-400 bg-emerald-500/10" },
  FAILED:                    { label: "FAILED",        cls: "border-red-500/40 text-red-400 bg-red-500/10" },
  FAILED_ROLLED_BACK:        { label: "ROLLED BACK",   cls: "border-red-500/40 text-red-400 bg-red-500/10" },
  FAILED_WORKER_CRASH:       { label: "WORKER CRASH",  cls: "border-red-500/40 text-red-400 bg-red-500/10" },
  CANCELLED:                 { label: "CANCELLED",     cls: "border-zinc-600 text-zinc-500 bg-zinc-800/50" },
  WAITING_HUMAN:             { label: "HITL",          cls: "border-yellow-500/40 text-yellow-400 bg-yellow-500/10 animate-pulse" },
  PENDING_ASYNC:             { label: "ASYNC",         cls: "border-blue-500/40 text-blue-400 bg-blue-500/10" },
  PENDING_SUB_WORKFLOW:      { label: "SUB-WORKFLOW",  cls: "border-blue-500/40 text-blue-400 bg-blue-500/10" },
  WAITING_CHILD_HUMAN_INPUT: { label: "CHILD HITL",   cls: "border-yellow-500/40 text-yellow-400 bg-yellow-500/10 animate-pulse" },
  FAILED_CHILD_WORKFLOW:     { label: "CHILD FAILED",  cls: "border-red-500/40 text-red-400 bg-red-500/10" },
};

const DEVICE_STATUS_MAP: Record<DeviceStatus, BadgeConfig> = {
  online:      { label: "ONLINE",      cls: "border-emerald-500/40 text-emerald-400 bg-emerald-500/10" },
  offline:     { label: "OFFLINE",     cls: "border-red-500/40 text-red-400 bg-red-500/10" },
  maintenance: { label: "MAINTENANCE", cls: "border-yellow-500/40 text-yellow-400 bg-yellow-500/10" },
  unknown:     { label: "UNKNOWN",     cls: "border-zinc-600 text-zinc-500 bg-zinc-800/50" },
};

function ConsoleBadge({ label, cls }: BadgeConfig) {
  return (
    <span className={`inline-flex items-center border px-1.5 py-0.5 font-mono text-[10px] tracking-wider rounded-none ${cls}`}>
      {label}
    </span>
  );
}

export function WorkflowStatusBadge({ status }: { status: WorkflowStatus }) {
  const config = WORKFLOW_STATUS_MAP[status] ?? { label: status, cls: "border-zinc-600 text-zinc-500 bg-zinc-800/50" };
  return <ConsoleBadge {...config} />;
}

export function DeviceStatusBadge({ status }: { status: DeviceStatus }) {
  const config = DEVICE_STATUS_MAP[status] ?? { label: status, cls: "border-zinc-600 text-zinc-500 bg-zinc-800/50" };
  return <ConsoleBadge {...config} />;
}
