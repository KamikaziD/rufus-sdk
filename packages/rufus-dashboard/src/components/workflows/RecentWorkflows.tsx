"use client";

import Link from "next/link";
import { useWorkflowList } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { truncateId, formatRelativeTime } from "@/lib/utils";

export function RecentWorkflows() {
  const { data, isLoading } = useWorkflowList({ limit: 10 });
  const workflows = data?.workflows ?? [];

  return (
    <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1E1E22]">
        <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">RECENT EXECUTIONS</span>
        <Link href="/workflows" className="font-mono text-[10px] text-zinc-600 hover:text-zinc-300 transition-colors">
          View all →
        </Link>
      </div>
      <div>
        {isLoading ? (
          <div className="p-4 space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-10 animate-pulse bg-zinc-800/50 rounded-none" />
            ))}
          </div>
        ) : workflows.length === 0 ? (
          <p className="font-mono text-xs text-zinc-600 px-4 py-6 text-center">No workflows yet</p>
        ) : (
          workflows.map((wf) => (
            <Link
              key={wf.workflow_id}
              href={`/workflows/${wf.workflow_id}`}
              className="flex items-center justify-between px-4 py-2.5 border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors"
            >
              <div>
                <p className="font-mono text-xs text-amber-400 hover:text-amber-300">
                  #{truncateId(wf.workflow_id, 8)}
                </p>
                <p className="font-mono text-[11px] text-zinc-500 truncate max-w-[160px]">{wf.workflow_type}</p>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <span className="font-mono text-[10px] text-zinc-600">{formatRelativeTime(wf.started_at)}</span>
                <WorkflowStatusBadge status={wf.status} />
              </div>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
