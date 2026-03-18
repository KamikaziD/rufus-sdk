"use client";

import { useState, useEffect } from "react";
import { useWorkflow, useResumeWorkflow, useCancelWorkflow, useNextStep, useRewindWorkflow } from "@/lib/hooks/useWorkflow";
import { useWorkflowStream } from "@/lib/hooks/useWorkflowStream";
import { WorkflowHeader } from "@/components/workflows/WorkflowHeader";
import { StepTimeline } from "@/components/workflows/StepTimeline";
import { ConsoleDetailPanel } from "@/components/workflows/ConsoleDetailPanel";

export default function WorkflowDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const [focusedStep, setFocusedStep] = useState<string | null>(null);
  const [showDAG, setShowDAG] = useState(false);

  const { data: workflow, isLoading, refetch } = useWorkflow(id);
  const resumeWorkflow = useResumeWorkflow();
  const cancelWorkflow = useCancelWorkflow();
  const nextStep = useNextStep();
  const rewindWorkflow = useRewindWorkflow();

  const { connected } = useWorkflowStream({
    workflowId: id,
    onMessage: () => refetch(),
  });

  // Auto-sync focused step to current step
  useEffect(() => {
    if (workflow?.current_step) {
      setFocusedStep(workflow.current_step);
    }
  }, [workflow?.current_step]);

  if (isLoading) {
    return (
      <div className="console-page -m-6 flex flex-col" style={{ height: "calc(100vh - 56px)" }}>
        <div className="flex-1 flex items-center justify-center">
          <span className="font-mono text-xs text-zinc-600 animate-pulse">LOADING…</span>
        </div>
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="console-page -m-6 flex items-center justify-center" style={{ height: "calc(100vh - 56px)" }}>
        <span className="font-mono text-xs text-zinc-600">WORKFLOW NOT FOUND</span>
      </div>
    );
  }

  const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK", "FAILED_WORKER_CRASH"];
  const isWaitingHuman = ["WAITING_HUMAN", "WAITING_CHILD_HUMAN_INPUT"].includes(workflow.status);
  const isFailed = workflow.status.startsWith("FAILED");

  const auditLog = workflow.audit_log ?? [];
  const stepsConfig = workflow.steps_config ?? [];

  // Find last error from audit log
  const errorEntry = auditLog.find((e) => e.event?.toLowerCase().includes("fail") || e.event?.toLowerCase().includes("error"));
  const errorMessage = errorEntry
    ? (errorEntry.details?.error as string) ?? errorEntry.event
    : undefined;

  return (
    <div className="console-page -m-6 flex flex-col" style={{ height: "calc(100vh - 56px)" }}>
      {/* Top strip */}
      <WorkflowHeader
        id={id}
        workflowType={workflow.workflow_type ?? null}
        status={workflow.status}
        currentStep={workflow.current_step ?? null}
        totalSteps={stepsConfig.length}
        startedAt={workflow.started_at ?? null}
        completedAt={workflow.completed_at}
        connected={connected}
        showDAG={showDAG}
        onToggleDAG={() => setShowDAG((v) => !v)}
        onRefresh={() => refetch()}
        onAdvance={() => nextStep.mutate({ id, userInput: {} })}
        onRewind={() => rewindWorkflow.mutate(id)}
        onCancel={() => cancelWorkflow.mutate(id)}
      />

      {/* Two-column body */}
      <div className="flex flex-1 min-h-0">
        {/* Left rail — step timeline */}
        <div
          className="flex-shrink-0 border-r border-[#1E1E22] overflow-y-auto bg-[#0A0A0B]"
          style={{ width: 260 }}
        >
          <StepTimeline
            stepsConfig={stepsConfig}
            currentStep={workflow.current_step ?? null}
            status={workflow.status}
            focusedStep={focusedStep}
            onStepClick={(name) => setFocusedStep(focusedStep === name ? null : name)}
            auditLog={auditLog}
          />
        </div>

        {/* Right panel */}
        <div className="flex-1 min-w-0 bg-[#111113]">
          <ConsoleDetailPanel
            showDAG={showDAG}
            onCloseDAG={() => setShowDAG(false)}
            stepsConfig={stepsConfig}
            currentStep={workflow.current_step ?? null}
            status={workflow.status}
            focusedStep={focusedStep}
            isFailed={isFailed}
            isWaitingHuman={isWaitingHuman}
            workflowId={id}
            workflowType={workflow.workflow_type ?? ""}
            state={workflow.state ?? {}}
            auditLog={auditLog}
            inputSchema={workflow.current_step_info?.input_schema}
            stepName={workflow.current_step ?? ""}
            onHitlSubmit={(data) => resumeWorkflow.mutate({ id, userInput: data })}
            isSubmitting={resumeWorkflow.isPending}
            errorMessage={errorMessage}
          />
        </div>
      </div>
    </div>
  );
}
