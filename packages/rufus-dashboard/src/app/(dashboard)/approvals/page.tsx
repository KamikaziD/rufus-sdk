"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { useApprovals } from "@/lib/hooks/useApprovals";
import { useResumeWorkflow } from "@/lib/hooks/useWorkflow";
import { WorkflowStatusBadge } from "@/components/shared/StatusBadge";
import { HitlForm } from "@/components/workflows/HitlForm";
import { FraudReviewPanel } from "@/components/approvals/FraudReviewPanel";
import { LoanReviewPanel } from "@/components/approvals/LoanReviewPanel";
import { formatRelativeTime, truncateId } from "@/lib/utils";
import { CheckSquare, RefreshCw, X, ShieldAlert, Banknote } from "lucide-react";
import type { WorkflowExecution } from "@/types";

const SEARCH_INPUT = "bg-[#0A0A0B] border border-[#1E1E22] font-mono text-xs text-zinc-300 placeholder-zinc-600 px-3 py-1.5 w-64 focus:outline-none focus:border-zinc-500 transition-colors rounded-none";

// ─── Panel registry — add new workflow types here ─────────────────────────────
// Maps workflow_type → { accentColor, badge label, card icon, expand panel }

type PanelVariant = "fraud" | "loan" | "default";

function getPanelVariant(workflowType: string): PanelVariant {
  if (workflowType === "FraudCaseReview") return "fraud";
  if (workflowType === "LoanApplication")  return "loan";
  return "default";
}

const VARIANT_STYLES: Record<PanelVariant, {
  border: string;
  activeBorder: string;
  expandBg: string;
  expandBorder: string;
}> = {
  fraud: {
    border:       "border-[#1E1E22]",
    activeBorder: "border-red-500/40",
    expandBg:     "bg-red-500/5",
    expandBorder: "border-red-500/20",
  },
  loan: {
    border:       "border-[#1E1E22]",
    activeBorder: "border-emerald-500/40",
    expandBg:     "bg-emerald-500/5",
    expandBorder: "border-emerald-500/20",
  },
  default: {
    border:       "border-[#1E1E22]",
    activeBorder: "border-amber-500/40",
    expandBg:     "bg-amber-500/5",
    expandBorder: "border-amber-500/20",
  },
};

// ─── Toast ────────────────────────────────────────────────────────────────────

interface ToastData {
  workflowId: string;
  alertId: string;
  amount: number;
  currency: string;
}

function FraudToast({ toast, onDismiss }: { toast: ToastData; onDismiss: () => void }) {
  return (
    <div className="fixed bottom-6 right-6 z-50 flex items-start gap-3 bg-[#111113] border border-red-500/40 px-4 py-3 shadow-xl animate-in slide-in-from-bottom-2 duration-300 max-w-xs">
      <ShieldAlert className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="font-mono text-[11px] font-semibold text-red-400 uppercase tracking-wider">Fraud Review Required</p>
        <p className="font-mono text-[10px] text-zinc-400 mt-0.5 truncate">
          {toast.currency} {toast.amount.toFixed(2)} · alert {toast.alertId.slice(0, 10)}
        </p>
        <p className="font-mono text-[9px] text-zinc-600 mt-0.5">
          case {toast.workflowId.slice(0, 12)}…
        </p>
      </div>
      <button onClick={onDismiss} className="text-zinc-600 hover:text-zinc-400 flex-shrink-0">
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ApprovalsPage() {
  const { data, isLoading, refetch } = useApprovals();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const resumeWorkflow = useResumeWorkflow();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [toast, setToast] = useState<ToastData | null>(null);
  const knownFraudIds = useRef<Set<string>>(new Set());
  const initializedRef = useRef(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Detect new FraudCaseReview arrivals and show toast
  useEffect(() => {
    if (!data) return;
    const fraudCases = data.workflows.filter((wf) => wf.workflow_type === "FraudCaseReview");
    if (!initializedRef.current) {
      fraudCases.forEach((wf) => knownFraudIds.current.add(wf.workflow_id));
      initializedRef.current = true;
      return;
    }
    for (const wf of fraudCases) {
      if (!knownFraudIds.current.has(wf.workflow_id)) {
        knownFraudIds.current.add(wf.workflow_id);
        const s = wf.state as Record<string, unknown>;
        setToast({
          workflowId: wf.workflow_id,
          alertId: String(s.alert_id ?? ""),
          amount: Number(s.amount ?? 0),
          currency: String(s.currency ?? "USD"),
        });
        if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
        toastTimerRef.current = setTimeout(() => setToast(null), 5000);
      }
    }
  }, [data]);

  useEffect(() => () => { if (toastTimerRef.current) clearTimeout(toastTimerRef.current); }, []);

  const allApprovals = data?.workflows ?? [];

  const approvals = useMemo(() => {
    if (!debouncedSearch) return allApprovals;
    const q = debouncedSearch.toLowerCase();
    return allApprovals.filter(
      (wf) =>
        wf.workflow_type.toLowerCase().includes(q) ||
        wf.workflow_id.toLowerCase().includes(q)
    );
  }, [allApprovals, debouncedSearch]);

  return (
    <>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">APPROVAL QUEUE</h1>
            <p className="font-mono text-[10px] text-zinc-600 mt-0.5">{approvals.length} workflows awaiting input</p>
          </div>
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>

        {/* Search */}
        <div className="relative inline-block">
          <input
            type="text"
            placeholder="Search by type or ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={SEARCH_INPUT}
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-400"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-20 animate-pulse bg-[#111113] border border-[#1E1E22] rounded-none" />
            ))}
          </div>
        ) : approvals.length === 0 ? (
          <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-12 text-center">
            <CheckSquare className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
            <p className="font-mono text-xs text-zinc-600">NO PENDING APPROVALS</p>
          </div>
        ) : (
          <div className="space-y-3">
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

      {toast && (
        <FraudToast
          toast={toast}
          onDismiss={() => {
            setToast(null);
            if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
          }}
        />
      )}
    </>
  );
}

// ─── Approval Card ────────────────────────────────────────────────────────────

function CardHeader({ workflow, variant }: { workflow: WorkflowExecution; variant: PanelVariant }) {
  const s = workflow.state as Record<string, unknown>;

  if (variant === "fraud") {
    return (
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-3.5 w-3.5 text-red-400 flex-shrink-0" />
        <span className="font-mono text-sm text-[#E4E4E7]">{workflow.workflow_type}</span>
        <span className="font-mono text-[9px] bg-red-500/10 text-red-400 border border-red-500/20 px-1.5 py-0.5 uppercase tracking-wider">
          Fraud Review
        </span>
      </div>
    );
  }

  if (variant === "loan") {
    const profile = s.applicant_profile as Record<string, unknown> | undefined;
    return (
      <div className="flex items-center gap-2">
        <Banknote className="h-3.5 w-3.5 text-emerald-400 flex-shrink-0" />
        <span className="font-mono text-sm text-[#E4E4E7]">{workflow.workflow_type}</span>
        <span className="font-mono text-[9px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 uppercase tracking-wider">
          Underwriter Review
        </span>
        {profile?.name && (
          <span className="font-mono text-[10px] text-zinc-500 truncate max-w-[120px]">
            {String(profile.name)}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="inline-block w-2 h-2 bg-yellow-400 rounded-full animate-pulse flex-shrink-0" />
      <span className="font-mono text-sm text-[#E4E4E7]">{workflow.workflow_type}</span>
    </div>
  );
}

function CardSubline({ workflow, variant }: { workflow: WorkflowExecution; variant: PanelVariant }) {
  const s = workflow.state as Record<string, unknown>;

  return (
    <div className="flex items-center gap-3 mt-1">
      <span className="font-mono text-[10px] text-zinc-600">#{truncateId(workflow.workflow_id, 8)}</span>
      {workflow.current_step && (
        <span className="font-mono text-[10px] text-zinc-600">→ {workflow.current_step}</span>
      )}
      {variant === "fraud" && s.amount ? (
        <span className="font-mono text-[10px] text-zinc-500">
          {String(s.currency ?? "USD")} {Number(s.amount).toFixed(2)}
        </span>
      ) : null}
      {variant === "loan" && s.requested_amount ? (
        <span className="font-mono text-[10px] text-zinc-500">
          {Number(s.requested_amount).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
        </span>
      ) : null}
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
  const variant = getPanelVariant(workflow.workflow_type);
  const styles  = VARIANT_STYLES[variant];

  return (
    <div className={`bg-[#111113] border rounded-none ${isSelected ? styles.activeBorder : styles.border}`}>
      <button
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-[#1A1A1E] transition-colors"
        onClick={onSelect}
      >
        <div className="text-left">
          <CardHeader workflow={workflow} variant={variant} />
          <CardSubline workflow={workflow} variant={variant} />
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="font-mono text-[10px] text-zinc-600">{formatRelativeTime(workflow.started_at)}</span>
          <WorkflowStatusBadge status={workflow.status} />
        </div>
      </button>

      {isSelected && (
        <div className={`border-t px-4 py-4 ${styles.expandBorder} ${styles.expandBg}`}>
          {variant === "fraud" ? (
            <FraudReviewPanel
              workflowId={workflow.workflow_id}
              state={workflow.state as Record<string, unknown>}
              onSubmit={onSubmit}
              isSubmitting={isSubmitting}
            />
          ) : variant === "loan" ? (
            <LoanReviewPanel
              workflowId={workflow.workflow_id}
              state={workflow.state as Record<string, unknown>}
              onSubmit={onSubmit}
              isSubmitting={isSubmitting}
            />
          ) : (
            <HitlForm
              workflowId={workflow.workflow_id}
              inputSchema={(workflow.state as Record<string, unknown>)?._input_schema as Record<string, unknown> | undefined}
              stepName={workflow.current_step ?? ""}
              onSubmit={onSubmit}
              isSubmitting={isSubmitting}
            />
          )}
        </div>
      )}
    </div>
  );
}
