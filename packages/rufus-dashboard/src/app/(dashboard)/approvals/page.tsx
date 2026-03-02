"use client";

import { useState } from "react";
import { useApprovals } from "@/lib/hooks/useApprovals";
import { useResumeWorkflow } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { HitlForm } from "@/components/workflows/HitlForm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatRelativeTime, truncateId } from "@/lib/utils";
import { CheckSquare, RefreshCw } from "lucide-react";
import type { WorkflowExecution } from "@/types";

export default function ApprovalsPage() {
  const { data, isLoading, refetch } = useApprovals();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const resumeWorkflow = useResumeWorkflow();

  const approvals = data?.workflows ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Approval Queue</h1>
          <p className="text-muted-foreground">{approvals.length} workflows awaiting input</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => <div key={i} className="h-20 animate-pulse bg-muted rounded-xl" />)}
        </div>
      ) : approvals.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <CheckSquare className="h-8 w-8 mx-auto mb-3 opacity-30" />
            No pending approvals
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
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
    <Card className={isSelected ? "border-primary" : ""}>
      <CardContent className="pt-5">
        <button
          className="w-full flex items-center justify-between"
          onClick={onSelect}
        >
          <div className="text-left">
            <p className="font-medium">{workflow.workflow_type}</p>
            <div className="flex items-center gap-3 mt-1">
              <span className="font-mono text-xs text-muted-foreground">
                {truncateId(workflow.workflow_id)}
              </span>
              <span className="text-xs text-muted-foreground">
                {workflow.current_step}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">
              {formatRelativeTime(workflow.started_at)}
            </span>
            <WorkflowStatusBadge status={workflow.status} />
          </div>
        </button>

        {isSelected && (
          <div className="mt-4 pt-4 border-t">
            <HitlForm
              workflowId={workflow.workflow_id}
              inputSchema={(workflow.state as Record<string, unknown>)?._input_schema as Record<string, unknown> | undefined}
              stepName={workflow.current_step ?? ""}
              onSubmit={onSubmit}
              isSubmitting={isSubmitting}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
