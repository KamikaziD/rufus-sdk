"use client";

import { useState } from "react";
import { useWorkflow, useResumeWorkflow, useCancelWorkflow, useNextStep, useRewindWorkflow } from "@/lib/hooks/useWorkflow";
import { useWorkflowStream } from "@/lib/hooks/useWorkflowStream";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { LiveIndicator } from "@/components/shared/LiveIndicator";
import { RoleGate } from "@/components/shared/RoleGate";
import { StepTimeline } from "@/components/workflows/StepTimeline";
import { StatePanel } from "@/components/workflows/StatePanel";
import { HitlForm } from "@/components/workflows/HitlForm";
import { WorkflowDAG } from "@/components/workflows/WorkflowDAG";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { truncateId, formatTime } from "@/lib/utils";
import { RefreshCw, RotateCcw, XCircle, Bug, ChevronRight } from "lucide-react";
import Link from "next/link";

type Tab = "steps" | "dag" | "state" | "logs" | "input";

export default function WorkflowDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const [activeTab, setActiveTab] = useState<Tab>("steps");

  const { data: workflow, isLoading, refetch } = useWorkflow(id);
  const resumeWorkflow = useResumeWorkflow();
  const cancelWorkflow = useCancelWorkflow();
  const nextStep = useNextStep();
  const rewindWorkflow = useRewindWorkflow();

  const { connected } = useWorkflowStream({
    workflowId: id,
    onMessage: () => refetch(),
  });

  if (isLoading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-8 w-64 bg-muted rounded" />
        <div className="h-32 bg-muted rounded-xl" />
      </div>
    );
  }

  if (!workflow) {
    return <div className="text-muted-foreground">Workflow not found</div>;
  }

  const isWaitingHuman = workflow.status === "WAITING_HUMAN";
  const isRunnable    = ["PENDING", "RUNNING"].includes(workflow.status);
  const isCancellable = ["RUNNING", "PENDING", "WAITING_HUMAN"].includes(workflow.status);
  const tabs: { key: Tab; label: string }[] = [
    { key: "steps",  label: "Steps" },
    { key: "dag",    label: "DAG" },
    { key: "state",  label: "State" },
    { key: "logs",   label: "Logs" },
    ...(isWaitingHuman ? [{ key: "input" as Tab, label: "Required Input" }] : []),
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold font-mono">{truncateId(id, 16)}</h1>
            <WorkflowStatusBadge status={workflow.status} />
            <LiveIndicator connected={connected} />
          </div>
          <p className="text-muted-foreground">
            {workflow.workflow_type ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RoleGate permission="debugWorkflow">
            <Button variant="outline" size="sm" asChild>
              <Link href={`/workflows/${id}/debug`}>
                <Bug className="h-3.5 w-3.5" />
                Debug
              </Link>
            </Button>
          </RoleGate>
          <RoleGate permission="resumeWorkflow">
            {isRunnable && (
              <Button size="sm" onClick={() => nextStep.mutate({ id, userInput: {} })}>
                <ChevronRight className="h-3.5 w-3.5" />
                Next Step
              </Button>
            )}
          </RoleGate>
          <RoleGate permission="retryWorkflow">
            {workflow.status?.startsWith("FAILED") && (
              <Button variant="outline" size="sm" onClick={() => rewindWorkflow.mutate(id)}>
                <RotateCcw className="h-3.5 w-3.5" />
                Rewind
              </Button>
            )}
          </RoleGate>
          <RoleGate permission="cancelWorkflow">
            {isCancellable && (
              <Button variant="outline" size="sm" onClick={() => cancelWorkflow.mutate(id)}>
                <XCircle className="h-3.5 w-3.5 text-destructive" />
                Cancel
              </Button>
            )}
          </RoleGate>
          <Button variant="ghost" size="icon" onClick={() => refetch()} aria-label="Refresh">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div>
        <div className="flex gap-1 border-b mb-4">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                activeTab === t.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
              {t.key === "input" && (
                <span className="ml-1.5 h-1.5 w-1.5 rounded-full bg-yellow-500 inline-block" />
              )}
            </button>
          ))}
        </div>

        {activeTab === "steps" && (
          <StepTimeline
            stepsConfig={workflow.steps_config ?? []}
            currentStep={workflow.current_step}
            status={workflow.status}
          />
        )}
        {activeTab === "dag" && (
          <WorkflowDAG
            stepsConfig={workflow.steps_config ?? []}
            currentStep={workflow.current_step}
            status={workflow.status}
          />
        )}
        {activeTab === "state" && (
          <StatePanel state={workflow.state ?? {}} />
        )}
        {activeTab === "logs" && (
          <AuditLogTab entries={workflow.audit_log ?? []} />
        )}
        {activeTab === "input" && isWaitingHuman && (
          <HitlForm
            workflowId={id}
            inputSchema={workflow.current_step_info?.input_schema}
            stepName={workflow.current_step ?? ""}
            onSubmit={(data) => resumeWorkflow.mutate({ id, userInput: data })}
            isSubmitting={resumeWorkflow.isPending}
          />
        )}
      </div>
    </div>
  );
}

function AuditLogTab({ entries }: { entries: { timestamp: string; event: string; step?: string; details?: Record<string, unknown> }[] }) {
  if (!entries.length) {
    return <p className="text-muted-foreground text-sm">No log entries yet.</p>;
  }
  return (
    <div className="space-y-2">
      {entries.map((entry, i) => (
        <div key={i} className="flex gap-4 text-sm">
          <span className="text-muted-foreground font-mono text-xs w-36 flex-shrink-0">
            {formatTime(entry.timestamp)}
          </span>
          <span className="font-medium">{entry.event}</span>
          {entry.step && (
            <span className="text-muted-foreground">→ {entry.step}</span>
          )}
        </div>
      ))}
    </div>
  );
}
