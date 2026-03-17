"use client";

import { useState, useMemo, useEffect } from "react";
import { useApprovals } from "@/lib/hooks/useApprovals";
import { useResumeWorkflow } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { HitlForm } from "@/components/workflows/HitlForm";
import { formatRelativeTime, truncateId } from "@/lib/utils";
import { CheckSquare, RefreshCw, X } from "lucide-react";
import type { WorkflowExecution } from "@/types";

const SEARCH_INPUT = "bg-[#0A0A0B] border border-[#1E1E22] font-mono text-xs text-zinc-300 placeholder-zinc-600 px-3 py-1.5 w-64 focus:outline-none focus:border-zinc-500 transition-colors rounded-none";

export default function ApprovalsPage() {
  const { data, isLoading, refetch } = useApprovals();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const resumeWorkflow = useResumeWorkflow();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const allApprovals = data?.workflows ?? [];

  const approvals = useMemo(() => {
    if (!debouncedSearch) return allApprovals;
    const q = debouncedSearch.toLowerCase();
    return allApprovals.filter(
      (wf) =>
        wf.workflow_type.toLowerCase().includes(q) ||
        wf.workflow_id.toLowerCase().includes(q)
    );
  }, [allApprovals, debouncedSearch]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">APPROVAL QUEUE</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">{approvals.length} workflows awaiting input</p>
        </div>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
        >
          <RefreshCw className="h-3 w-3" /> Refresh
        </button>
      </div>

      {/* Search */}
      <div className="relative inline-block">
        <input
          type="text"
          placeholder="Search by type or ID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={SEARCH_INPUT}
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

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => <div key={i} className="h-20 animate-pulse bg-[#111113] border border-[#1E1E22] rounded-none" />)}
        </div>
      ) : approvals.length === 0 ? (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-12 text-center">
          <CheckSquare className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
          <p className="font-mono text-xs text-zinc-600">NO PENDING APPROVALS</p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((wf) => (
            <ApprovalCard
              key={wf.workflow_id}
              workflow={wf}
              isSelected={selectedId === wf.workflow_id}
              onSelect={() => setSelectedId(selectedId === wf.workflow_id ? null : wf.workflow_id)}
              onSubmit={(data) => {
                resumeWorkflow.mutate({ id: wf.workflow_id, userInput: data });
                setSelectedId(null);
              }}
              isSubmitting={resumeWorkflow.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({
  workflow,
  isSelected,
  onSelect,
  onSubmit,
  isSubmitting,
}: {
  workflow: WorkflowExecution;
  isSelected: boolean;
  onSelect: () => void;
  onSubmit: (data: Record<string, unknown>) => void;
  isSubmitting: boolean;
}) {
  return (
    <div className={`bg-[#111113] border rounded-none ${isSelected ? "border-amber-500/40" : "border-[#1E1E22]"}`}>
      <button
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-[#1A1A1E] transition-colors"
        onClick={onSelect}
      >
        <div className="text-left">
          <div className="flex items-center gap-2">
            <span className="inline-block w-2 h-2 bg-yellow-400 rounded-full animate-pulse flex-shrink-0" />
            <span className="font-mono text-sm text-[#E4E4E7]">{workflow.workflow_type}</span>
          </div>
          <div className="flex items-center gap-3 mt-1">
            <span className="font-mono text-[10px] text-zinc-600">#{truncateId(workflow.workflow_id, 8)}</span>
            {workflow.current_step && (
              <span className="font-mono text-[10px] text-zinc-600">→ {workflow.current_step}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="font-mono text-[10px] text-zinc-600">{formatRelativeTime(workflow.started_at)}</span>
          <WorkflowStatusBadge status={workflow.status} />
        </div>
      </button>

      {isSelected && (
        <div className="border-t border-amber-500/20 bg-amber-500/5 px-4 py-4">
          <HitlForm
            workflowId={workflow.workflow_id}
            inputSchema={(workflow.state as Record<string, unknown>)?._input_schema as Record<string, unknown> | undefined}
            stepName={workflow.current_step ?? ""}
            onSubmit={onSubmit}
            isSubmitting={isSubmitting}
          />
        </div>
      )}
    </div>
  );
}
