"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listWorkers,
  listRateLimits,
  createRateLimitRule,
  updateRateLimitRule,
  listWebhooks,
  createWebhook,
  deleteWebhook,
  getWebhookDeliveries,
  testWebhook,
  listWorkflowDefinitions,
  getWorkflowDefinition,
  uploadWorkflowDefinition,
  patchWorkflowDefinition,
  deleteWorkflowDefinition,
  listServerCommands,
  sendServerCommand,
  cancelServerCommand,
  pushWorkflowToDevices,
  type WorkerSummary,
  type RateLimitRule,
  type Webhook,
  type WebhookDelivery,
  type WorkflowDefinition,
  type ServerCommand,
} from "@/lib/api";
import { hasPermission } from "@/lib/roles";
import { parseUtcDate, formatDateTime } from "@/lib/utils";
import { WorkerCommandModal } from "@/components/workers/WorkerCommandModal";
import { WorkflowDAG } from "@/components/workflows/WorkflowDAG";
import { Settings, RefreshCw, Plus, ChevronDown, ChevronUp, Cpu, MapPin, Clock, Wifi, WifiOff, Radio, Upload, Send, Trash2 } from "lucide-react"; // eslint-disable-line @typescript-eslint/no-unused-vars

type Tab = "workers" | "rate-limits" | "webhooks" | "server";

const INPUT_CLS = "flex h-9 w-full border border-[#1E1E22] bg-[#0A0A0B] px-3 py-1 font-mono text-sm text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50 transition-colors";

// ── Inline Badge helpers ───────────────────────────────────────────────────────

function BadgeSuccess({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[10px] border border-emerald-500/40 text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-none">{children}</span>;
}
function BadgeSecondary({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[10px] border border-zinc-600 text-zinc-500 bg-zinc-800/50 px-1.5 py-0.5 rounded-none">{children}</span>;
}
function BadgeOutline({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={`font-mono text-[10px] border border-zinc-700 text-zinc-400 px-1.5 py-0.5 rounded-none ${className ?? ""}`}>{children}</span>;
}
function BadgeDestructive({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[10px] border border-red-500/40 text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded-none">{children}</span>;
}
function BadgeWarning({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[10px] border border-yellow-500/40 text-yellow-400 bg-yellow-500/10 px-1.5 py-0.5 rounded-none">{children}</span>;
}

// ── Inline Button helpers ─────────────────────────────────────────────────────

function BtnOutline({ children, onClick, disabled, className, type }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean; className?: string; type?: "button" | "submit" }) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors disabled:opacity-40 ${className ?? ""}`}>
      {children}
    </button>
  );
}
function BtnPrimary({ children, onClick, disabled, className, type }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean; className?: string; type?: "button" | "submit" }) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`inline-flex items-center gap-1.5 font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-2 py-1 rounded-none transition-colors disabled:opacity-40 ${className ?? ""}`}>
      {children}
    </button>
  );
}
function BtnGhost({ children, onClick, disabled, className }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean; className?: string }) {
  return (
    <button onClick={onClick} disabled={disabled} className={`inline-flex items-center gap-1.5 font-mono text-xs text-zinc-500 hover:text-zinc-200 px-2 py-1 rounded-none transition-colors disabled:opacity-40 ${className ?? ""}`}>
      {children}
    </button>
  );
}

function useToken() {
  const { data: session } = useSession();
  return (session as unknown as { accessToken?: string })?.accessToken;
}

export default function AdminPage() {
  const token = useToken();
  const { data: session } = useSession();
  const roles = (session?.user as unknown as { roles?: string[] })?.roles ?? [];
  const canManageWorkers = hasPermission(roles, "manageWorkers");
  const [activeTab, setActiveTab] = useState<Tab>("workers");

  const { data: health, isLoading: healthLoading, refetch: refetchHealth } = useQuery<{ workers: WorkerSummary[]; total: number }>({
    queryKey: ["system-health"],
    queryFn: () => listWorkers(token!, { limit: 100 }),
    enabled: !!token,
    refetchInterval: 30_000,
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "workers",     label: "Workers" },
    { key: "rate-limits", label: "Rate Limits" },
    { key: "webhooks",    label: "Webhooks" },
    { key: "server",      label: "Server" },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">ADMIN PANEL</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">System administration — SUPER_ADMIN only</p>
        </div>
        <BtnOutline onClick={() => refetchHealth()}>
          <RefreshCw className="h-3 w-3" /> Refresh
        </BtnOutline>
      </div>

      <div className="flex gap-0 border-b border-[#1E1E22] mb-4">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`font-mono text-[10px] px-4 py-2 border-b-2 transition-colors ${
              activeTab === t.key
                ? "border-amber-500 text-amber-400"
                : "border-transparent text-zinc-600 hover:text-zinc-300"
            }`}
          >
            {t.label.toUpperCase()}
          </button>
        ))}
      </div>

      {activeTab === "workers" && (
        <WorkersTab health={health} isLoading={healthLoading} canManage={canManageWorkers} />
      )}
      {activeTab === "rate-limits" && <RateLimitsTab token={token} />}
      {activeTab === "webhooks" && <WebhooksTab token={token} />}
      {activeTab === "server" && <ServerTab token={token} />}
    </div>
  );
}

// ── Workers Tab ───────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  const d = parseUtcDate(iso);
  if (!d) return "—";
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function WorkerCard({
  worker,
  onSendCommand,
}: {
  worker: WorkerSummary;
  onSendCommand: (worker: WorkerSummary) => void;
}) {
  const isOnline = worker.status === "online";
  const capabilities = Object.keys(worker.capabilities ?? {});

  return (
    <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
      <div className="flex items-start justify-between gap-4">
        {/* Left: identity */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex-shrink-0">
            {isOnline
              ? <Wifi className="h-4 w-4 text-emerald-400" />
              : <WifiOff className="h-4 w-4 text-zinc-600" />}
          </div>
          <div className="min-w-0">
            <p className="font-mono text-sm font-semibold text-[#E4E4E7] truncate">{worker.worker_id}</p>
            <p className="font-mono text-xs text-zinc-500 truncate flex items-center gap-1 mt-0.5">
              <Cpu className="h-3 w-3 flex-shrink-0" />
              {worker.hostname}
            </p>
          </div>
        </div>

        {/* Right: status badge + send command */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {isOnline ? <BadgeSuccess>{worker.status}</BadgeSuccess> : <BadgeDestructive>{worker.status}</BadgeDestructive>}
          <BtnOutline onClick={() => onSendCommand(worker)}>Send Command</BtnOutline>
        </div>
      </div>

      {/* Meta row */}
      <div className="mt-4 grid grid-cols-4 gap-3 font-mono text-xs">
        <div className="flex flex-col gap-0.5">
          <span className="text-zinc-600 flex items-center gap-1">
            <MapPin className="h-3 w-3" /> Region
          </span>
          <span className="text-zinc-300">{worker.region || "—"}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-zinc-600">Zone</span>
          <span className="text-zinc-300">{worker.zone || "—"}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-zinc-600">SDK</span>
          <span className="text-zinc-300">{worker.sdk_version ?? "—"}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-zinc-600 flex items-center gap-1">
            <Clock className="h-3 w-3" /> Heartbeat
          </span>
          <span className="text-zinc-300 tabular-nums">{timeAgo(worker.last_heartbeat)}</span>
        </div>
      </div>

      {/* Pending summary */}
      {worker.pending_command_count > 0 && (
        <div className="mt-3 flex items-center gap-3">
          <BadgeOutline>{worker.pending_command_count} pending</BadgeOutline>
        </div>
      )}

      {/* Capabilities */}
      {capabilities.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {capabilities.map((cap) => (
            <BadgeSecondary key={cap}>{cap}</BadgeSecondary>
          ))}
        </div>
      )}
    </div>
  );
}

function WorkersTab({ health, isLoading, canManage }: { health?: { workers: WorkerSummary[]; total: number }; isLoading: boolean; canManage: boolean }) {
  const [cmdModal, setCmdModal] = useState<{ open: boolean; workerId: string; hostname: string }>({
    open: false, workerId: "", hostname: "",
  });
  const [broadcastOpen, setBroadcastOpen] = useState(false);

  if (isLoading) return <div className="h-32 animate-pulse bg-[#111113] border border-[#1E1E22] rounded-none" />;

  const workers = health?.workers ?? [];
  const onlineCount = workers.filter((w) => w.status === "online").length;

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Total", value: workers.length, cls: "border-l-zinc-500" },
          { label: "Online", value: onlineCount, cls: "border-l-emerald-500" },
          { label: "Offline", value: workers.length - onlineCount, cls: "border-l-red-500" },
        ].map(({ label, value, cls }) => (
          <div key={label} className={`bg-[#111113] border border-[#1E1E22] rounded-none p-4 border-l-2 ${cls}`}>
            <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-1">{label}</div>
            <div className="font-mono text-2xl font-semibold text-[#E4E4E7]">{value}</div>
          </div>
        ))}
      </div>

      {/* Broadcast button */}
      {canManage && (
        <div className="flex justify-end">
          <BtnOutline onClick={() => setBroadcastOpen(true)}>
            <Radio className="h-3 w-3" /> Broadcast to All
          </BtnOutline>
        </div>
      )}

      {/* Worker cards */}
      {workers.length === 0 ? (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-8 text-center">
          <Settings className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
          <p className="font-mono text-xs text-zinc-600">NO WORKERS REGISTERED</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {workers.map((worker) => (
            <WorkerCard
              key={worker.worker_id}
              worker={worker}
              onSendCommand={(w) =>
                canManage && setCmdModal({ open: true, workerId: w.worker_id, hostname: w.hostname })
              }
            />
          ))}
        </div>
      )}

      <WorkerCommandModal
        open={cmdModal.open}
        onClose={() => setCmdModal((m) => ({ ...m, open: false }))}
        mode="single"
        workerId={cmdModal.workerId}
        workerHostname={cmdModal.hostname}
      />
      <WorkerCommandModal
        open={broadcastOpen}
        onClose={() => setBroadcastOpen(false)}
        mode="broadcast"
      />
    </div>
  );
}

// ── Rate Limits Tab ───────────────────────────────────────────────────────────

interface RuleDraft {
  rule_name: string;
  resource_pattern: string;
  scope: string;
  limit_per_window: string;
  window_seconds: string;
}

const EMPTY_RULE: RuleDraft = {
  rule_name: "",
  resource_pattern: "/api/v1/*",
  scope: "ip",
  limit_per_window: "100",
  window_seconds: "60",
};

function RateLimitsTab({ token }: { token: string | undefined }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<RuleDraft>(EMPTY_RULE);
  const [feedback, setFeedback] = useState<string | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["rate-limits"],
    queryFn: () => listRateLimits(token!),
    enabled: !!token,
    refetchInterval: 60_000,
  });

  const createMut = useMutation({
    mutationFn: (body: Parameters<typeof createRateLimitRule>[1]) =>
      createRateLimitRule(token!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rate-limits"] });
      setShowForm(false);
      setDraft(EMPTY_RULE);
      setFeedback("Rule created.");
    },
    onError: (e) => setFeedback(e instanceof Error ? e.message : "Failed to create."),
  });

  const updateMut = useMutation({
    mutationFn: ({ name, is_active }: { name: string; is_active: boolean }) =>
      updateRateLimitRule(token!, name, { is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rate-limits"] }),
  });

  const rules: RateLimitRule[] = data?.rules ?? [];

  function setDraftField<K extends keyof RuleDraft>(k: K, v: RuleDraft[K]) {
    setDraft((d) => ({ ...d, [k]: v }));
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    createMut.mutate({
      rule_name: draft.rule_name,
      resource_pattern: draft.resource_pattern,
      scope: draft.scope,
      limit_per_window: Number(draft.limit_per_window),
      window_seconds: Number(draft.window_seconds),
      is_active: true,
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] text-zinc-600">{rules.length} rules · {data?.total ?? 0} total</p>
        <div className="flex gap-2">
          <BtnOutline onClick={() => refetch()}>
            <RefreshCw className="h-3 w-3" />
          </BtnOutline>
          <BtnPrimary onClick={() => setShowForm((v) => !v)}>
            <Plus className="h-3 w-3" /> Add Rule
          </BtnPrimary>
        </div>
      </div>

      {feedback && (
        <div className="border-l-4 border-emerald-500 bg-emerald-500/5 font-mono text-xs text-emerald-400 px-3 py-2">
          {feedback}
        </div>
      )}

      {showForm && (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-3">New Rate Limit Rule</div>
          <form onSubmit={handleCreate} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <FieldWrap label="Rule Name *">
                <input required className={INPUT_CLS} value={draft.rule_name}
                  onChange={(e) => setDraftField("rule_name", e.target.value)} placeholder="api_requests" />
              </FieldWrap>
              <FieldWrap label="Resource Pattern *">
                <input required className={INPUT_CLS} value={draft.resource_pattern}
                  onChange={(e) => setDraftField("resource_pattern", e.target.value)} placeholder="/api/v1/*" />
              </FieldWrap>
              <FieldWrap label="Scope">
                <select className={INPUT_CLS} value={draft.scope}
                  onChange={(e) => setDraftField("scope", e.target.value)}>
                  <option value="ip">IP</option>
                  <option value="user">User</option>
                  <option value="global">Global</option>
                </select>
              </FieldWrap>
              <FieldWrap label="Limit per Window">
                <input required type="number" min={1} className={INPUT_CLS} value={draft.limit_per_window}
                  onChange={(e) => setDraftField("limit_per_window", e.target.value)} />
              </FieldWrap>
              <FieldWrap label="Window (seconds)">
                <input required type="number" min={1} className={INPUT_CLS} value={draft.window_seconds}
                  onChange={(e) => setDraftField("window_seconds", e.target.value)} />
              </FieldWrap>
            </div>
            <div className="flex gap-2 justify-end pt-1">
              <BtnOutline type="button" onClick={() => setShowForm(false)}>Cancel</BtnOutline>
              <BtnPrimary type="submit" disabled={createMut.isPending}>
                {createMut.isPending ? "Creating…" : "Create"}
              </BtnPrimary>
            </div>
          </form>
        </div>
      )}

      {isLoading ? (
        <div className="h-32 animate-pulse bg-[#111113] border border-[#1E1E22] rounded-none" />
      ) : rules.length === 0 ? (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-10 text-center">
          <p className="font-mono text-xs text-zinc-600">No rate limit rules configured</p>
        </div>
      ) : (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                {["Rule Name", "Pattern", "Scope", "Limit", "Window", "Active"].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.rule_name} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                  <td className="px-4 py-3 text-zinc-300">{r.rule_name}</td>
                  <td className="px-4 py-3 text-zinc-500">{r.resource_pattern}</td>
                  <td className="px-4 py-3 text-zinc-500">{r.scope}</td>
                  <td className="px-4 py-3 text-zinc-500">{r.limit_per_window}</td>
                  <td className="px-4 py-3 text-zinc-500">{r.window_seconds}s</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => updateMut.mutate({ name: r.rule_name, is_active: !r.is_active })}
                      disabled={updateMut.isPending}
                      className="focus:outline-none"
                      aria-label={r.is_active ? "Deactivate" : "Activate"}
                    >
                      {r.is_active ? <BadgeSuccess>Active</BadgeSuccess> : <BadgeSecondary>Inactive</BadgeSecondary>}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Webhooks Tab ──────────────────────────────────────────────────────────────

interface WebhookDraft {
  name: string;
  url: string;
  events: string;
  secret: string;
}

const EMPTY_WEBHOOK: WebhookDraft = { name: "", url: "", events: "device.online,device.offline", secret: "" };

const AVAILABLE_EVENTS = [
  "device.online", "device.offline", "device.maintenance",
  "workflow.started", "workflow.completed", "workflow.failed",
  "transaction.approved", "transaction.declined",
];

function WebhooksTab({ token }: { token: string | undefined }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<WebhookDraft>(EMPTY_WEBHOOK);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<Record<string, WebhookDelivery[]>>({});
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["webhooks"],
    queryFn: () => listWebhooks(token!),
    enabled: !!token,
    refetchInterval: 60_000,
  });

  const createMut = useMutation({
    mutationFn: (body: Parameters<typeof createWebhook>[1]) => createWebhook(token!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["webhooks"] });
      setShowForm(false);
      setDraft(EMPTY_WEBHOOK);
      setFeedback({ type: "success", msg: "Webhook registered." });
    },
    onError: (e) => setFeedback({ type: "error", msg: e instanceof Error ? e.message : "Failed." }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteWebhook(token!, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["webhooks"] }),
  });

  const testMut = useMutation({
    mutationFn: ({ url }: { url: string }) =>
      testWebhook(token!, { url, event_type: "device.online", event_data: { test: true } }),
    onSuccess: () => setFeedback({ type: "success", msg: "Test webhook sent." }),
    onError: (e) => setFeedback({ type: "error", msg: e instanceof Error ? e.message : "Test failed." }),
  });

  const webhooks: Webhook[] = data?.webhooks ?? [];

  async function toggleDeliveries(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!deliveries[id]) {
      try {
        const res = await getWebhookDeliveries(token!, id, 5);
        setDeliveries((d) => ({ ...d, [id]: res.deliveries }));
      } catch {
        setDeliveries((d) => ({ ...d, [id]: [] }));
      }
    }
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    createMut.mutate({
      name: draft.name,
      url: draft.url,
      events: draft.events.split(",").map((e) => e.trim()).filter(Boolean),
      secret: draft.secret || undefined,
    });
  }

  function setDraftField<K extends keyof WebhookDraft>(k: K, v: WebhookDraft[K]) {
    setDraft((d) => ({ ...d, [k]: v }));
  }

  function toggleEvent(event: string) {
    const current = draft.events.split(",").map((e) => e.trim()).filter(Boolean);
    const next = current.includes(event)
      ? current.filter((e) => e !== event)
      : [...current, event];
    setDraftField("events", next.join(","));
  }

  const selectedEvents = draft.events.split(",").map((e) => e.trim()).filter(Boolean);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] text-zinc-600">{webhooks.length} webhooks registered</p>
        <div className="flex gap-2">
          <BtnOutline onClick={() => refetch()}>
            <RefreshCw className="h-3 w-3" />
          </BtnOutline>
          <BtnPrimary onClick={() => setShowForm((v) => !v)}>
            <Plus className="h-3 w-3" /> Register Webhook
          </BtnPrimary>
        </div>
      </div>

      {feedback && (
        <div className={`font-mono text-xs px-3 py-2 ${
          feedback.type === "success"
            ? "border-l-4 border-emerald-500 bg-emerald-500/5 text-emerald-400"
            : "border-l-4 border-red-500 bg-red-500/5 text-red-400"
        }`}>
          {feedback.msg}
        </div>
      )}

      {showForm && (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-3">Register Webhook</div>
          <form onSubmit={handleCreate} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <FieldWrap label="Name *">
                <input required className={INPUT_CLS} value={draft.name}
                  onChange={(e) => setDraftField("name", e.target.value)} placeholder="My Webhook" />
              </FieldWrap>
              <FieldWrap label="URL *">
                <input required type="url" className={INPUT_CLS} value={draft.url}
                  onChange={(e) => setDraftField("url", e.target.value)} placeholder="https://example.com/webhook" />
              </FieldWrap>
              <FieldWrap label="Secret (optional)">
                <input className={INPUT_CLS} type="password" value={draft.secret}
                  onChange={(e) => setDraftField("secret", e.target.value)} placeholder="HMAC secret" />
              </FieldWrap>
            </div>
            <FieldWrap label="Events *">
              <div className="flex flex-wrap gap-2 pt-1">
                {AVAILABLE_EVENTS.map((ev) => (
                  <label key={ev} className="flex items-center gap-1.5 font-mono text-xs cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedEvents.includes(ev)}
                      onChange={() => toggleEvent(ev)}
                      className="h-3.5 w-3.5 rounded-none"
                    />
                    <span className="text-zinc-400">{ev}</span>
                  </label>
                ))}
              </div>
            </FieldWrap>
            <div className="flex gap-2 justify-end pt-1">
              <BtnOutline type="button" onClick={() => setShowForm(false)}>Cancel</BtnOutline>
              <BtnPrimary type="submit" disabled={createMut.isPending}>
                {createMut.isPending ? "Registering…" : "Register"}
              </BtnPrimary>
            </div>
          </form>
        </div>
      )}

      {isLoading ? (
        <div className="h-32 animate-pulse bg-[#111113] border border-[#1E1E22] rounded-none" />
      ) : webhooks.length === 0 ? (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-10 text-center">
          <p className="font-mono text-xs text-zinc-600">No webhooks registered</p>
        </div>
      ) : (
        <div className="space-y-2">
          {webhooks.map((wh) => (
            <div key={wh.webhook_id} className="bg-[#111113] border border-[#1E1E22] rounded-none">
              <div className="p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-sm font-medium text-[#E4E4E7]">{wh.name}</span>
                      {wh.is_active ? <BadgeSuccess>Active</BadgeSuccess> : <BadgeSecondary>Inactive</BadgeSecondary>}
                    </div>
                    <p className="font-mono text-xs text-zinc-500 truncate">{wh.url}</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {(Array.isArray(wh.events) ? wh.events : []).slice(0, 4).map((ev) => (
                        <BadgeOutline key={ev} className="font-mono">{ev}</BadgeOutline>
                      ))}
                      {Array.isArray(wh.events) && wh.events.length > 4 && (
                        <BadgeOutline>+{wh.events.length - 4}</BadgeOutline>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <BtnOutline onClick={() => testMut.mutate({ url: wh.url })} disabled={testMut.isPending}>
                      Test
                    </BtnOutline>
                    <BtnGhost onClick={() => toggleDeliveries(wh.webhook_id)}>
                      {expandedId === wh.webhook_id
                        ? <ChevronUp className="h-3.5 w-3.5" />
                        : <ChevronDown className="h-3.5 w-3.5" />}
                    </BtnGhost>
                    <BtnGhost
                      onClick={() => deleteMut.mutate(wh.webhook_id)}
                      disabled={deleteMut.isPending}
                      className="text-red-500 hover:text-red-400"
                    >
                      Delete
                    </BtnGhost>
                  </div>
                </div>

                {expandedId === wh.webhook_id && (
                  <div className="mt-3 border-t border-[#1E1E22] pt-3">
                    <p className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">Last 5 deliveries</p>
                    {(deliveries[wh.webhook_id] ?? []).length === 0 ? (
                      <p className="font-mono text-xs text-zinc-600">No deliveries recorded.</p>
                    ) : (
                      <div className="space-y-1">
                        {(deliveries[wh.webhook_id] ?? []).map((d) => (
                          <div key={d.delivery_id} className="flex items-center justify-between font-mono text-xs">
                            <span className="text-zinc-500">{d.event_type}</span>
                            <span className="text-zinc-600">{d.attempted_at?.slice(0, 19).replace("T", " ")}</span>
                            {d.success
                              ? <BadgeSuccess>{d.status_code ?? "OK"}</BadgeSuccess>
                              : <BadgeDestructive>{d.status_code ?? "ERR"}</BadgeDestructive>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Server Tab ────────────────────────────────────────────────────────────────

const SERVER_CMDS = ["reload_workflows", "gc_caches", "update_code", "restart"] as const;
type ServerCmdType = typeof SERVER_CMDS[number];
const SERVER_CMD_LABELS: Record<ServerCmdType, string> = {
  reload_workflows: "Reload Workflows",
  gc_caches:        "GC Caches",
  update_code:      "Update Code",
  restart:          "Restart Server",
};

function statusBadge(s: string) {
  if (s === "completed") return <BadgeSuccess>{s}</BadgeSuccess>;
  if (s === "failed")    return <BadgeDestructive>{s}</BadgeDestructive>;
  if (s === "running")   return <BadgeWarning>{s}</BadgeWarning>;
  return <BadgeSecondary>{s}</BadgeSecondary>;
}

function ServerTab({ token }: { token?: string }) {
  // ── Workflow Definitions ─────────────────────────────────────────────────
  const { data: defs = [], isLoading: defsLoading, refetch: refetchDefs } = useQuery<WorkflowDefinition[]>({
    queryKey: ["workflow-definitions"],
    queryFn: () => listWorkflowDefinitions(token!),
    enabled: !!token,
  });

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadWfType, setUploadWfType] = useState("");
  const [uploadYaml, setUploadYaml] = useState("");
  const [uploadDesc, setUploadDesc] = useState("");
  const [editingDef, setEditingDef] = useState<WorkflowDefinition | null>(null);
  const [editYaml, setEditYaml] = useState("");
  const [dagPreviewDef, setDagPreviewDef] = useState<WorkflowDefinition | null>(null);
  const [pushTarget, setPushTarget] = useState<WorkflowDefinition | null>(null);

  const uploadMut = useMutation({
    mutationFn: () =>
      uploadWorkflowDefinition(token!, {
        workflow_type: uploadWfType,
        yaml_content: uploadYaml,
        description: uploadDesc || undefined,
      }),
    onSuccess: () => {
      setUploadOpen(false);
      setUploadWfType(""); setUploadYaml(""); setUploadDesc("");
      refetchDefs();
    },
  });

  const patchMut = useMutation({
    mutationFn: (d: WorkflowDefinition) =>
      patchWorkflowDefinition(token!, d.workflow_type, editYaml),
    onSuccess: () => {
      setEditingDef(null);
      refetchDefs();
    },
  });

  const deleteMut = useMutation({
    mutationFn: (wfType: string) => deleteWorkflowDefinition(token!, wfType),
    onSuccess: () => refetchDefs(),
  });

  const pushMut = useMutation({
    mutationFn: (d: WorkflowDefinition) =>
      pushWorkflowToDevices(token!, {
        workflow_type: d.workflow_type,
        version: d.version,
        yaml_content: d.yaml_content ?? "",
      }),
    onSuccess: () => setPushTarget(null),
  });

  function startEdit(def: WorkflowDefinition) {
    getWorkflowDefinition(token!, def.workflow_type)
      .then((full) => {
        setEditingDef(full);
        setEditYaml(full.yaml_content ?? "");
      })
      .catch(() => {
        setEditingDef(def);
        setEditYaml(def.yaml_content ?? "");
      });
  }

  // ── Server Commands ──────────────────────────────────────────────────────
  const { data: srvCmds = [], refetch: refetchCmds } = useQuery<ServerCommand[]>({
    queryKey: ["server-commands"],
    queryFn: () => listServerCommands(token!),
    enabled: !!token,
    refetchInterval: 15_000,
  });

  const [sendCmdOpen, setSendCmdOpen] = useState(false);
  const [selectedCmd, setSelectedCmd] = useState<ServerCmdType>("reload_workflows");
  const [cmdPackage, setCmdPackage] = useState("");
  const [cmdVersion, setCmdVersion] = useState("");

  const sendCmdMut = useMutation({
    mutationFn: () =>
      sendServerCommand(token!, {
        command: selectedCmd,
        payload:
          selectedCmd === "update_code"
            ? { package: cmdPackage, version: cmdVersion }
            : {},
      }),
    onSuccess: () => {
      setSendCmdOpen(false);
      refetchCmds();
    },
  });

  const cancelCmdMut = useMutation({
    mutationFn: (id: string) => cancelServerCommand(token!, id),
    onSuccess: () => refetchCmds(),
  });

  return (
    <div className="space-y-6">
      {/* ── Workflow Definitions ─────────────────────────────────────────── */}
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1E1E22]">
          <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Workflow Definitions</span>
          <div className="flex gap-2">
            <BtnOutline onClick={() => refetchDefs()}>
              <RefreshCw className="h-3 w-3" />
            </BtnOutline>
            <BtnPrimary onClick={() => setUploadOpen(true)}>
              <Upload className="h-3 w-3" /> Upload
            </BtnPrimary>
          </div>
        </div>
        <div className="p-4">
          {defsLoading ? (
            <p className="font-mono text-xs text-zinc-600">Loading…</p>
          ) : defs.length === 0 ? (
            <p className="font-mono text-xs text-zinc-600">
              No DB-backed definitions yet. Upload a YAML to override disk files.
            </p>
          ) : (
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                  {["Type", "Version", "Status", "Uploaded by", "Date", ""].map((h) => (
                    <th key={h} className="text-left px-3 py-2 font-mono text-[10px] text-zinc-600 uppercase tracking-widest">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {defs.map((d) => (
                  <tr key={d.workflow_type} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                    <td className="px-3 py-2 text-zinc-300">{d.workflow_type}</td>
                    <td className="px-3 py-2 text-zinc-500">v{d.version}</td>
                    <td className="px-3 py-2">
                      {d.is_active ? <BadgeSuccess>active</BadgeSuccess> : <BadgeSecondary>inactive</BadgeSecondary>}
                    </td>
                    <td className="px-3 py-2 text-zinc-500">{d.uploaded_by ?? "—"}</td>
                    <td className="px-3 py-2 text-zinc-500">{formatDateTime(d.created_at)}</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1 justify-end">
                        <BtnGhost onClick={() => startEdit(d)}>Edit</BtnGhost>
                        <BtnGhost onClick={async () => {
                          const full = await getWorkflowDefinition(token!, d.workflow_type).catch(() => d);
                          setDagPreviewDef(full);
                        }}>DAG</BtnGhost>
                        <BtnGhost className="text-blue-400 hover:text-blue-300" onClick={() => setPushTarget(d)}>Push</BtnGhost>
                        <BtnGhost className="text-red-500 hover:text-red-400" onClick={() => deleteMut.mutate(d.workflow_type)}>
                          <Trash2 className="h-3 w-3" />
                        </BtnGhost>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Upload dialog */}
        {uploadOpen && (
          <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
            <div className="bg-[#111113] border border-[#1E1E22] rounded-none w-full max-w-2xl p-5 space-y-3">
              <h3 className="font-mono text-sm text-[#E4E4E7] uppercase tracking-wider">Upload Workflow Definition</h3>
              <input
                className={INPUT_CLS}
                placeholder="workflow_type (e.g. PaymentAuthorization)"
                value={uploadWfType}
                onChange={(e) => setUploadWfType(e.target.value)}
              />
              <input
                className={INPUT_CLS}
                placeholder="Description (optional)"
                value={uploadDesc}
                onChange={(e) => setUploadDesc(e.target.value)}
              />
              <textarea
                className="w-full font-mono text-xs border border-[#1E1E22] bg-[#0A0A0B] px-3 py-2 text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50"
                rows={14}
                placeholder="Paste YAML workflow definition here…"
                value={uploadYaml}
                onChange={(e) => setUploadYaml(e.target.value)}
              />
              <div className="flex gap-2 justify-end">
                <BtnOutline onClick={() => setUploadOpen(false)}>Cancel</BtnOutline>
                <BtnPrimary
                  disabled={!uploadWfType || !uploadYaml || uploadMut.isPending}
                  onClick={() => uploadMut.mutate()}
                >
                  Upload
                </BtnPrimary>
              </div>
            </div>
          </div>
        )}

        {/* Edit dialog */}
        {editingDef && (
          <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
            <div className="bg-[#111113] border border-[#1E1E22] rounded-none w-full max-w-4xl p-5 space-y-3 max-h-[90vh] overflow-auto">
              <div className="flex items-center justify-between">
                <h3 className="font-mono text-sm text-[#E4E4E7] uppercase tracking-wider">Edit — {editingDef.workflow_type}</h3>
                <span className="font-mono text-[10px] text-zinc-600">v{editingDef.version} → v{editingDef.version + 1}</span>
              </div>

              {/* DAG preview with editable DECISION routing */}
              <div className="border border-[#1E1E22] rounded-none overflow-hidden">
                <WorkflowDAG
                  stepsConfig={(() => {
                    try {
                      // eslint-disable-next-line @typescript-eslint/no-require-imports
                      const yaml = require("js-yaml");
                      const doc = yaml.load(editYaml) as Record<string, unknown>;
                      return (doc?.steps as Array<{ name: string; type: string }>) ?? [];
                    } catch { return []; }
                  })()}
                  currentStep={null}
                  status="RUNNING"
                  editable
                  yamlContent={editYaml}
                  onSaveYaml={(newYaml) => setEditYaml(newYaml)}
                />
              </div>
              <p className="font-mono text-[10px] text-zinc-600">
                Click a DECISION node to edit its route conditions inline.
              </p>

              <textarea
                className="w-full font-mono text-xs border border-[#1E1E22] bg-[#0A0A0B] px-3 py-2 text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50"
                rows={12}
                value={editYaml}
                onChange={(e) => setEditYaml(e.target.value)}
              />
              <div className="flex gap-2 justify-end">
                <BtnOutline onClick={() => setEditingDef(null)}>Cancel</BtnOutline>
                <BtnPrimary
                  disabled={!editYaml || patchMut.isPending}
                  onClick={() => patchMut.mutate(editingDef)}
                >
                  Save &amp; Reload Server
                </BtnPrimary>
              </div>
            </div>
          </div>
        )}

        {/* DAG preview (read-only) */}
        {dagPreviewDef && (
          <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
            <div className="bg-[#111113] border border-[#1E1E22] rounded-none w-full max-w-3xl p-5 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-mono text-sm text-[#E4E4E7] uppercase tracking-wider">DAG — {dagPreviewDef.workflow_type} v{dagPreviewDef.version}</h3>
                <BtnGhost onClick={() => setDagPreviewDef(null)}>✕</BtnGhost>
              </div>
              <WorkflowDAG
                stepsConfig={(() => {
                  try {
                    // eslint-disable-next-line @typescript-eslint/no-require-imports
                    const yaml = require("js-yaml");
                    const doc = yaml.load(dagPreviewDef.yaml_content ?? "") as Record<string, unknown>;
                    return (doc?.steps as Array<{ name: string; type: string }>) ?? [];
                  } catch { return []; }
                })()}
                currentStep={null}
                status="RUNNING"
              />
            </div>
          </div>
        )}

        {/* Push to devices confirmation */}
        {pushTarget && (
          <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
            <div className="bg-[#111113] border border-[#1E1E22] rounded-none w-96 p-5 space-y-3">
              <h3 className="font-mono text-sm text-[#E4E4E7] uppercase tracking-wider">Push to Devices</h3>
              <p className="font-mono text-xs text-zinc-500">
                Broadcast <span className="text-zinc-300">{pushTarget.workflow_type}</span> v{pushTarget.version}
                {" "}to all registered edge devices via{" "}
                <span className="text-zinc-300">update_workflow</span> command.
              </p>
              <p className="font-mono text-[10px] text-zinc-600">
                Devices pick it up within 30–60 s on their next heartbeat poll.
              </p>
              <div className="flex gap-2 justify-end">
                <BtnOutline onClick={() => setPushTarget(null)}>Cancel</BtnOutline>
                <BtnPrimary
                  disabled={pushMut.isPending}
                  onClick={() => pushMut.mutate(pushTarget)}
                >
                  <Send className="h-3 w-3" /> Push to All Devices
                </BtnPrimary>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Server Commands ──────────────────────────────────────────────── */}
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#1E1E22]">
          <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Server Commands</span>
          <div className="flex gap-2">
            <BtnOutline onClick={() => refetchCmds()}>
              <RefreshCw className="h-3 w-3" />
            </BtnOutline>
            <BtnPrimary onClick={() => setSendCmdOpen(true)}>
              <Send className="h-3 w-3" /> Send Command
            </BtnPrimary>
          </div>
        </div>
        <div className="p-4 space-y-2">
          {srvCmds.length === 0 ? (
            <p className="font-mono text-xs text-zinc-600">No server commands yet.</p>
          ) : (
            <table className="w-full font-mono text-xs">
              <thead>
                <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                  {["Command", "Status", "By", "When", ""].map((h) => (
                    <th key={h} className="text-left px-3 py-2 font-mono text-[10px] text-zinc-600 uppercase tracking-widest">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {srvCmds.map((c) => (
                  <tr key={c.id} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                    <td className="px-3 py-2 text-zinc-300">{c.command}</td>
                    <td className="px-3 py-2">{statusBadge(c.status)}</td>
                    <td className="px-3 py-2 text-zinc-500">{c.created_by ?? "—"}</td>
                    <td className="px-3 py-2 text-zinc-500">{formatDateTime(c.created_at)}</td>
                    <td className="px-3 py-2">
                      {c.status === "pending" && (
                        <BtnGhost
                          className="text-red-500 hover:text-red-400"
                          onClick={() => cancelCmdMut.mutate(c.id)}
                        >
                          Cancel
                        </BtnGhost>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Send command dialog */}
          {sendCmdOpen && (
            <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
              <div className="bg-[#111113] border border-[#1E1E22] rounded-none w-96 p-5 space-y-3">
                <h3 className="font-mono text-sm text-[#E4E4E7] uppercase tracking-wider">Send Server Command</h3>
                <div className="space-y-1">
                  <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Command</label>
                  <select
                    className={INPUT_CLS}
                    value={selectedCmd}
                    onChange={(e) => setSelectedCmd(e.target.value as ServerCmdType)}
                  >
                    {SERVER_CMDS.map((c) => (
                      <option key={c} value={c}>{SERVER_CMD_LABELS[c]}</option>
                    ))}
                  </select>
                </div>
                {selectedCmd === "update_code" && (
                  <>
                    <input
                      className={INPUT_CLS}
                      placeholder="package (e.g. rufus-sdk)"
                      value={cmdPackage}
                      onChange={(e) => setCmdPackage(e.target.value)}
                    />
                    <input
                      className={INPUT_CLS}
                      placeholder="version (e.g. 1.0.0rc3, leave blank for latest)"
                      value={cmdVersion}
                      onChange={(e) => setCmdVersion(e.target.value)}
                    />
                  </>
                )}
                <div className="font-mono text-[10px] text-zinc-600 border border-[#1E1E22] bg-[#0A0A0B] p-2 rounded-none">
                  {selectedCmd === "reload_workflows" && "Force-reload all active workflow definitions from DB immediately."}
                  {selectedCmd === "gc_caches" && "Clear WorkflowBuilder import + config caches. Safe — next request rebuilds them."}
                  {selectedCmd === "update_code" && "pip install the package then SIGTERM. Supervisor/k8s restarts the server."}
                  {selectedCmd === "restart" && "Graceful SIGTERM. Supervisor/k8s restart policy brings the server back."}
                </div>
                <div className="flex gap-2 justify-end">
                  <BtnOutline onClick={() => setSendCmdOpen(false)}>Cancel</BtnOutline>
                  <BtnPrimary
                    disabled={sendCmdMut.isPending}
                    onClick={() => sendCmdMut.mutate()}
                  >
                    Send
                  </BtnPrimary>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">{label}</label>
      {children}
    </div>
  );
}
