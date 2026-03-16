"use client";

import { useState } from "react";
import Link from "next/link";
import { useWorkflowList, useWorkflowTypes, useCancelWorkflow } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { RoleGate } from "@/components/shared/RoleGate";
import { truncateId, formatRelativeTime, formatDuration } from "@/lib/utils";
import { Plus, RefreshCw, X } from "lucide-react";

const STATUS_OPTIONS = ["ALL", "ACTIVE", "RUNNING", "PENDING_ASYNC", "COMPLETED", "FAILED", "WAITING_HUMAN", "CANCELLED"];
const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK", "FAILED_WORKER_CRASH"];

function useLiveTimer(startedAt: string, status: string) {
  const [tick, setTick] = useState(0);
  if (TERMINAL.includes(status)) {
    return formatDuration(startedAt, null);
  }
  // We just use formatDuration which will compute from startedAt to now
  return formatDuration(startedAt, null);
}

export default function WorkflowsPage() {
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [page, setPage] = useState(1);

  const { data, isLoading, refetch } = useWorkflowList({
    status: statusFilter === "ALL" ? undefined : statusFilter,
    limit: 20,
    page,
  });

  const cancelWorkflow = useCancelWorkflow();
  const workflows = data?.workflows ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / 20);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">WORKFLOWS</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">{total} executions total</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
          <RoleGate permission="startWorkflow">
            <Link
              href="/workflows/new"
              className="inline-flex items-center gap-1.5 font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-2 py-1 rounded-none transition-colors"
            >
              <Plus className="h-3 w-3" /> New Workflow
            </Link>
          </RoleGate>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex gap-1.5 flex-wrap">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1); }}
            className={`font-mono text-[10px] border px-2 py-1 rounded-none transition-colors ${
              statusFilter === s
                ? "bg-amber-500/10 border-amber-500/40 text-amber-400"
                : "border-zinc-700 text-zinc-500 hover:text-zinc-300 hover:border-zinc-500"
            }`}
          >
            {s === "ALL" ? "ALL" : s.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-10 animate-pulse bg-zinc-800/50 rounded-none" />
            ))}
          </div>
        ) : workflows.length === 0 ? (
          <div className="py-12 text-center font-mono text-xs text-zinc-600">NO WORKFLOWS FOUND</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                  {["ID", "TYPE", "STATUS", "CURRENT STEP", "STARTED", "DURATION", ""].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {workflows.map((wf) => {
                  const isActive = !TERMINAL.includes(wf.status);
                  return (
                    <tr key={wf.workflow_id} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                      <td className="px-4 py-3">
                        <Link
                          href={`/workflows/${wf.workflow_id}`}
                          className="font-mono text-xs text-amber-400 hover:text-amber-300"
                        >
                          #{truncateId(wf.workflow_id, 8)}
                        </Link>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-300 max-w-[180px] truncate">
                        {wf.workflow_type}
                      </td>
                      <td className="px-4 py-3">
                        <WorkflowStatusBadge status={wf.status} />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-500">{wf.current_step ?? "—"}</td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-500">{formatRelativeTime(wf.started_at)}</td>
                      <td className={`px-4 py-3 font-mono text-xs tabular-nums ${isActive ? "text-amber-500" : "text-zinc-500"}`}>
                        {formatDuration(wf.started_at, wf.completed_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center gap-1 justify-end">
                          <Link
                            href={`/workflows/${wf.workflow_id}`}
                            className="font-mono text-[10px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-2 py-0.5 rounded-none transition-colors"
                          >
                            VIEW
                          </Link>
                          <RoleGate permission="cancelWorkflow">
                            {!TERMINAL.includes(wf.status) && (
                              <button
                                onClick={() => cancelWorkflow.mutate(wf.workflow_id)}
                                className="font-mono text-[10px] border border-red-500/30 text-red-500 hover:bg-red-500/10 px-2 py-0.5 rounded-none transition-colors"
                                aria-label="Cancel"
                              >
                                [✕]
                              </button>
                            )}
                          </RoleGate>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
            className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-3 py-1 rounded-none disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ← Prev
          </button>
          <span className="font-mono text-xs text-zinc-600">{page} / {pageCount}</span>
          <button
            disabled={page === pageCount}
            onClick={() => setPage((p) => p + 1)}
            className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-3 py-1 rounded-none disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
