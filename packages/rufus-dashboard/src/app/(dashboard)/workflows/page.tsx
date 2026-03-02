"use client";

import { useState } from "react";
import Link from "next/link";
import { useWorkflowList, useWorkflowTypes, useCancelWorkflow } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { RoleGate } from "@/components/shared/RoleGate";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { truncateId, formatRelativeTime, formatDuration } from "@/lib/utils";
import { Plus, RefreshCw, XCircle } from "lucide-react";

const STATUS_OPTIONS = ["ALL", "RUNNING", "COMPLETED", "FAILED", "WAITING_HUMAN", "CANCELLED"];

export default function WorkflowsPage() {
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [page, setPage] = useState(1);

  const { data, isLoading, refetch } = useWorkflowList({
    status: statusFilter === "ALL" ? undefined : statusFilter,
    limit: 20,
    page,
  });

  const { data: typesData } = useWorkflowTypes();
  const cancelWorkflow = useCancelWorkflow();

  const workflows = data?.workflows ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / 20);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Workflows</h1>
          <p className="text-muted-foreground">{total} executions total</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <RoleGate permission="startWorkflow">
            <Button size="sm" asChild>
              <Link href="/workflows/new">
                <Plus className="h-3.5 w-3.5" />
                New Workflow
              </Link>
            </Button>
          </RoleGate>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1); }}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              statusFilter === s
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border text-muted-foreground hover:border-foreground"
            }`}
          >
            {s === "ALL" ? "All" : s.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-12 animate-pulse bg-muted rounded" />
              ))}
            </div>
          ) : workflows.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">No workflows found</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Type</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Status</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Current Step</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Started</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Duration</th>
                    <th className="text-right px-4 py-3 font-medium text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {workflows.map((wf) => (
                    <tr key={wf.workflow_id} className="border-b hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3">
                        <Link
                          href={`/workflows/${wf.workflow_id}`}
                          className="font-mono text-xs text-primary hover:underline"
                        >
                          {truncateId(wf.workflow_id)}
                        </Link>
                      </td>
                      <td className="px-4 py-3 font-medium">{wf.workflow_type}</td>
                      <td className="px-4 py-3">
                        <WorkflowStatusBadge status={wf.status} />
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{wf.current_step ?? "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground">{formatRelativeTime(wf.started_at)}</td>
                      <td className="px-4 py-3 text-muted-foreground">{formatDuration(wf.started_at, wf.completed_at)}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center gap-1 justify-end">
                          <Button variant="ghost" size="sm" asChild>
                            <Link href={`/workflows/${wf.workflow_id}`}>View</Link>
                          </Button>
                          <RoleGate permission="cancelWorkflow">
                            {["RUNNING", "PENDING", "WAITING_HUMAN"].includes(wf.status) && (
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => cancelWorkflow.mutate(wf.workflow_id)}
                                aria-label="Cancel"
                              >
                                <XCircle className="h-3.5 w-3.5 text-destructive" />
                              </Button>
                            )}
                          </RoleGate>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {pageCount}</span>
          <Button variant="outline" size="sm" disabled={page === pageCount} onClick={() => setPage(p => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
