"use client";

import type { WorkflowStatus } from "@/types";

interface StepConfig {
  name: string;
  type: string;
  description?: string;
}

interface AuditEntry {
  timestamp: string;
  event: string;
  step?: string;
  details?: Record<string, unknown>;
}

interface StepTimelineProps {
  stepsConfig: StepConfig[];
  currentStep: string | null;
  status: WorkflowStatus;
  focusedStep?: string | null;
  onStepClick?: (name: string) => void;
  auditLog?: AuditEntry[];
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

function getStepDuration(stepName: string, auditLog?: AuditEntry[]): string | null {
  if (!auditLog?.length) return null;
  const entries = auditLog.filter((e) => e.step === stepName);
  if (entries.length < 2) return null;
  const first = new Date(entries[0].timestamp).getTime();
  const last  = new Date(entries[entries.length - 1].timestamp).getTime();
  const ms = last - first;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const TYPE_BADGE: Record<string, string> = {
  STANDARD:        "border-zinc-700 text-zinc-500",
  DECISION:        "border-purple-500/40 text-purple-400",
  PARALLEL:        "border-blue-500/40 text-blue-400",
  HTTP:            "border-orange-500/40 text-orange-400",
  ASYNC:           "border-cyan-500/40 text-cyan-400",
  HUMAN_IN_LOOP:   "border-yellow-500/40 text-yellow-400",
  LOOP:            "border-emerald-500/40 text-emerald-400",
  FIRE_AND_FORGET: "border-pink-500/40 text-pink-400",
  CRON_SCHEDULE:   "border-indigo-500/40 text-indigo-400",
  AI_INFERENCE:    "border-violet-500/40 text-violet-400",
  WASM:            "border-teal-500/40 text-teal-400",
};

const DOT_COLOR: Record<StepState, string> = {
  completed: "bg-emerald-400 border-emerald-400",
  current:   "bg-amber-400 border-amber-400 animate-pulse-amber",
  failed:    "bg-red-400 border-red-400",
  pending:   "bg-transparent border-zinc-600",
};

const RAIL_COLOR: Record<StepState, string> = {
  completed: "bg-emerald-500/40",
  current:   "bg-amber-500/40",
  failed:    "bg-red-500/40",
  pending:   "bg-[#3A3A42]",
};

export function StepTimeline({ stepsConfig, currentStep, status, focusedStep, onStepClick, auditLog }: StepTimelineProps) {
  if (!stepsConfig.length) {
    return <p className="font-mono text-sm text-zinc-600 px-4 py-6">No step configuration available.</p>;
  }

  const isAsyncCurrent = status === "PENDING_ASYNC";

  return (
    <div className="py-2">
      {stepsConfig.map((step, i) => {
        const state = getStepState(step, currentStep, stepsConfig, status);
        const isFocused = focusedStep === step.name;
        const duration = getStepDuration(step.name, auditLog);

        return (
          <div
            key={step.name}
            className={`flex gap-3 cursor-pointer transition-colors ${isFocused ? "bg-zinc-800/60 border-l-2 border-amber-500" : "border-l-2 border-transparent hover:bg-[#1A1A1E]"}`}
            onClick={() => onStepClick?.(step.name)}
          >
            {/* Left rail */}
            <div className="flex flex-col items-center ml-3 flex-shrink-0">
              <div className="mt-4 flex items-center gap-2">
                <span className="font-mono text-[10px] text-zinc-600 w-5 text-right">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className={`w-3 h-3 rounded-full border-2 flex-shrink-0 ${DOT_COLOR[state]}`} />
              </div>
              {i < stepsConfig.length - 1 && (
                <div className="w-px flex-1 my-1 ml-7" style={{ position: "relative" }}>
                  <div
                    className={`w-px h-full ${RAIL_COLOR[state]} ${state === "current" && isAsyncCurrent ? "stroke-dasharray-2" : ""}`}
                    style={{
                      minHeight: 20,
                      background: state === "current" && isAsyncCurrent
                        ? "repeating-linear-gradient(to bottom, #F97316 0px, #F97316 4px, transparent 4px, transparent 8px)"
                        : undefined,
                    }}
                  />
                </div>
              )}
            </div>

            {/* Step info */}
            <div className="flex-1 py-3 pr-4">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`font-mono text-sm ${state === "pending" ? "text-zinc-600" : state === "current" ? "text-amber-400" : state === "failed" ? "text-red-400" : "text-zinc-300"}`}>
                  {step.name}
                </span>
                <span className={`font-mono text-[9px] border px-1 py-0.5 rounded-none ${TYPE_BADGE[step.type] ?? "border-zinc-700 text-zinc-600"}`}>
                  {step.type}
                </span>
                {duration && (
                  <span className="font-mono text-[10px] text-zinc-600">{duration}</span>
                )}
              </div>
              {step.description && (
                <p className="font-mono text-[11px] text-zinc-600 mt-0.5">{step.description}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
