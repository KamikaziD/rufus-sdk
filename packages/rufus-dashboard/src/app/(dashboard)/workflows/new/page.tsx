"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useWorkflowTypes, useStartWorkflow } from "@/lib/hooks/useWorkflow";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, Loader2 } from "lucide-react";

export default function NewWorkflowPage() {
  const router = useRouter();
  const { data: typesData, isLoading: typesLoading } = useWorkflowTypes();
  const startWorkflow = useStartWorkflow();

  const [selectedType, setSelectedType] = useState("");
  const [rawJson, setRawJson] = useState("{}");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState(false);

  const types = typesData?.types ?? [];

  function validateJson(val: string): Record<string, unknown> | null {
    try {
      setJsonError(null);
      return JSON.parse(val);
    } catch {
      setJsonError("Invalid JSON");
      return null;
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = validateJson(rawJson);
    if (!parsed || !selectedType) return;

    const result = await startWorkflow.mutateAsync({
      workflow_type: selectedType,
      initial_data: parsed,
      dry_run: dryRun,
    });

    if (!dryRun && result.workflow_id) {
      router.push(`/workflows/${result.workflow_id}`);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Start Workflow</h1>
        <p className="text-muted-foreground">Launch a new workflow execution</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Workflow Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Type selector */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Workflow Type</label>
              {typesLoading ? (
                <div className="h-9 animate-pulse bg-muted rounded-md" />
              ) : (
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                  value={selectedType}
                  onChange={(e) => setSelectedType(e.target.value)}
                  required
                >
                  <option value="">Select a workflow type...</option>
                  {types.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              )}
            </div>

            {/* Initial data JSON */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Initial Data (JSON)</label>
              <textarea
                className="flex min-h-[140px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono resize-y"
                value={rawJson}
                onChange={(e) => {
                  setRawJson(e.target.value);
                  validateJson(e.target.value);
                }}
                spellCheck={false}
              />
              {jsonError && (
                <p className="text-xs text-destructive flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" /> {jsonError}
                </p>
              )}
            </div>

            {/* Dry run toggle */}
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="dry-run"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              <label htmlFor="dry-run" className="text-sm font-medium">
                Dry run (validate without persisting)
              </label>
            </div>

            {/* Error */}
            {startWorkflow.error && (
              <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 p-3 rounded-md">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                {(startWorkflow.error as Error).message}
              </div>
            )}

            {/* Dry run result */}
            {dryRun && startWorkflow.data && (
              <div className="bg-muted rounded-md p-3 text-sm font-mono whitespace-pre">
                {JSON.stringify(startWorkflow.data, null, 2)}
              </div>
            )}

            <div className="flex gap-3">
              <Button type="submit" disabled={!selectedType || !!jsonError || startWorkflow.isPending}>
                {startWorkflow.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {dryRun ? "Validate" : "Start Workflow"}
              </Button>
              <Button type="button" variant="outline" onClick={() => router.back()}>
                Cancel
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
