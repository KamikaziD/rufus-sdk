"use client";

import { useState, useMemo, useEffect } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listPolicies, createPolicy, updatePolicyStatus } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Shield, RefreshCw, Plus, X } from "lucide-react";

const STATUS_CLS: Record<string, string> = {
  ACTIVE:   "border-emerald-500/40 text-emerald-400 bg-emerald-500/10",
  PAUSED:   "border-yellow-500/40 text-yellow-400 bg-yellow-500/10",
  ARCHIVED: "border-zinc-600 text-zinc-500 bg-zinc-800/50",
  DRAFT:    "border-zinc-600 text-zinc-500 bg-zinc-800/50",
};

const NEXT_ACTIONS: Record<string, Array<{ label: string; value: "active" | "paused" | "archived" }>> = {
  DRAFT:    [{ label: "ACTIVATE", value: "active" }],
  ACTIVE:   [{ label: "PAUSE", value: "paused" }, { label: "ARCHIVE", value: "archived" }],
  PAUSED:   [{ label: "ACTIVATE", value: "active" }, { label: "ARCHIVE", value: "archived" }],
  ARCHIVED: [],
};

const EMPTY_FORM = { policy_name: "", description: "", condition: "default", artifact: "" };

const INPUT_CLS = "flex h-9 w-full border border-[#1E1E22] bg-[#0A0A0B] px-3 py-1 font-mono text-sm text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50 transition-colors";
const SEARCH_INPUT = "bg-[#0A0A0B] border border-[#1E1E22] font-mono text-xs text-zinc-300 placeholder-zinc-600 px-3 py-1.5 w-64 focus:outline-none focus:border-zinc-500 transition-colors rounded-none";

export default function PoliciesPage() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const queryClient = useQueryClient();

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["policies"],
    queryFn: () => listPolicies(token!),
    enabled: !!token,
  });

  const allPolicies = data?.policies ?? [];

  const policies = useMemo(() => {
    if (!debouncedSearch) return allPolicies;
    const q = debouncedSearch.toLowerCase();
    return allPolicies.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q)
    );
  }, [allPolicies, debouncedSearch]);

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
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">POLICIES</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">{policies.length} configured</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
          <button
            onClick={() => setIsCreateOpen(true)}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-2 py-1 rounded-none transition-colors"
          >
            <Plus className="h-3 w-3" /> Create Policy
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative inline-block">
        <input
          type="text"
          placeholder="Search policies…"
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

      <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[...Array(4)].map((_, i) => <div key={i} className="h-10 animate-pulse bg-zinc-800/50 rounded-none" />)}
          </div>
        ) : policies.length === 0 ? (
          <div className="py-12 text-center">
            <Shield className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
            <p className="font-mono text-xs text-zinc-600">NO POLICIES CONFIGURED</p>
          </div>
        ) : (
          policies.map((policy) => {
            const statusKey = policy.status?.toUpperCase() ?? "DRAFT";
            const actions = NEXT_ACTIONS[statusKey] ?? [];
            return (
              <div key={policy.policy_id} className="flex items-center justify-between px-4 py-3 border-b border-[#1E1E22] last:border-0 hover:bg-[#1A1A1E] transition-colors">
                <div>
                  <p className="font-mono text-sm text-[#E4E4E7]">{policy.name}</p>
                  <p className="font-mono text-[11px] text-zinc-600 mt-0.5">{policy.description}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`font-mono text-[10px] border px-1.5 py-0.5 rounded-none ${STATUS_CLS[statusKey] ?? "border-zinc-600 text-zinc-500"}`}>
                    {statusKey}
                  </span>
                  {actions.map((action) => (
                    <button
                      key={action.value}
                      disabled={statusMutation.isPending}
                      onClick={() => statusMutation.mutate({ id: policy.policy_id, status: action.value })}
                      className="font-mono text-[10px] border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-0.5 rounded-none disabled:opacity-40 transition-colors"
                    >
                      [{action.label}]
                    </button>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Create Policy Modal */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="bg-[#111113] border border-[#1E1E22] rounded-none">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm text-[#E4E4E7] uppercase tracking-wider">Create Policy</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <FieldWrap label="Policy Name *">
              <input className={INPUT_CLS} placeholder="fraud-rules-v2"
                value={form.policy_name} onChange={(e) => setForm((f) => ({ ...f, policy_name: e.target.value }))} />
            </FieldWrap>
            <FieldWrap label="Description">
              <input className={INPUT_CLS} placeholder="Optional description"
                value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </FieldWrap>
            <FieldWrap label="Rule Condition *">
              <input className={INPUT_CLS} placeholder='hardware == "NVIDIA" or "default"'
                value={form.condition} onChange={(e) => setForm((f) => ({ ...f, condition: e.target.value }))} />
            </FieldWrap>
            <FieldWrap label="Artifact *">
              <input className={INPUT_CLS} placeholder="model_v2.pex"
                value={form.artifact} onChange={(e) => setForm((f) => ({ ...f, artifact: e.target.value }))} />
            </FieldWrap>
          </div>
          {createMutation.isError && (
            <div className="border-l-4 border-red-500 bg-red-500/5 font-mono text-xs text-red-400 px-3 py-2 mt-2">
              {(createMutation.error as Error)?.message ?? "Failed to create policy"}
            </div>
          )}
          <DialogFooter>
            <button onClick={() => setIsCreateOpen(false)} className="font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-none">
              Cancel
            </button>
            <button
              onClick={() => createMutation.mutate()}
              disabled={!form.policy_name || !form.artifact || createMutation.isPending}
              className="font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-4 py-2 rounded-none disabled:opacity-40"
            >
              {createMutation.isPending ? "CREATING…" : "CREATE"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">{label}</label>
      {children}
    </div>
  );
}
