"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import {
  User, DollarSign, CreditCard, ShieldCheck, ShieldOff,
  AlertTriangle, CheckCircle2, XCircle, Loader2,
  FileText, Globe, Hash, TrendingUp, TrendingDown,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ApplicantProfile {
  user_id?: string;
  name?: string;
  email?: string;
  country?: string;
  age?: number;
  id_document_url?: string;
}

interface CreditCheck {
  score?: number;
  report_id?: string;
  risk_level?: string;
}

interface FraudCheck {
  status?: string;
  score?: number;
  reason?: string | null;
}

interface UnderwritingResult {
  risk_score?: number;
  recommendation?: string;
  detailed_report_url?: string;
}

interface KycResult {
  kyc_overall_status?: string;
  id_verified?: boolean;
  sanctions_screen_passed?: boolean;
  kyc_report_summary?: string;
}

interface LoanCaseState {
  application_id?: string;
  requested_amount?: number;
  applicant_profile?: ApplicantProfile;
  credit_check?: CreditCheck;
  fraud_check?: FraudCheck;
  underwriting_result?: UnderwritingResult;
  sub_workflow_results?: Record<string, unknown>;
  kyc_results?: KycResult;
  pre_approval_status?: string;
  underwriting_type?: string;
  final_loan_status?: string;
}

interface LoanReviewPanelProps {
  workflowId: string;
  state: Record<string, unknown>;
  onSubmit: (data: Record<string, unknown>) => void;
  isSubmitting?: boolean;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function creditColor(score: number) {
  if (score >= 750) return { bar: "bg-emerald-500", text: "text-emerald-400", label: "EXCELLENT" };
  if (score >= 700) return { bar: "bg-emerald-500", text: "text-emerald-400", label: "GOOD" };
  if (score >= 650) return { bar: "bg-yellow-500",  text: "text-yellow-400",  label: "FAIR" };
  if (score >= 600) return { bar: "bg-amber-500",   text: "text-amber-400",   label: "POOR" };
  return               { bar: "bg-red-500",    text: "text-red-400",    label: "VERY POOR" };
}

function fraudColor(status: string, score: number) {
  if (status === "HIGH_RISK") return { icon: ShieldOff, text: "text-red-400",    bg: "bg-red-500/10",    border: "border-red-500/30",    label: "HIGH RISK" };
  if (score > 0.4)            return { icon: AlertTriangle, text: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/30", label: "ELEVATED" };
  return                             { icon: ShieldCheck, text: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/30", label: "CLEAN" };
}

function uwColor(recommendation: string) {
  if (recommendation === "APPROVE") return { text: "text-emerald-400", label: "APPROVE" };
  if (recommendation === "REJECT")  return { text: "text-red-400",    label: "REJECT" };
  return                                   { text: "text-zinc-400",   label: recommendation.toUpperCase() };
}

function kycColor(status: string) {
  if (status === "APPROVED") return "text-emerald-400";
  if (status === "REJECTED") return "text-red-400";
  return "text-amber-400";
}

// ─── Component ────────────────────────────────────────────────────────────────

export function LoanReviewPanel({ workflowId, state, onSubmit, isSubmitting = false }: LoanReviewPanelProps) {
  const { data: session } = useSession();
  const reviewerName = session?.user?.name ?? "Analyst";
  const reviewerEmail = (session?.user as { email?: string })?.email ?? reviewerName;

  const s = state as LoanCaseState;
  const profile   = s.applicant_profile ?? {};
  const credit    = s.credit_check ?? {};
  const fraud     = s.fraud_check ?? {};
  const uw        = s.underwriting_result ?? {};
  const kyc: KycResult = ((s.sub_workflow_results as Record<string, unknown>)?.KYC as KycResult)
    ?? s.kyc_results
    ?? {};

  const creditScore = credit.score ?? 0;
  const creditC     = creditColor(creditScore);
  const fraudC      = fraudColor(fraud.status ?? "UNKNOWN", fraud.score ?? 0);
  const FraudIcon   = fraudC.icon;

  const [notes, setNotes]     = useState("");
  const [decision, setDecision] = useState<"APPROVED" | "REJECTED" | null>(null);

  function submit(d: "APPROVED" | "REJECTED") {
    setDecision(d);
    onSubmit({
      decision: d,
      reviewer_id: reviewerEmail,
      comments: notes || `${d === "APPROVED" ? "Approved" : "Rejected"} by ${reviewerName}`,
    });
  }

  const uwRec = uw.recommendation ?? "";
  const uwC   = uwRec ? uwColor(uwRec) : null;

  return (
    <div className="space-y-4 py-1">

      {/* ── Reviewer identity ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-1">
        <User className="h-3 w-3 text-zinc-600 flex-shrink-0" />
        <span className="font-mono text-[10px] text-zinc-500 uppercase tracking-wider">
          Reviewing as <span className="text-zinc-300">{reviewerName}</span>
        </span>
      </div>

      {/* ── Row 1: Credit · Fraud · Amount ─────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">

        {/* Credit score */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">Credit Score</p>
          <div className={`font-mono text-2xl font-bold ${creditC.text}`}>{creditScore}</div>
          <div className="mt-2 h-1 bg-[#1E1E22] rounded-none overflow-hidden">
            <div className={`h-full ${creditC.bar} transition-all`} style={{ width: `${Math.min((creditScore / 850) * 100, 100)}%` }} />
          </div>
          <div className={`mt-1.5 font-mono text-[9px] ${creditC.text} uppercase tracking-widest`}>
            {creditC.label}
          </div>
          {credit.risk_level && (
            <div className="font-mono text-[9px] text-zinc-600 mt-0.5 uppercase">{credit.risk_level} risk</div>
          )}
        </div>

        {/* Fraud check */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">Fraud Check</p>
          <div className={`inline-flex items-center gap-1.5 px-2 py-1 ${fraudC.bg} border ${fraudC.border} mb-2`}>
            <FraudIcon className={`h-3 w-3 ${fraudC.text} flex-shrink-0`} />
            <span className={`font-mono text-[10px] font-semibold ${fraudC.text}`}>{fraudC.label}</span>
          </div>
          <div className="font-mono text-[10px] text-zinc-500">
            Score: <span className={fraudC.text}>{((fraud.score ?? 0) * 100).toFixed(0)}%</span>
          </div>
          {fraud.reason && (
            <div className="font-mono text-[9px] text-red-400 mt-0.5 truncate">{fraud.reason}</div>
          )}
        </div>

        {/* Loan amount */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">Loan Request</p>
          <div className="flex items-center gap-1.5 mb-1">
            <DollarSign className="h-3 w-3 text-zinc-500 flex-shrink-0" />
            <span className="font-mono text-xl font-bold text-zinc-200">
              {(s.requested_amount ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
            </span>
          </div>
          <div className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mt-1">
            {s.underwriting_type ?? "—"} underwriting
          </div>
          {s.application_id && (
            <div className="flex items-center gap-1 mt-1.5">
              <Hash className="h-2.5 w-2.5 text-zinc-700 flex-shrink-0" />
              <span className="font-mono text-[9px] text-zinc-700 truncate">{s.application_id}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Row 2: Applicant · Underwriting · KYC ─────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">

        {/* Applicant profile */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">Applicant</p>
          <p className="font-mono text-xs text-zinc-200 font-semibold truncate">{profile.name ?? "—"}</p>
          <div className="flex items-center gap-1 mt-1.5">
            <Globe className="h-2.5 w-2.5 text-zinc-700 flex-shrink-0" />
            <span className="font-mono text-[10px] text-zinc-500">{profile.country ?? "—"}</span>
          </div>
          <div className="font-mono text-[10px] text-zinc-600 mt-0.5">
            Age <span className="text-zinc-400">{profile.age ?? "—"}</span>
          </div>
          {profile.id_document_url && (
            <div className="flex items-center gap-1 mt-1">
              <FileText className="h-2.5 w-2.5 text-zinc-700 flex-shrink-0" />
              <span className="font-mono text-[9px] text-zinc-700">ID doc on file</span>
            </div>
          )}
        </div>

        {/* Underwriting result */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">Underwriting</p>
          {uwC ? (
            <>
              <div className={`font-mono text-xs font-semibold ${uwC.text} flex items-center gap-1.5`}>
                {uwRec === "APPROVE"
                  ? <TrendingUp className="h-3 w-3 flex-shrink-0" />
                  : <TrendingDown className="h-3 w-3 flex-shrink-0" />}
                {uwC.label}
              </div>
              <div className="font-mono text-[10px] text-zinc-500 mt-1.5">
                Risk score{" "}
                <span className={uwC.text}>{((uw.risk_score ?? 0) * 100).toFixed(1)}%</span>
              </div>
              <div className="mt-1.5 h-1 bg-[#1E1E22] overflow-hidden">
                <div
                  className={`h-full transition-all ${uwRec === "APPROVE" ? "bg-emerald-500" : "bg-red-500"}`}
                  style={{ width: `${Math.min((uw.risk_score ?? 0) * 100, 100)}%` }}
                />
              </div>
            </>
          ) : (
            <span className="font-mono text-[10px] text-zinc-600">Pending</span>
          )}
        </div>

        {/* KYC status */}
        <div className="bg-[#0A0A0B] border border-[#1E1E22] p-3">
          <p className="font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-2">KYC</p>
          {kyc.kyc_overall_status ? (
            <>
              <div className={`font-mono text-xs font-semibold ${kycColor(kyc.kyc_overall_status)}`}>
                {kyc.kyc_overall_status}
              </div>
              <div className="mt-2 space-y-0.5">
                <div className="flex items-center gap-1.5">
                  <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${kyc.id_verified ? "bg-emerald-500" : "bg-red-500"}`} />
                  <span className="font-mono text-[9px] text-zinc-500">ID verified</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${kyc.sanctions_screen_passed ? "bg-emerald-500" : "bg-red-500"}`} />
                  <span className="font-mono text-[9px] text-zinc-500">Sanctions clear</span>
                </div>
              </div>
            </>
          ) : (
            <span className="font-mono text-[10px] text-zinc-600">Awaiting result</span>
          )}
        </div>
      </div>

      {/* ── Reviewer notes ──────────────────────────────────────────────────── */}
      <div>
        <label className="block font-mono text-[9px] text-zinc-600 uppercase tracking-wider mb-1.5">
          Underwriter Notes (optional)
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
          onClick={() => submit("APPROVED")}
          disabled={isSubmitting}
          className="flex-1 flex items-center justify-center gap-2 font-mono text-xs font-semibold uppercase tracking-wider py-2.5 border transition-all rounded-none
            bg-emerald-500/10 border-emerald-500/40 text-emerald-400
            hover:bg-emerald-500/20 hover:border-emerald-400
            disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isSubmitting && decision === "APPROVED"
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <CheckCircle2 className="h-3.5 w-3.5" />}
          Approve Loan
        </button>

        <button
          onClick={() => submit("REJECTED")}
          disabled={isSubmitting}
          className="flex-1 flex items-center justify-center gap-2 font-mono text-xs font-semibold uppercase tracking-wider py-2.5 border transition-all rounded-none
            bg-red-500/10 border-red-500/40 text-red-400
            hover:bg-red-500/20 hover:border-red-400
            disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isSubmitting && decision === "REJECTED"
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <XCircle className="h-3.5 w-3.5" />}
          Reject Loan
        </button>
      </div>

      {/* ── Workflow ID footer ───────────────────────────────────────────────── */}
      <p className="font-mono text-[9px] text-zinc-700 text-right">
        case {workflowId.slice(0, 16)}…
      </p>
    </div>
  );
}
