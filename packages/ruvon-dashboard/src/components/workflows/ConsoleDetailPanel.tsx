"use client";

import { WorkflowDAG, type StepConfig } from "@/components/workflows/WorkflowDAG";
import { StatePanel } from "@/components/workflows/StatePanel";
import { HitlForm } from "@/components/workflows/HitlForm";
import { FraudReviewPanel } from "@/components/approvals/FraudReviewPanel";
import { LoanReviewPanel } from "@/components/approvals/LoanReviewPanel";
import type { WorkflowStatus, RelayContext } from "@/types";

interface AuditEntry {
  timestamp: string;
  event: string;
  step?: string;
  details?: Record<string, unknown>;
}

interface ConsoleDetailPanelProps {
  showDAG: boolean;
  onCloseDAG: () => void;
  stepsConfig: StepConfig[];
  currentStep: string | null;
  status: WorkflowStatus;
  focusedStep: string | null;
  isFailed: boolean;
  isWaitingHuman: boolean;
  workflowId: string;
  workflowType?: string;
  state: Record<string, unknown>;
  auditLog: AuditEntry[];
  inputSchema?: Record<string, unknown>;
  stepName?: string;
  onHitlSubmit: (data: Record<string, unknown>) => void;
  isSubmitting: boolean;
  errorMessage?: string;
  relayContext?: RelayContext | null;
}

function StateDiff({ before, after }: { before: unknown; after: unknown }) {
  const beforeStr = JSON.stringify(before, null, 2) ?? "{}";
  const afterStr  = JSON.stringify(after,  null, 2) ?? "{}";
  return (
    <div className="grid grid-cols-2 h-full divide-x divide-[#1E1E22]">
      <div className="overflow-auto p-4">
        <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">BEFORE</div>
        <pre className="font-mono text-[11px] text-zinc-400 leading-5 whitespace-pre-wrap">{beforeStr}</pre>
      </div>
      <div className="overflow-auto p-4">
        <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">AFTER</div>
        <pre className="font-mono text-[11px] text-emerald-400 leading-5 whitespace-pre-wrap">{afterStr}</pre>
      </div>
    </div>
  );
}

const EVENT_COLORS: Record<string, string> = {
  WORKFLOW_COMPLETED:    "text-emerald-400",
  WORKFLOW_FAILED:       "text-red-400",
  WORKER_CRASH_DETECTED: "text-red-400",
  WORKFLOW_RUNNING:      "text-sky-400",
  WORKFLOW_CREATED:      "text-zinc-500",
  WORKFLOW_PENDING:      "text-zinc-500",
  WORKFLOW_PAUSED:       "text-amber-400",
  WORKFLOW_CANCELLED:    "text-zinc-500",
  STATUS_CHANGED:        "text-zinc-400",
};

function RelayBanner({ relay }: { relay: RelayContext }) {
  return (
    <div className="mx-4 mt-3 border border-orange-500/30 bg-orange-500/5 rounded px-3 py-2.5">
      <div className="font-mono text-[10px] text-orange-400 font-semibold uppercase tracking-widest mb-2 flex items-center gap-2">
        <span className="inline-block w-1.5 h-1.5 bg-orange-400 rounded-full" />
        Mesh Relay
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-[11px]">
        <div>
          <span className="text-zinc-600">Relay device  </span>
          <span className="text-zinc-300">{relay.relay_device_id}</span>
        </div>
        <div>
          <span className="text-zinc-600">Hops  </span>
          <span className="text-zinc-300">{relay.hop_count}</span>
        </div>
        {relay.relay_source_device_id && relay.relay_source_device_id !== relay.relay_device_id && (
          <div>
            <span className="text-zinc-600">Source  </span>
            <span className="text-zinc-400">{relay.relay_source_device_id}</span>
          </div>
        )}
        {relay.relayed_at && (
          <div>
            <span className="text-zinc-600">Relayed at  </span>
            <span className="text-zinc-400">{new Date(relay.relayed_at).toLocaleString()}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function ConsoleAuditTail({ entries }: { entries: AuditEntry[] }) {
  const recent = [...entries].reverse().slice(0, 50);
  return (
    <div className="border-t border-[#1E1E22]">
      <div className="px-4 py-2 border-b border-[#1E1E22] flex items-center justify-between flex-shrink-0">
        <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Audit Trail</span>
        <span className="font-mono text-[10px] text-zinc-700">{entries.length} events</span>
      </div>
      <div className="max-h-56 overflow-y-auto">
        {recent.length === 0 ? (
          <p className="font-mono text-[11px] text-zinc-600 px-4 py-3">No entries.</p>
        ) : recent.map((entry, i) => {
          const colorClass = EVENT_COLORS[entry.event] ?? "text-zinc-400";
          const oldStatus  = entry.details?.old as string | undefined;
          const newStatus  = entry.details?.new as string | undefined;
          return (
            <div key={i} className="flex items-baseline gap-2 px-4 py-1.5 hover:bg-[#1A1A1E] font-mono text-[11px] border-b border-[#1E1E22]/50">
              <span className="text-zinc-600 tabular-nums flex-shrink-0 w-16">
                {new Date(entry.timestamp).toLocaleTimeString("en-GB", { hour12: false })}
              </span>
              <span className={`flex-shrink-0 ${colorClass}`}>{entry.event}</span>
              {oldStatus && newStatus && (
                <span className="text-zinc-600 flex-shrink-0 text-[10px]">
                  {oldStatus} → {newStatus}
                </span>
              )}
              {entry.step && (
                <span className="text-zinc-500 truncate text-[10px]">@ {entry.step}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ConsoleDetailPanel({
  showDAG,
  onCloseDAG,
  stepsConfig,
  currentStep,
  status,
  focusedStep,
  isFailed,
  isWaitingHuman,
  workflowId,
  workflowType,
  state,
  auditLog,
  inputSchema,
  stepName,
  onHitlSubmit,
  isSubmitting,
  errorMessage,
  relayContext,
}: ConsoleDetailPanelProps) {
  // 1. DAG overlay
  if (showDAG) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between px-4 py-2 border-b border-[#1E1E22] flex-shrink-0">
          <span className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest">WORKFLOW DAG</span>
          <button
            onClick={onCloseDAG}
            className="font-mono text-[10px] text-zinc-500 hover:text-zinc-200 border border-zinc-700 px-2 py-0.5 rounded-none"
          >
            ✕ CLOSE
          </button>
        </div>
        <div className="flex-1 min-h-0">
          <WorkflowDAG
            stepsConfig={stepsConfig}
            currentStep={currentStep}
            status={status}
            bgColor="#111113"
          />
        </div>
      </div>
    );
  }

  // 2. Failed error banner
  if (isFailed) {
    return (
      <div className="flex flex-col h-full overflow-auto">
        <div className="border-l-4 border-red-500 bg-red-500/5 font-mono text-xs text-red-400 px-4 py-3 m-4">
          <div className="font-semibold mb-1">WORKFLOW FAILED</div>
          {errorMessage && <div className="text-red-400/80">{errorMessage}</div>}
        </div>
        {relayContext && <RelayBanner relay={relayContext} />}
        <div className="flex-1 overflow-auto px-4">
          <StatePanel state={state} />
        </div>
        <ConsoleAuditTail entries={auditLog} />
      </div>
    );
  }

  // 3. HITL waiting
  if (isWaitingHuman) {
    const isFraud = workflowType === "FraudCaseReview";
    const isLoan  = workflowType === "LoanApplication";
    const accentBorder = isFraud ? "border-red-500/40"     : isLoan ? "border-emerald-500/40"  : "border-amber-500/40";
    const accentBg     = isFraud ? "bg-red-500/5"          : isLoan ? "bg-emerald-500/5"        : "bg-amber-500/5";
    const dotColor     = isFraud ? "bg-red-400"            : isLoan ? "bg-emerald-400"           : "bg-amber-400";
    const labelColor   = isFraud ? "text-red-400"          : isLoan ? "text-emerald-400"         : "text-amber-400";
    const label        = isFraud ? "FRAUD REVIEW REQUIRED" : isLoan ? "AWAITING UNDERWRITER"     : "AWAITING HUMAN INPUT";

    return (
      <div className="flex flex-col h-full overflow-auto">
        <div className={`border ${accentBorder} ${accentBg} m-4 p-4`}>
          <div className={`font-mono text-xs ${labelColor} font-semibold mb-3 flex items-center gap-2`}>
            <span className={`inline-block w-2 h-2 ${dotColor} rounded-full animate-pulse`} />
            {label}
          </div>
          {isFraud ? (
            <FraudReviewPanel
              workflowId={workflowId}
              state={state}
              onSubmit={onHitlSubmit}
              isSubmitting={isSubmitting}
            />
          ) : isLoan ? (
            <LoanReviewPanel
              workflowId={workflowId}
              state={state}
              onSubmit={onHitlSubmit}
              isSubmitting={isSubmitting}
            />
          ) : (
            <HitlForm
              workflowId={workflowId}
              inputSchema={inputSchema}
              stepName={stepName ?? ""}
              onSubmit={onHitlSubmit}
              isSubmitting={isSubmitting}
            />
          )}
        </div>
        <ConsoleAuditTail entries={auditLog} />
      </div>
    );
  }

  // 4. Focused past step → state diff
  if (focusedStep) {
    const stepEntries = auditLog.filter((e) => e.step === focusedStep);
    if (stepEntries.length >= 2) {
      const before = stepEntries[0].details?.old_state ?? stepEntries[0].details;
      const after  = stepEntries[stepEntries.length - 1].details?.new_state ?? stepEntries[stepEntries.length - 1].details;
      return (
        <div className="flex flex-col h-full">
          <div className="px-4 py-2 border-b border-[#1E1E22] flex-shrink-0">
            <span className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest">
              STEP DIFF · {focusedStep}
            </span>
          </div>
          <div className="flex-1 min-h-0">
            <StateDiff before={before} after={after} />
          </div>
        </div>
      );
    }
  }

  // 5. Default: state + audit tail
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto p-4">
        <StatePanel state={state} />
      </div>
      {relayContext && <RelayBanner relay={relayContext} />}
      <ConsoleAuditTail entries={auditLog} />
    </div>
  );
}
