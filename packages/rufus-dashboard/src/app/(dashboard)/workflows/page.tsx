"use client";

import { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import { useWorkflowList, useCancelWorkflow } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { RoleGate } from "@/components/shared/RoleGate";
import { truncateId, formatRelativeTime, formatDuration } from "@/lib/utils";
import { Plus, RefreshCw, X, ArrowUpDown } from "lucide-react";

const STATUS_OPTIONS = ["ALL", "ACTIVE", "RUNNING", "PENDING_ASYNC", "COMPLETED", "FAILED", "WAITING_HUMAN", "CANCELLED"];
const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK", "FAILED_WORKER_CRASH"];

type SortCol = "status" | "started" | "duration";
type SortDir = "asc" | "desc";

const FILTER_INPUT = "bg-[#0A0A0B] border border-[#1E1E22] font-mono text-xs text-zinc-300 placeholder-zinc-600 px-3 py-1.5 w-64 focus:outline-none focus:border-zinc-500 transition-colors rounded-none";

export default function WorkflowsPage() {
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sortCol, setSortCol] = useState<SortCol | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, refetch } = useWorkflowList({
    status: statusFilter === "ALL" ? undefined : statusFilter,
    limit: 20,
    page,
  });

  const cancelWorkflow = useCancelWorkflow();
  const allWorkflows = data?.workflows ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / 20);

  const workflows = useMemo(() => {
    let rows = allWorkflows;
    if (debouncedSearch) {
      const q = debouncedSearch.toLowerCase();
      rows = rows.filter(
        (wf) =>
          wf.workflow_id.toLowerCase().includes(q) ||
          wf.workflow_type.toLowerCase().includes(q)
      );
    }
    if (!sortCol) return rows;
    return [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortCol === "status")   cmp = (a.status ?? "").localeCompare(b.status ?? "");
      else if (sortCol === "started")  cmp = (a.started_at ?? "").localeCompare(b.started_at ?? "");
      else if (sortCol === "duration") {
        const durA = a.completed_at ? new Date(a.completed_at).getTime() - new Date(a.started_at).getTime() : Date.now() - new Date(a.started_at).getTime();
        const durB = b.completed_at ? new Date(b.completed_at).getTime() - new Date(b.started_at).getTime() : Date.now() - new Date(b.started_at).getTime();
        cmp = durA - durB;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [allWorkflows, debouncedSearch, sortCol, sortDir]);

  function toggleSort(col: SortCol) {
    if (sortCol === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("asc"); }
  }

  function ColHeader({ col, label }: { col: SortCol; label: string }) {
    const active = sortCol === col;
    return (
      <button
        onClick={() => toggleSort(col)}
        className={`flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest hover:text-zinc-300 transition-colors ${active ? "text-amber-400" : "text-zinc-600"}`}
      >
        {label}
        <ArrowUpDown className="h-2.5 w-2.5 opacity-50" />
        {active && <span className="text-[9px]">{sortDir === "asc" ? "↑" : "↓"}</span>}
      </button>
    );
  }

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

      {/* Search + filter row */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative">
          <input
            type="text"
            placeholder="Search by ID or type…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={FILTER_INPUT}
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-400"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Status filter chips */}
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
                  {["ID", "TYPE"].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                  <th className="text-left px-4 py-2.5"><ColHeader col="status" label="STATUS" /></th>
                  <th className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest whitespace-nowrap">
                    CURRENT STEP
                  </th>
                  <th className="text-left px-4 py-2.5"><ColHeader col="started" label="STARTED" /></th>
                  <th className="text-left px-4 py-2.5"><ColHeader col="duration" label="DURATION" /></th>
                  <th className="text-left px-4 py-2.5" />
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
