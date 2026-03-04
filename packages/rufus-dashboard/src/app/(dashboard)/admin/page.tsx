"use client";

import { useState, useCallback } from "react";
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
import { WorkerCommandModal } from "@/components/workers/WorkerCommandModal";
import { WorkflowDAG } from "@/components/workflows/WorkflowDAG";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Settings, RefreshCw, Plus, ChevronDown, ChevronUp, Cpu, MapPin, Clock, Wifi, WifiOff, Radio, Upload, Send, Trash2, History } from "lucide-react";
import { Button } from "@/components/ui/button";

type Tab = "workers" | "rate-limits" | "webhooks" | "server";

const INPUT_CLS = "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm";

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

  function handleRefresh() {
    refetchHealth();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Admin Panel</h1>
          <p className="text-muted-foreground">System administration — SUPER_ADMIN only</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleRefresh}>
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      <div className="flex gap-1 border-b mb-4">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
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
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
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
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-start justify-between gap-4">
          {/* Left: identity */}
          <div className="flex items-center gap-3 min-w-0">
            <div className={`flex-shrink-0 rounded-lg p-2 ${isOnline ? "bg-green-50" : "bg-muted"}`}>
              {isOnline
                ? <Wifi className="h-4 w-4 text-green-600" />
                : <WifiOff className="h-4 w-4 text-muted-foreground" />}
            </div>
            <div className="min-w-0">
              <p className="font-mono text-sm font-semibold truncate">{worker.worker_id}</p>
              <p className="text-xs text-muted-foreground truncate flex items-center gap-1 mt-0.5">
                <Cpu className="h-3 w-3 flex-shrink-0" />
                {worker.hostname}
              </p>
            </div>
          </div>

          {/* Right: status badge + send command */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <Badge variant={isOnline ? "success" : "destructive"}>
              {worker.status}
            </Badge>
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              onClick={() => onSendCommand(worker)}
            >
              Send Command
            </Button>
          </div>
        </div>

        {/* Meta row */}
        <div className="mt-4 grid grid-cols-4 gap-3 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground flex items-center gap-1">
              <MapPin className="h-3 w-3" /> Region
            </span>
            <span className="font-medium">{worker.region || "—"}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground">Zone</span>
            <span className="font-medium">{worker.zone || "—"}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground">SDK</span>
            <span className="font-mono font-medium">{worker.sdk_version ?? "—"}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" /> Heartbeat
            </span>
            <span className="font-medium tabular-nums">{timeAgo(worker.last_heartbeat)}</span>
          </div>
        </div>

        {/* SDK + pending summary */}
        <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
          {worker.pending_command_count > 0 && (
            <Badge variant="outline" className="text-xs">
              {worker.pending_command_count} pending
            </Badge>
          )}
        </div>

        {/* Capabilities */}
        {capabilities.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {capabilities.map((cap) => (
              <Badge key={cap} variant="secondary" className="text-xs">{cap}</Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function WorkersTab({ health, isLoading, canManage }: { health?: { workers: WorkerSummary[]; total: number }; isLoading: boolean; canManage: boolean }) {

  const [cmdModal, setCmdModal] = useState<{ open: boolean; workerId: string; hostname: string }>({
    open: false, workerId: "", hostname: "",
  });
  const [broadcastOpen, setBroadcastOpen] = useState(false);

  if (isLoading) return <div className="h-32 animate-pulse bg-muted rounded-xl" />;

  const workers = health?.workers ?? [];
  const onlineCount = workers.filter((w) => w.status === "online").length;

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <CardContent className="py-4 flex items-center gap-3">
            <div className="rounded-md bg-primary/10 p-2">
              <Cpu className="h-4 w-4 text-primary" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Total</p>
              <p className="text-lg font-bold leading-none">{workers.length}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-3">
            <div className="rounded-md bg-green-100 p-2">
              <Wifi className="h-4 w-4 text-green-600" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Online</p>
              <p className="text-lg font-bold leading-none text-green-600">{onlineCount}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-3">
            <div className="rounded-md bg-muted p-2">
              <WifiOff className="h-4 w-4 text-muted-foreground" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Offline</p>
              <p className="text-lg font-bold leading-none">{workers.length - onlineCount}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Broadcast button */}
      {canManage && (
        <div className="flex justify-end">
          <Button variant="outline" size="sm" onClick={() => setBroadcastOpen(true)}>
            <Radio className="h-3.5 w-3.5" />
            Broadcast to All
          </Button>
        </div>
      )}

      {/* Worker cards */}
      {workers.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            <Settings className="h-8 w-8 mx-auto mb-3 opacity-30" />
            No workers registered
          </CardContent>
        </Card>
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

      {/* Command modal (single worker) */}
      <WorkerCommandModal
        open={cmdModal.open}
        onClose={() => setCmdModal((m) => ({ ...m, open: false }))}
        mode="single"
        workerId={cmdModal.workerId}
        workerHostname={cmdModal.hostname}
      />

      {/* Broadcast modal */}
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
        <p className="text-sm text-muted-foreground">{rules.length} rules · {data?.total ?? 0} total</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" onClick={() => setShowForm((v) => !v)}>
            <Plus className="h-3.5 w-3.5" />
            Add Rule
          </Button>
        </div>
      </div>

      {feedback && (
        <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded px-3 py-2">{feedback}</p>
      )}

      {showForm && (
        <Card>
          <CardHeader><CardTitle className="text-sm">New Rate Limit Rule</CardTitle></CardHeader>
          <CardContent>
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
                <Button type="button" variant="outline" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
                <Button type="submit" size="sm" disabled={createMut.isPending}>
                  {createMut.isPending ? "Creating…" : "Create"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="h-32 animate-pulse bg-muted rounded-xl" />
      ) : rules.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No rate limit rules configured
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="text-left px-4 py-3 font-medium">Rule Name</th>
                  <th className="text-left px-4 py-3 font-medium">Pattern</th>
                  <th className="text-left px-4 py-3 font-medium">Scope</th>
                  <th className="text-left px-4 py-3 font-medium">Limit</th>
                  <th className="text-left px-4 py-3 font-medium">Window</th>
                  <th className="text-left px-4 py-3 font-medium">Active</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.rule_name} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="px-4 py-3 font-mono text-xs">{r.rule_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{r.resource_pattern}</td>
                    <td className="px-4 py-3 text-xs">{r.scope}</td>
                    <td className="px-4 py-3 text-xs">{r.limit_per_window}</td>
                    <td className="px-4 py-3 text-xs">{r.window_seconds}s</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => updateMut.mutate({ name: r.rule_name, is_active: !r.is_active })}
                        disabled={updateMut.isPending}
                        className="focus:outline-none"
                        aria-label={r.is_active ? "Deactivate" : "Activate"}
                      >
                        <Badge variant={r.is_active ? "success" : "secondary"}>
                          {r.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
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
        <p className="text-sm text-muted-foreground">{webhooks.length} webhooks registered</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" onClick={() => setShowForm((v) => !v)}>
            <Plus className="h-3.5 w-3.5" />
            Register Webhook
          </Button>
        </div>
      </div>

      {feedback && (
        <p className={`text-sm rounded px-3 py-2 border ${
          feedback.type === "success"
            ? "text-green-700 bg-green-50 border-green-200"
            : "text-red-700 bg-red-50 border-red-200"
        }`}>{feedback.msg}</p>
      )}

      {showForm && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Register Webhook</CardTitle></CardHeader>
          <CardContent>
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
                    <label key={ev} className="flex items-center gap-1.5 text-xs cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedEvents.includes(ev)}
                        onChange={() => toggleEvent(ev)}
                        className="h-3.5 w-3.5 rounded"
                      />
                      <span className="font-mono">{ev}</span>
                    </label>
                  ))}
                </div>
              </FieldWrap>
              <div className="flex gap-2 justify-end pt-1">
                <Button type="button" variant="outline" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
                <Button type="submit" size="sm" disabled={createMut.isPending}>
                  {createMut.isPending ? "Registering…" : "Register"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="h-32 animate-pulse bg-muted rounded-xl" />
      ) : webhooks.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No webhooks registered
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {webhooks.map((wh) => (
            <Card key={wh.webhook_id}>
              <CardContent className="pt-4 pb-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-sm">{wh.name}</span>
                      <Badge variant={wh.is_active ? "success" : "secondary"}>
                        {wh.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </div>
                    <p className="font-mono text-xs text-muted-foreground truncate">{wh.url}</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {wh.events.slice(0, 4).map((ev) => (
                        <Badge key={ev} variant="outline" className="text-xs font-mono">{ev}</Badge>
                      ))}
                      {wh.events.length > 4 && (
                        <Badge variant="outline" className="text-xs">+{wh.events.length - 4}</Badge>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <Button
                      size="sm" variant="outline"
                      className="h-7 px-2 text-xs"
                      onClick={() => testMut.mutate({ url: wh.url })}
                      disabled={testMut.isPending}
                    >
                      Test
                    </Button>
                    <Button
                      size="sm" variant="ghost"
                      className="h-7 px-2 text-xs"
                      onClick={() => toggleDeliveries(wh.webhook_id)}
                    >
                      {expandedId === wh.webhook_id
                        ? <ChevronUp className="h-3.5 w-3.5" />
                        : <ChevronDown className="h-3.5 w-3.5" />}
                    </Button>
                    <Button
                      size="sm" variant="ghost"
                      className="h-7 px-2 text-xs text-destructive hover:text-destructive"
                      onClick={() => deleteMut.mutate(wh.webhook_id)}
                      disabled={deleteMut.isPending}
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {expandedId === wh.webhook_id && (
                  <div className="mt-3 border-t pt-3">
                    <p className="text-xs font-medium text-muted-foreground mb-2">Last 5 deliveries</p>
                    {(deliveries[wh.webhook_id] ?? []).length === 0 ? (
                      <p className="text-xs text-muted-foreground">No deliveries recorded.</p>
                    ) : (
                      <div className="space-y-1">
                        {(deliveries[wh.webhook_id] ?? []).map((d) => (
                          <div key={d.delivery_id} className="flex items-center justify-between text-xs">
                            <span className="font-mono text-muted-foreground">{d.event_type}</span>
                            <span className="text-muted-foreground">{d.attempted_at?.slice(0, 19).replace("T", " ")}</span>
                            <Badge variant={d.success ? "success" : "destructive"}>
                              {d.status_code ?? (d.success ? "OK" : "ERR")}
                            </Badge>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
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

function ServerTab({ token }: { token?: string }) {
  const qc = useQueryClient();

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

  function handleDagSave(newYaml: string) {
    if (!editingDef) return;
    setEditYaml(newYaml);
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

  const statusColor = (s: string) =>
    s === "completed" ? "success" : s === "failed" ? "destructive" : s === "running" ? "warning" : "secondary";

  return (
    <div className="space-y-6">
      {/* ── Workflow Definitions ─────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-base">Workflow Definitions</CardTitle>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => refetchDefs()}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
            <Button size="sm" onClick={() => setUploadOpen(true)}>
              <Upload className="h-3.5 w-3.5 mr-1" /> Upload
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {defsLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : defs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No DB-backed definitions yet. Upload a YAML to override disk files.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="text-left py-1.5 font-medium">Type</th>
                  <th className="text-left py-1.5 font-medium">Version</th>
                  <th className="text-left py-1.5 font-medium">Status</th>
                  <th className="text-left py-1.5 font-medium">Uploaded by</th>
                  <th className="text-left py-1.5 font-medium">Date</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {defs.map((d) => (
                  <tr key={d.workflow_type} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="py-2 font-mono text-xs">{d.workflow_type}</td>
                    <td className="py-2 text-xs">v{d.version}</td>
                    <td className="py-2">
                      <Badge variant={d.is_active ? "success" : "secondary"} className="text-xs">
                        {d.is_active ? "active" : "inactive"}
                      </Badge>
                    </td>
                    <td className="py-2 text-xs text-muted-foreground">{d.uploaded_by ?? "—"}</td>
                    <td className="py-2 text-xs text-muted-foreground">
                      {d.created_at ? new Date(d.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="py-2">
                      <div className="flex gap-1 justify-end">
                        <Button
                          size="sm" variant="ghost"
                          className="h-6 px-2 text-xs"
                          onClick={() => startEdit(d)}
                        >
                          Edit
                        </Button>
                        <Button
                          size="sm" variant="ghost"
                          className="h-6 px-2 text-xs"
                          onClick={async () => {
                            const full = await getWorkflowDefinition(token!, d.workflow_type).catch(() => d);
                            setDagPreviewDef(full);
                          }}
                        >
                          DAG
                        </Button>
                        <Button
                          size="sm" variant="ghost"
                          className="h-6 px-2 text-xs text-blue-600"
                          onClick={() => setPushTarget(d)}
                        >
                          Push
                        </Button>
                        <Button
                          size="sm" variant="ghost"
                          className="h-6 px-2 text-xs text-destructive"
                          onClick={() => deleteMut.mutate(d.workflow_type)}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Upload dialog */}
          {uploadOpen && (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
              <div className="bg-background rounded-lg shadow-xl w-full max-w-2xl p-5 space-y-3">
                <h3 className="text-base font-semibold">Upload Workflow Definition</h3>
                <input
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                  placeholder="workflow_type (e.g. PaymentAuthorization)"
                  value={uploadWfType}
                  onChange={(e) => setUploadWfType(e.target.value)}
                />
                <input
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                  placeholder="Description (optional)"
                  value={uploadDesc}
                  onChange={(e) => setUploadDesc(e.target.value)}
                />
                <textarea
                  className="w-full font-mono text-xs border rounded px-3 py-2 bg-muted/30"
                  rows={14}
                  placeholder="Paste YAML workflow definition here…"
                  value={uploadYaml}
                  onChange={(e) => setUploadYaml(e.target.value)}
                />
                <div className="flex gap-2 justify-end">
                  <Button variant="outline" size="sm" onClick={() => setUploadOpen(false)}>Cancel</Button>
                  <Button
                    size="sm"
                    disabled={!uploadWfType || !uploadYaml || uploadMut.isPending}
                    onClick={() => uploadMut.mutate()}
                  >
                    Upload
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Edit dialog */}
          {editingDef && (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
              <div className="bg-background rounded-lg shadow-xl w-full max-w-4xl p-5 space-y-3 max-h-[90vh] overflow-auto">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold">Edit — {editingDef.workflow_type}</h3>
                  <span className="text-xs text-muted-foreground">v{editingDef.version} → v{editingDef.version + 1}</span>
                </div>

                {/* DAG preview with editable DECISION routing */}
                <div className="border rounded-lg overflow-hidden">
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
                    onSaveYaml={(newYaml) => {
                      setEditYaml(newYaml);
                    }}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  Click a DECISION node to edit its route conditions inline.
                </p>

                <textarea
                  className="w-full font-mono text-xs border rounded px-3 py-2 bg-muted/30"
                  rows={12}
                  value={editYaml}
                  onChange={(e) => setEditYaml(e.target.value)}
                />
                <div className="flex gap-2 justify-end">
                  <Button variant="outline" size="sm" onClick={() => setEditingDef(null)}>Cancel</Button>
                  <Button
                    size="sm"
                    disabled={!editYaml || patchMut.isPending}
                    onClick={() => patchMut.mutate(editingDef)}
                  >
                    Save &amp; Reload Server
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* DAG preview (read-only) */}
          {dagPreviewDef && (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
              <div className="bg-background rounded-lg shadow-xl w-full max-w-3xl p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold">DAG — {dagPreviewDef.workflow_type} v{dagPreviewDef.version}</h3>
                  <Button variant="ghost" size="sm" onClick={() => setDagPreviewDef(null)}>✕</Button>
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
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
              <div className="bg-background rounded-lg shadow-xl w-96 p-5 space-y-3">
                <h3 className="text-base font-semibold">Push to Devices</h3>
                <p className="text-sm text-muted-foreground">
                  Broadcast <span className="font-mono font-medium">{pushTarget.workflow_type}</span> v{pushTarget.version}
                  {" "}to all registered edge devices via{" "}
                  <span className="font-mono">update_workflow</span> command.
                </p>
                <p className="text-xs text-muted-foreground">
                  Devices pick it up within 30–60 s on their next heartbeat poll.
                </p>
                <div className="flex gap-2 justify-end">
                  <Button variant="outline" size="sm" onClick={() => setPushTarget(null)}>Cancel</Button>
                  <Button
                    size="sm"
                    disabled={pushMut.isPending}
                    onClick={() => pushMut.mutate(pushTarget)}
                  >
                    <Send className="h-3.5 w-3.5 mr-1" /> Push to All Devices
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Server Commands ──────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-base">Server Commands</CardTitle>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => refetchCmds()}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
            <Button size="sm" onClick={() => setSendCmdOpen(true)}>
              <Send className="h-3.5 w-3.5 mr-1" /> Send Command
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {srvCmds.length === 0 ? (
            <p className="text-sm text-muted-foreground">No server commands yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="text-left py-1.5 font-medium">Command</th>
                  <th className="text-left py-1.5 font-medium">Status</th>
                  <th className="text-left py-1.5 font-medium">By</th>
                  <th className="text-left py-1.5 font-medium">When</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {srvCmds.map((c) => (
                  <tr key={c.id} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="py-2 font-mono text-xs">{c.command}</td>
                    <td className="py-2">
                      <Badge variant={statusColor(c.status) as "success" | "destructive" | "warning" | "secondary"} className="text-xs">
                        {c.status}
                      </Badge>
                    </td>
                    <td className="py-2 text-xs text-muted-foreground">{c.created_by ?? "—"}</td>
                    <td className="py-2 text-xs text-muted-foreground">
                      {c.created_at ? new Date(c.created_at).toLocaleTimeString() : "—"}
                    </td>
                    <td className="py-2">
                      {c.status === "pending" && (
                        <Button
                          size="sm" variant="ghost"
                          className="h-6 px-2 text-xs text-destructive"
                          onClick={() => cancelCmdMut.mutate(c.id)}
                        >
                          Cancel
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Send command dialog */}
          {sendCmdOpen && (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
              <div className="bg-background rounded-lg shadow-xl w-96 p-5 space-y-3">
                <h3 className="text-base font-semibold">Send Server Command</h3>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">Command</label>
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
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
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                      placeholder="package (e.g. rufus-sdk)"
                      value={cmdPackage}
                      onChange={(e) => setCmdPackage(e.target.value)}
                    />
                    <input
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                      placeholder="version (e.g. 0.8.0, leave blank for latest)"
                      value={cmdVersion}
                      onChange={(e) => setCmdVersion(e.target.value)}
                    />
                  </>
                )}
                <div className="text-xs text-muted-foreground bg-muted/40 rounded p-2">
                  {selectedCmd === "reload_workflows" && "Force-reload all active workflow definitions from DB immediately."}
                  {selectedCmd === "gc_caches" && "Clear WorkflowBuilder import + config caches. Safe — next request rebuilds them."}
                  {selectedCmd === "update_code" && "pip install the package then SIGTERM. Supervisor/k8s restarts the server."}
                  {selectedCmd === "restart" && "Graceful SIGTERM. Supervisor/k8s restart policy brings the server back."}
                </div>
                <div className="flex gap-2 justify-end">
                  <Button variant="outline" size="sm" onClick={() => setSendCmdOpen(false)}>Cancel</Button>
                  <Button
                    size="sm"
                    disabled={sendCmdMut.isPending}
                    onClick={() => sendCmdMut.mutate()}
                  >
                    Send
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
