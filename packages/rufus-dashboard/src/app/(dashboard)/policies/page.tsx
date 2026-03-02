"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listPolicies, createPolicy, updatePolicyStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Shield, RefreshCw, Plus } from "lucide-react";

const STATUS_VARIANT: Record<string, "success" | "secondary" | "outline"> = {
  ACTIVE:   "success",
  PAUSED:   "secondary",
  ARCHIVED: "outline",
  DRAFT:    "outline",
};

// Status transitions available per current status
const NEXT_ACTIONS: Record<string, Array<{ label: string; value: "active" | "paused" | "archived" }>> = {
  DRAFT:    [{ label: "Activate", value: "active" }],
  ACTIVE:   [{ label: "Pause", value: "paused" }, { label: "Archive", value: "archived" }],
  PAUSED:   [{ label: "Activate", value: "active" }, { label: "Archive", value: "archived" }],
  ARCHIVED: [],
};

const EMPTY_FORM = {
  policy_name: "",
  description: "",
  condition: "default",
  artifact: "",
};

export default function PoliciesPage() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const queryClient = useQueryClient();

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["policies"],
    queryFn: () => listPolicies(token!),
    enabled: !!token,
  });

  const policies = data?.policies ?? [];

  const createMutation = useMutation({
    mutationFn: () =>
      createPolicy(token!, {
        policy_name: form.policy_name,
        description: form.description || undefined,
        rules: [{ condition: form.condition, artifact: form.artifact }],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["policies"] });
      setIsCreateOpen(false);
      setForm(EMPTY_FORM);
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "active" | "paused" | "archived" }) =>
      updatePolicyStatus(token!, id, status),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Policies</h1>
          <p className="text-muted-foreground">{policies.length} policies configured</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setIsCreateOpen(true)}>
            <Plus className="h-3.5 w-3.5" />
            Create Policy
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(4)].map((_, i) => <div key={i} className="h-12 animate-pulse bg-muted rounded" />)}
            </div>
          ) : policies.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">
              <Shield className="h-8 w-8 mx-auto mb-3 opacity-30" />
              No policies configured
            </div>
          ) : (
            <div className="divide-y">
              {policies.map((policy) => {
                const statusKey = policy.status?.toUpperCase() ?? "DRAFT";
                const actions = NEXT_ACTIONS[statusKey] ?? [];
                return (
                  <div key={policy.policy_id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="font-medium">{policy.name}</p>
                      <p className="text-xs text-muted-foreground">{policy.description}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={STATUS_VARIANT[statusKey] ?? "outline"}>{statusKey}</Badge>
                      {actions.map((action) => (
                        <Button
                          key={action.value}
                          variant="outline"
                          size="sm"
                          disabled={statusMutation.isPending}
                          onClick={() => statusMutation.mutate({ id: policy.policy_id, status: action.value })}
                        >
                          {action.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Policy Modal */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Policy</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">Policy Name *</label>
              <input
                className="mt-1 w-full border rounded px-3 py-2 text-sm bg-background"
                placeholder="e.g. fraud-rules-v2"
                value={form.policy_name}
                onChange={(e) => setForm((f) => ({ ...f, policy_name: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium">Description</label>
              <input
                className="mt-1 w-full border rounded px-3 py-2 text-sm bg-background"
                placeholder="Optional description"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium">Rule Condition *</label>
              <input
                className="mt-1 w-full border rounded px-3 py-2 text-sm bg-background font-mono"
                placeholder='e.g. hardware == "NVIDIA" or "default"'
                value={form.condition}
                onChange={(e) => setForm((f) => ({ ...f, condition: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-sm font-medium">Artifact *</label>
              <input
                className="mt-1 w-full border rounded px-3 py-2 text-sm bg-background"
                placeholder="e.g. model_v2.pex"
                value={form.artifact}
                onChange={(e) => setForm((f) => ({ ...f, artifact: e.target.value }))}
              />
            </div>
          </div>

          {createMutation.isError && (
            <p className="text-sm text-destructive mt-2">
              {(createMutation.error as Error)?.message ?? "Failed to create policy"}
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={!form.policy_name || !form.artifact || createMutation.isPending}
            >
              {createMutation.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
