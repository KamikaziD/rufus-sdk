"use client";

import { useState } from "react";
import { useWorkflow, useNextStep, useRewindWorkflow, useResumeWorkflow } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { HitlForm } from "@/components/workflows/HitlForm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { truncateId } from "@/lib/utils";
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import Link from "next/link";

export default function DebugStepperPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const { data: workflow, isLoading, refetch } = useWorkflow(id);
  const nextStep = useNextStep();
  const rewindWorkflow = useRewindWorkflow();
  const resumeWorkflow = useResumeWorkflow();
  const [prevState, setPrevState] = useState<Record<string, unknown> | null>(null);

  if (isLoading) return <div className="animate-pulse h-32 bg-muted rounded-xl" />;
  if (!workflow) return <div className="text-muted-foreground">Workflow not found</div>;

  const currentState = workflow.state ?? {};
  const stepsConfig = workflow.steps_config ?? [];
  const currentIdx = stepsConfig.findIndex((s) => s.name === workflow.current_step);
  const stepCount = stepsConfig.length;

  async function handleNext(userInput: Record<string, unknown> = {}) {
    setPrevState(currentState);
    if (isWaitingHuman) {
      await resumeWorkflow.mutateAsync({ id, userInput });
    } else {
      await nextStep.mutateAsync({ id, userInput });
    }
    refetch();
  }

  async function handleRewind() {
    setPrevState(null);
    await rewindWorkflow.mutateAsync(id);
    refetch();
  }

  const isWaitingHuman = workflow.status === "WAITING_HUMAN";
  const canAdvance     = ["RUNNING", "PENDING", "ACTIVE"].includes(workflow.status) && !isWaitingHuman;
  const canRewind      = currentIdx > 0;

  // Compute state diff
  const stateDiff: { key: string; before: unknown; after: unknown }[] = prevState
    ? Object.keys({ ...prevState, ...currentState }).map((key) => ({
        key,
        before: prevState[key],
        after:  currentState[key],
      })).filter((d) => JSON.stringify(d.before) !== JSON.stringify(d.after))
    : [];

  return (
    <div className="max-w-3xl space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/workflows/${id}`}><ChevronLeft className="h-4 w-4" /> Back</Link>
        </Button>
        <div>
          <h1 className="text-xl font-bold">Debug Stepper</h1>
          <p className="text-muted-foreground text-sm font-mono">{truncateId(id, 16)}</p>
        </div>
        <WorkflowStatusBadge status={workflow.status} />
      </div>

      {/* Step counter */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Current Step</p>
              <p className="text-lg font-semibold">{workflow.current_step ?? "—"}</p>
              <p className="text-sm text-muted-foreground">
                Step {currentIdx === -1 ? "?" : currentIdx + 1} of {stepCount}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={!canRewind || rewindWorkflow.isPending}
                onClick={handleRewind}
              >
                <RotateCcw className="h-4 w-4" />
                Rewind
              </Button>
              <Button
                disabled={!canAdvance || nextStep.isPending}
                onClick={() => handleNext()}
              >
                <ChevronRight className="h-4 w-4" />
                Next Step
              </Button>
            </div>
          </div>

          {/* Step breadcrumb */}
          <div className="flex gap-1 flex-wrap">
            {stepsConfig.map((step, i) => (
              <span
                key={step.name}
                className={`text-xs px-2 py-0.5 rounded ${
                  i < currentIdx ? "bg-green-100 text-green-800" :
                  i === currentIdx ? "bg-primary text-primary-foreground" :
                  "bg-muted text-muted-foreground"
                }`}
              >
                {step.name}
              </span>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* HITL form (if waiting) */}
      {isWaitingHuman && (
        <HitlForm
          workflowId={id}
          inputSchema={workflow.current_step_info?.input_schema}
          stepName={workflow.current_step ?? ""}
          onSubmit={(data) => handleNext(data)}
          isSubmitting={nextStep.isPending || resumeWorkflow.isPending}
        />
      )}

      {/* State diff */}
      {stateDiff.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">State Changes</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2 font-mono text-xs">
              {stateDiff.map((d) => (
                <div key={d.key} className="grid grid-cols-3 gap-2 border-b pb-2">
                  <span className="font-semibold">{d.key}</span>
                  <span className="text-red-600 truncate">{JSON.stringify(d.before)}</span>
                  <span className="text-green-600 truncate">{JSON.stringify(d.after)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Current state */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Current State</CardTitle></CardHeader>
        <CardContent>
          <pre className="text-xs font-mono overflow-auto max-h-60 p-3 bg-muted rounded">
            {JSON.stringify(currentState, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
