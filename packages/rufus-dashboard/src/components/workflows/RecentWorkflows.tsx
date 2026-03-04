"use client";

import Link from "next/link";
import { useWorkflowList } from "@/lib/hooks/useWorkflow";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { truncateId, formatRelativeTime } from "@/lib/utils";

export function RecentWorkflows() {
  const { data, isLoading } = useWorkflowList({ limit: 10 });
  const workflows = data?.workflows ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">Recent Executions</CardTitle>
        <Link href="/workflows" className="text-xs text-muted-foreground hover:text-foreground">
          View all →
        </Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 animate-pulse bg-muted rounded" />
            ))}
          </div>
        ) : workflows.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">No workflows yet</p>
        ) : (
          <div className="space-y-2">
            {workflows.map((wf) => (
              <Link
                key={wf.workflow_id}
                href={`/workflows/${wf.workflow_id}`}
                className="flex items-center justify-between py-2 px-1 rounded hover:bg-muted transition-colors"
              >
                <div>
                  <p className="text-sm font-medium">{wf.workflow_type}</p>
                  <p className="text-xs text-muted-foreground font-mono">{truncateId(wf.workflow_id)}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground">{formatRelativeTime(wf.started_at)}</span>
                  <WorkflowStatusBadge status={wf.status} />
                </div>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
