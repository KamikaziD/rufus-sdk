"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { LiveIndicator } from "@/components/shared/LiveIndicator";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { RoleGate } from "@/components/shared/RoleGate";
import { Bug, Network, RefreshCw, Play, RotateCcw, X } from "lucide-react";
import type { WorkflowStatus } from "@/types";

function useLiveDuration(startedAt: string | null, status: WorkflowStatus, completedAt?: string | null) {
  const [duration, setDuration] = useState("—");

  useEffect(() => {
    const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK", "FAILED_WORKER_CRASH", "FAILED_CHILD_WORKFLOW"];
    if (!startedAt) return;

    function fmt(ms: number) {
      const s = Math.floor(ms / 1000);
      const m = Math.floor(s / 60);
      const h = Math.floor(m / 60);
      if (h > 0) return `${h}h ${m % 60}m`;
      return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
    }

    if (TERMINAL.includes(status) && completedAt) {
      setDuration(fmt(new Date(completedAt).getTime() - new Date(startedAt).getTime()));
      return;
    }

    function tick() {
      setDuration(fmt(Date.now() - new Date(startedAt!).getTime()));
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt, status, completedAt]);

  return duration;
}

function ConsoleButton({
  children,
  onClick,
  variant = "default",
  disabled,
  asChild,
  href,
  active,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "default" | "amber" | "red" | "ghost";
  disabled?: boolean;
  asChild?: boolean;
  href?: string;
  active?: boolean;
}) {
  const base = "inline-flex items-center gap-1.5 font-mono text-xs border px-2 py-1 rounded-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed";
  const variants = {
    default: `border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 ${active ? "bg-zinc-700/50 border-zinc-500" : ""}`,
    amber:   "border-amber-500/40 text-amber-400 hover:bg-amber-500/10",
    red:     "border-red-500/40 text-red-400 hover:bg-red-500/10",
    ghost:   "border-transparent text-zinc-500 hover:text-zinc-200",
  };

  if (href) {
    return (
      <Link href={href} className={`${base} ${variants[variant]}`}>
        {children}
      </Link>
    );
  }

  return (
    <button className={`${base} ${variants[variant]}`} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

interface WorkflowHeaderProps {
  id: string;
  workflowType: string | null;
  status: WorkflowStatus;
  currentStep: string | null;
  totalSteps: number;
  startedAt: string | null;
  completedAt?: string | null;
  connected: boolean;
  showDAG: boolean;
  onToggleDAG: () => void;
  onRefresh: () => void;
  onAdvance: () => void;
  onRewind: () => void;
  onCancel: () => void;
}

export function WorkflowHeader({
  id,
  workflowType,
  status,
  currentStep,
  totalSteps,
  startedAt,
  completedAt,
  connected,
  showDAG,
  onToggleDAG,
  onRefresh,
  onAdvance,
  onRewind,
  onCancel,
}: WorkflowHeaderProps) {
  const duration = useLiveDuration(startedAt, status, completedAt);
  const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK", "FAILED_WORKER_CRASH"];
  const isLive = !TERMINAL.includes(status);
  const isRunnable = ["ACTIVE", "PENDING_ASYNC", "RUNNING"].includes(status);
  const isFailed = status.startsWith("FAILED");
  const isCancellable = !TERMINAL.includes(status);

  const currentIdx = currentStep ? 1 : 0; // simplified; parent can pass index if needed

  function relativeTime(ts: string | null) {
    if (!ts) return "—";
    const diff = Date.now() - new Date(ts).getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    return `${Math.floor(m / 60)}h ago`;
  }

  return (
    <div className="flex items-center justify-between px-5 py-3 border-b border-[#1E1E22] bg-[#111113] flex-shrink-0">
      {/* Left: identity + status */}
      <div className="flex items-center gap-4 min-w-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-[#E4E4E7] truncate">{workflowType ?? "—"}</span>
            <span className="font-mono text-xs text-zinc-600">#{id.slice(0, 8)}</span>
            <WorkflowStatusBadge status={status} />
            <LiveIndicator connected={connected} />
          </div>
          <div className="flex items-center gap-3 mt-1">
            {currentStep && (
              <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">
                STEP {currentStep}
              </span>
            )}
            <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">
              STARTED {relativeTime(startedAt)}
            </span>
            <span className={`font-mono text-[10px] uppercase tracking-widest tabular-nums ${isLive ? "text-amber-500 animate-tick" : "text-zinc-600"}`}>
              {duration}
            </span>
          </div>
        </div>
      </div>

      {/* Right: action bar */}
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <RoleGate permission="debugWorkflow">
          <ConsoleButton href={`/workflows/${id}/debug`}>
            <Bug className="h-3 w-3" /> Debug
          </ConsoleButton>
        </RoleGate>
        <ConsoleButton onClick={onToggleDAG} active={showDAG}>
          <Network className="h-3 w-3" /> DAG
        </ConsoleButton>
        <ConsoleButton onClick={onRefresh}>
          <RefreshCw className="h-3 w-3" />
        </ConsoleButton>
        <span className="text-zinc-700 text-sm mx-1">|</span>
        <RoleGate permission="resumeWorkflow">
          {isRunnable && (
            <ConsoleButton variant="amber" onClick={onAdvance}>
              <Play className="h-3 w-3" /> Advance
            </ConsoleButton>
          )}
        </RoleGate>
        <RoleGate permission="retryWorkflow">
          {isFailed && (
            <ConsoleButton onClick={onRewind}>
              <RotateCcw className="h-3 w-3" /> Rewind
            </ConsoleButton>
          )}
        </RoleGate>
        <RoleGate permission="cancelWorkflow">
          {isCancellable && (
            <ConsoleButton variant="red" onClick={onCancel}>
              <X className="h-3 w-3" /> Cancel
            </ConsoleButton>
          )}
        </RoleGate>
      </div>
    </div>
  );
}
