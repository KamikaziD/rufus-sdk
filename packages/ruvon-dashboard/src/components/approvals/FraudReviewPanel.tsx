"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import {
  ShieldAlert, Cpu, CreditCard, Hash, TrendingUp,
  AlertTriangle, CheckCircle2, XCircle, Loader2, User,
} from "lucide-react";

// ─── Rule / typology display labels ──────────────────────────────────────────

const RULE_LABELS: Record<string, string> = {
  pos_r001_velocity:       "Velocity (≥3 txn / 60 min)",
  pos_r002_micro_struct:   "Micro-structuring ($900–$999)",
  pos_r003_card_testing:   "Card Testing (<$5)",
  pos_r004_unknown_merchant: "Unknown Merchant",
  pos_r005_amount_spike:   "Amount Spike (>$200)",
  atm_r001_large_cash:     "Large Cash (>$400)",
  atm_r002_after_hours:    "After-Hours (23:00–06:00 UTC)",
  atm_r003_structuring:    "Structuring ($450–$499)",
  atm_r004_velocity:       "ATM Velocity (≥2 txn / 30 min)",
  atm_r005_large_daily:    "Large Daily (>$700)",
  atm_r006_unknown_location: "Unknown ATM Location",
};

const TYPOLOGY_LABELS: Record<string, string> = {
  card_testing:              "Card Testing",
  micro_structuring_pos:     "Micro-structuring",
  velocity_fraud:            "Velocity Fraud",
  unknown_merchant:          "Unknown Merchant",
  unknown_merchant_large_txn:"Unknown Merchant + Large Txn",
  unknown_merchant_velocity: "Unknown Merchant + Velocity",
  cash_structuring_atm:      "Cash Structuring (ATM)",
  nighttime_account_raid:    "Nighttime Account Raid",
  atm_velocity_fraud:        "ATM Velocity Fraud",
  nighttime_structuring:     "Nighttime Structuring",
  unknown_atm_location:      "Unknown ATM Location",
  unknown_atm_large_cash:    "Unknown ATM + Large Cash",
  unknown_atm_velocity:      "Unknown ATM + Velocity",
};

// ─── Types ────────────────────────────────────────────────────────────────────

interface FraudCaseState {
  device_id?: string;
  device_type?: string;
  transaction_id?: string;
  alert_id?: string;
  amount?: number;
  currency?: string;
  rules_fired?: string[];
  typologies_triggered?: string[];
  ml_risk_score?: number;
  case_summary?: string;
  risk_band?: string;
}

interface FraudReviewPanelProps {
  workflowId: string;
  state: Record<string, unknown>;
  onSubmit: (data: Record<string, unknown>) => void;
  isSubmitting?: boolean;
}

// ─── Risk helpers ─────────────────────────────────────────────────────────────

function riskColor(score: number) {
  if (score >= 0.8)  return { bar: "bg-red-500",   text: "text-red-400",   label: "CRITICAL" };
  if (score >= 0.6)  return { bar: "bg-amber-500",  text: "text-amber-400",  label: "HIGH" };
  if (score >= 0.3)  return { bar: "bg-yellow-500", text: "text-yellow-400", label: "MEDIUM" };
  return               { bar: "bg-emerald-500", text: "text-emerald-400", label: "LOW" };
}

// ─── Component ────────────────────────────────────────────────────────────────

export function FraudReviewPanel({ workflowId, state, onSubmit, isSubmitting = false }: FraudReviewPanelProps) {
  const { data: session } = useSession();
  const reviewerName = session?.user?.name ?? "Analyst";

  const s = state as FraudCaseState;
  const score   = s.ml_risk_score ?? 0;
  const risk    = riskColor(score);
  const rules   = s.rules_fired ?? [];
  const typologies = s.typologies_triggered ?? [];
  const deviceType = (s.device_type ?? "pos").toUpperCase();

  const [notes, setNotes]     = useState("");
  const [decision, setDecision] = useState<"APPROVE" | "BLOCK" | null>(null);

  function submit(d: "APPROVE" | "BLOCK") {
    setDecision(d);
    onSubmit({
      reviewer_decision: d,
      reviewer_notes: notes || `${d === "APPROVE" ? "Approved" : "Blocked"} by ${reviewerName}`,
    });
  }

  // ── Layout ──────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4 py-1">

      {/* ── Reviewer identity ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-1">
        <User className="h-3 w-3 text-zinc-600 flex-shrink-0" />
        <span className="font-mono text-[10px] text-zinc-500 uppercase tracking-wider">
          Reviewing as <span className="text-zinc-300">{reviewerName}</span>
        </span>
      </div>

      {/* ── Top row: Risk score + Device + Transaction ─────────────────────── */}
      <div className="grid grid-cols-3 gap-3">

        {/* Risk score */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">ML Risk Score</p>
          <div className={`font-mono text-2xl font-bold ${risk.text}`}>
            {(score * 100).toFixed(1)}%
          </div>
          <div className="mt-2 h-1 bg-[#1E1E22] rounded-none overflow-hidden">
            <div className={`h-full ${risk.bar} transition-all`} style={{ width: `${score * 100}%` }} />
          </div>
          <div className={`mt-1.5 font-mono text-[9px] ${risk.text} uppercase tracking-widest`}>
            {risk.label}
          </div>
        </div>

        {/* Device */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">Device</p>
          <div className="flex items-center gap-1.5 mb-1">
            <Cpu className="h-3 w-3 text-zinc-500 flex-shrink-0" />
            <span className="font-mono text-xs text-zinc-200 truncate">{s.device_id ?? "—"}</span>
          </div>
          <span className="font-mono text-[10px] text-zinc-500 uppercase">{deviceType}</span>
        </div>

        {/* Transaction */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">Transaction</p>
          <div className="flex items-center gap-1.5 mb-1">
            <CreditCard className="h-3 w-3 text-zinc-500 flex-shrink-0" />
            <span className={`font-mono text-sm font-semibold ${risk.text}`}>
              {s.currency ?? "USD"} {(s.amount ?? 0).toFixed(2)}
            </span>
          </div>
          <div className="flex items-center gap-1 mt-1">
            <Hash className="h-2.5 w-2.5 text-zinc-700 flex-shrink-0" />
            <span className="font-mono text-[9px] text-zinc-600 truncate">
              {s.transaction_id ? s.transaction_id.slice(0, 16) + "…" : "—"}
            </span>
          </div>
          {s.alert_id && (
            <div className="flex items-center gap-1 mt-0.5">
              <AlertTriangle className="h-2.5 w-2.5 text-amber-700 flex-shrink-0" />
              <span className="font-mono text-[9px] text-amber-700">alert {s.alert_id.slice(0, 12)}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Rules fired ─────────────────────────────────────────────────────── */}
      {rules.length > 0 && (
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <ShieldAlert className="h-3 w-3 text-amber-500 flex-shrink-0" />
            <p className="font-mono text-[9px] text-zinc-500 uppercase tracking-wider">
              Rules Fired ({rules.length})
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {rules.map((r) => (
              <span
                key={r}
                className="font-mono text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5"
              >
                {RULE_LABELS[r] ?? r}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Typologies ──────────────────────────────────────────────────────── */}
      {typologies.length > 0 && (
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="h-3 w-3 text-red-400 flex-shrink-0" />
            <p className="font-mono text-[9px] text-zinc-500 uppercase tracking-wider">
              Typologies Matched
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {typologies.map((t) => (
              <span
                key={t}
                className="font-mono text-[10px] bg-red-500/10 text-red-400 border border-red-500/20 px-2 py-0.5"
              >
                {TYPOLOGY_LABELS[t] ?? t}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Reviewer notes ──────────────────────────────────────────────────── */}
      <div>
        <label className="block font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5">
          Reviewer Notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Add notes for the audit log…"
          rows={2}
          className="w-full bg-[#0A0A0B] border border-[#1E1E22] font-mono text-xs text-zinc-300 placeholder-zinc-700 px-3 py-2 resize-none focus:outline-none focus:border-zinc-500 transition-colors rounded-none"
        />
      </div>

      {/* ── Decision buttons ─────────────────────────────────────────────────── */}
      <div className="flex gap-3 pt-1">
        <button
          onClick={() => submit("APPROVE")}
          disabled={isSubmitting}
          className="flex-1 flex items-center justify-center gap-2 font-mono text-xs font-semibold uppercase tracking-wider py-2.5 border transition-all rounded-none
            bg-emerald-500/10 border-emerald-500/40 text-emerald-400
            hover:bg-emerald-500/20 hover:border-emerald-400
            disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isSubmitting && decision === "APPROVE"
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <CheckCircle2 className="h-3.5 w-3.5" />}
          Approve Transaction
        </button>

        <button
          onClick={() => submit("BLOCK")}
          disabled={isSubmitting}
          className="flex-1 flex items-center justify-center gap-2 font-mono text-xs font-semibold uppercase tracking-wider py-2.5 border transition-all rounded-none
            bg-red-500/10 border-red-500/40 text-red-400
            hover:bg-red-500/20 hover:border-red-400
            disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isSubmitting && decision === "BLOCK"
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <XCircle className="h-3.5 w-3.5" />}
          Block Transaction
        </button>
      </div>

      {/* ── Workflow ID footer ───────────────────────────────────────────────── */}
      <p className="font-mono text-[9px] text-zinc-700 text-right">
        case {workflowId.slice(0, 16)}…
      </p>
    </div>
  );
}
