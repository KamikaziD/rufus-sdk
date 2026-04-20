"use client";

import { useState, useEffect, useRef } from "react";
import { useSession } from "next-auth/react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { startConfigRollout, getRolloutStatus } from "@/lib/api";
import { CheckCircle2, ChevronRight, ChevronLeft, Loader2, XCircle } from "lucide-react";

type WizardStep = 1 | 2 | 3 | 4;

interface WizardState {
  configChanges: string[];
  targetDevices: string[];
  rolloutStrategy: "all" | "canary";
  canaryPercent: number;
}

interface RolloutProgress {
  total_devices: number;
  status_breakdown: Record<string, number>;
  workflowId: string | null;
  outcome: string | null;
  error: string | null;
}

interface ConfigPushWizardProps {
  onClose: () => void;
}

export function ConfigPushWizard({ onClose }: ConfigPushWizardProps) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const [step, setStep] = useState<WizardStep>(1);
  const [state, setState] = useState<WizardState>({
    configChanges: [],
    targetDevices: [],
    rolloutStrategy: "all",
    canaryPercent: 10,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [progress, setProgress] = useState<RolloutProgress | null>(null);
  const [done, setDone] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Polling ref — cleared on unmount
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function nextStep() { setStep((s) => Math.min(s + 1, 4) as WizardStep); }
  function prevStep() { setStep((s) => Math.max(s - 1, 1) as WizardStep); }

  async function handleSubmit() {
    if (!token) return;
    setIsSubmitting(true);
    setSubmitError(null);
    setProgress(null);

    try {
      const res = await startConfigRollout(token, {
        rollout_strategy: state.rolloutStrategy === "canary"
          ? `canary_${state.canaryPercent}`
          : "all",
        target_devices: state.targetDevices.length > 0 ? state.targetDevices : undefined,
      });

      const workflowId = res.workflow_id ?? null;
      const outcome = res.rollout_outcome ?? res.status ?? null;

      // Seed initial progress display
      setProgress({
        total_devices: 0,
        status_breakdown: {},
        workflowId,
        outcome,
        error: null,
      });

      // Start polling rollout status every 3s
      pollRef.current = setInterval(async () => {
        try {
          const status = await getRolloutStatus(token);
          setProgress((prev) => ({
            total_devices: status.total_devices,
            status_breakdown: status.status_breakdown,
            workflowId: prev?.workflowId ?? null,
            outcome: prev?.outcome ?? null,
            error: null,
          }));
        } catch {
          // Ignore poll errors silently — don't interrupt the wizard
        }
      }, 3000);

      // Auto-complete after 10s (rollout endpoint is synchronous — workflow finishes before returning)
      setTimeout(() => {
        if (pollRef.current) clearInterval(pollRef.current);
        setIsSubmitting(false);
        setDone(true);
      }, 10_000);

    } catch (err) {
      setIsSubmitting(false);
      setSubmitError(err instanceof Error ? err.message : "Rollout failed.");
    }
  }

  function handleAbort() {
    if (pollRef.current) clearInterval(pollRef.current);
    setIsSubmitting(false);
    setProgress(null);
  }

  const stepLabels = ["Config Changes", "Target Devices", "Rollout Strategy", "Confirm"];

  if (done) {
    return (
      <Card>
        <CardContent className="py-10 text-center space-y-3">
          <CheckCircle2 className="h-10 w-10 text-green-500 mx-auto" />
          <p className="font-semibold">Rollout Complete</p>
          {progress && progress.total_devices > 0 && (
            <div className="flex justify-center gap-3 flex-wrap text-sm">
              {Object.entries(progress.status_breakdown).map(([k, v]) => (
                <Badge key={k} variant="secondary">{k}: {v}</Badge>
              ))}
            </div>
          )}
          <p className="text-sm text-muted-foreground">
            Config push finished. Monitor results in the Policies page.
          </p>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </CardContent>
      </Card>
    );
  }

  // Live progress panel (after submit, before done)
  if (isSubmitting && progress) {
    const breakdown = progress.status_breakdown;
    const successCount = (breakdown["applied"] ?? 0) + (breakdown["COMPLETED"] ?? 0);
    const failCount = (breakdown["failed"] ?? 0) + (breakdown["FAILED"] ?? 0);

    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            Rollout In Progress
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {progress.workflowId && (
            <p className="text-xs text-muted-foreground font-mono">
              Workflow: {progress.workflowId}
            </p>
          )}

          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg border p-3">
              <p className="text-2xl font-bold">{progress.total_devices}</p>
              <p className="text-xs text-muted-foreground mt-0.5">Total Devices</p>
            </div>
            <div className="rounded-lg border border-green-200 bg-green-50 p-3">
              <p className="text-2xl font-bold text-green-700">{successCount}</p>
              <p className="text-xs text-green-600 mt-0.5">Applied</p>
            </div>
            <div className="rounded-lg border border-red-200 bg-red-50 p-3">
              <p className="text-2xl font-bold text-red-700">{failCount}</p>
              <p className="text-xs text-red-600 mt-0.5">Failed</p>
            </div>
          </div>

          {Object.keys(breakdown).length > 0 && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(breakdown).map(([k, v]) => (
                <Badge key={k} variant="secondary" className="text-xs">{k}: {v}</Badge>
              ))}
            </div>
          )}

          <p className="text-xs text-muted-foreground text-center animate-pulse">
            Polling for updates every 3s…
          </p>

          <div className="flex justify-center">
            <Button variant="outline" size="sm" onClick={handleAbort}>
              <XCircle className="h-3.5 w-3.5" />
              Abort Monitor
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Config Push Wizard</CardTitle>
        {/* Step progress */}
        <div className="flex items-center gap-1 mt-2">
          {stepLabels.map((label, i) => (
            <div key={label} className="flex items-center gap-1">
              <span
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                  i + 1 < step ? "bg-green-500 text-white" :
                  i + 1 === step ? "bg-primary text-primary-foreground" :
                  "bg-muted text-muted-foreground"
                }`}
              >
                {i + 1 < step ? "✓" : i + 1}
              </span>
              <span className={`text-xs hidden sm:block ${i + 1 === step ? "font-medium" : "text-muted-foreground"}`}>
                {label}
              </span>
              {i < stepLabels.length - 1 && <div className="w-4 h-0.5 bg-border" />}
            </div>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {submitError && (
          <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            {submitError}
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Select config sections to push:</p>
            {["Fraud Rules", "Floor Limits", "Feature Flags", "Rate Limits"].map((item) => (
              <label key={item} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={state.configChanges.includes(item)}
                  onChange={(e) => setState((s) => ({
                    ...s,
                    configChanges: e.target.checked
                      ? [...s.configChanges, item]
                      : s.configChanges.filter((c) => c !== item),
                  }))}
                  className="h-4 w-4 rounded"
                />
                {item}
              </label>
            ))}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Target device selection:</p>
            <div className="flex gap-2">
              {["All Devices", "Online Only", "By Type"].map((opt) => (
                <button
                  key={opt}
                  onClick={() => setState((s) => ({ ...s, targetDevices: [opt] }))}
                  className={`px-3 py-1.5 rounded-md border text-sm transition-colors ${
                    state.targetDevices.includes(opt)
                      ? "bg-primary text-primary-foreground border-primary"
                      : "border-border hover:border-foreground"
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">Choose rollout strategy:</p>
            <div className="space-y-2">
              {(["all", "canary"] as const).map((strategy) => (
                <label key={strategy} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="radio"
                    checked={state.rolloutStrategy === strategy}
                    onChange={() => setState((s) => ({ ...s, rolloutStrategy: strategy }))}
                  />
                  <span className="font-medium">
                    {strategy === "all" ? "All at once" : "Canary rollout"}
                  </span>
                  <span className="text-muted-foreground">
                    {strategy === "all"
                      ? "— push to all targets simultaneously"
                      : `— start with ${state.canaryPercent}%, then 100%`}
                  </span>
                </label>
              ))}
              {state.rolloutStrategy === "canary" && (
                <div className="ml-6 flex items-center gap-2">
                  <label className="text-sm">Canary %:</label>
                  <input
                    type="range" min={5} max={50} step={5}
                    value={state.canaryPercent}
                    onChange={(e) => setState((s) => ({ ...s, canaryPercent: +e.target.value }))}
                    className="w-32"
                  />
                  <Badge variant="info">{state.canaryPercent}%</Badge>
                </div>
              )}
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <p className="text-sm font-medium">Review and confirm:</p>
            <div className="space-y-2 text-sm">
              <SummaryRow label="Config changes" value={state.configChanges.join(", ") || "None selected"} />
              <SummaryRow label="Target devices" value={state.targetDevices.join(", ") || "All devices"} />
              <SummaryRow label="Strategy"       value={state.rolloutStrategy === "canary" ? `Canary (${state.canaryPercent}%)` : "All at once"} />
            </div>
            <p className="text-xs text-muted-foreground bg-muted rounded p-3">
              This will push config changes to the selected devices. A saga compensation will
              automatically restore the previous config if the broadcast fails.
            </p>
          </div>
        )}

        {/* Navigation */}
        <div className="flex justify-between mt-6">
          <Button variant="outline" onClick={step === 1 ? onClose : prevStep}>
            {step === 1 ? "Cancel" : <><ChevronLeft className="h-3.5 w-3.5" /> Back</>}
          </Button>
          <Button
            onClick={step === 4 ? handleSubmit : nextStep}
            disabled={isSubmitting || (step === 1 && state.configChanges.length === 0)}
          >
            {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {step === 4 ? "Start Rollout" : <>Next <ChevronRight className="h-3.5 w-3.5" /></>}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b pb-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
