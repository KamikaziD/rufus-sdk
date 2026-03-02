import { auth } from "@/lib/auth";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { truncateId, formatRelativeTime } from "@/lib/utils";
import * as api from "@/lib/api";
import type { WorkflowStatus } from "@/types";

export async function RecentWorkflows() {
  const session = await auth();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  let workflows: { workflow_id: string; workflow_type: string; status: WorkflowStatus; started_at: string }[] = [];

  if (token) {
    try {
      const res = await api.listWorkflows(token, { limit: 10 });
      workflows = res.workflows ?? [];
    } catch {}
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">Recent Executions</CardTitle>
        <Link href="/workflows" className="text-xs text-muted-foreground hover:text-foreground">
          View all →
        </Link>
      </CardHeader>
      <CardContent>
        {workflows.length === 0 ? (
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
