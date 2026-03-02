"use client";

import { CheckCircle2, Circle, XCircle, Clock, User, Loader2 } from "lucide-react";
import type { WorkflowStatus } from "@/types";

interface StepConfig {
  name: string;
  type: string;
  description?: string;
}

interface StepTimelineProps {
  stepsConfig: StepConfig[];
  currentStep: string | null;
  status: WorkflowStatus;
}

type StepState = "completed" | "current" | "pending" | "failed";

function getStepState(
  step: StepConfig,
  currentStep: string | null,
  allSteps: StepConfig[],
  workflowStatus: WorkflowStatus
): StepState {
  const currentIdx = allSteps.findIndex((s) => s.name === currentStep);
  const thisIdx = allSteps.findIndex((s) => s.name === step.name);

  if (workflowStatus === "COMPLETED") return "completed";
  if (workflowStatus.startsWith("FAILED") && thisIdx === currentIdx) return "failed";
  if (thisIdx < currentIdx) return "completed";
  if (thisIdx === currentIdx) return "current";
  return "pending";
}

const STEP_ICON = {
  completed: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  current:   <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />,
  failed:    <XCircle className="h-5 w-5 text-red-500" />,
  pending:   <Circle className="h-5 w-5 text-muted-foreground" />,
};

const TYPE_BADGE: Record<string, string> = {
  STANDARD:       "bg-slate-100 text-slate-700",
  DECISION:       "bg-purple-100 text-purple-700",
  PARALLEL:       "bg-blue-100 text-blue-700",
  HTTP:           "bg-orange-100 text-orange-700",
  ASYNC:          "bg-cyan-100 text-cyan-700",
  HUMAN_IN_LOOP:  "bg-yellow-100 text-yellow-700",
  LOOP:           "bg-green-100 text-green-700",
  FIRE_AND_FORGET:"bg-pink-100 text-pink-700",
  CRON_SCHEDULE:  "bg-indigo-100 text-indigo-700",
};

export function StepTimeline({ stepsConfig, currentStep, status }: StepTimelineProps) {
  if (!stepsConfig.length) {
    return <p className="text-sm text-muted-foreground">No step configuration available.</p>;
  }

  return (
    <div className="space-y-1">
      {stepsConfig.map((step, i) => {
        const state = getStepState(step, currentStep, stepsConfig, status);
        return (
          <div key={step.name} className="flex gap-4">
            {/* Left: icon + connector */}
            <div className="flex flex-col items-center">
              <div className="mt-1">{STEP_ICON[state]}</div>
              {i < stepsConfig.length - 1 && (
                <div className={`w-0.5 flex-1 my-1 ${state === "completed" ? "bg-green-300" : "bg-border"}`} />
              )}
            </div>

            {/* Right: step info */}
            <div className={`pb-4 flex-1 ${i === stepsConfig.length - 1 ? "" : ""}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`font-medium text-sm ${state === "pending" ? "text-muted-foreground" : ""}`}>
                  {step.name}
                </span>
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${TYPE_BADGE[step.type] ?? "bg-muted text-muted-foreground"}`}>
                  {step.type}
                </span>
                {step.type === "HUMAN_IN_LOOP" && <User className="h-3 w-3 text-yellow-500" />}
              </div>
              {step.description && (
                <p className="text-xs text-muted-foreground mt-0.5">{step.description}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
