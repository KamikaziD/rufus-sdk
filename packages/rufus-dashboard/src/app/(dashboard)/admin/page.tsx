"use client";

import { useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSystemHealth,
  listRateLimits,
  createRateLimitRule,
  updateRateLimitRule,
  listWebhooks,
  createWebhook,
  deleteWebhook,
  getWebhookDeliveries,
  testWebhook,
  type RateLimitRule,
  type Webhook,
  type WebhookDelivery,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Settings, RefreshCw, Plus, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";

type Tab = "workers" | "rate-limits" | "webhooks";

const INPUT_CLS = "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm";

function useToken() {
  const { data: session } = useSession();
  return (session as unknown as { accessToken?: string })?.accessToken;
}

export default function AdminPage() {
  const token = useToken();
  const [activeTab, setActiveTab] = useState<Tab>("workers");

  const { data: health, isLoading: healthLoading, refetch: refetchHealth } = useQuery({
    queryKey: ["system-health"],
    queryFn: () => getSystemHealth(token!),
    enabled: !!token,
    refetchInterval: 30_000,
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "workers",     label: "Workers" },
    { key: "rate-limits", label: "Rate Limits" },
    { key: "webhooks",    label: "Webhooks" },
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
        <WorkersTab health={health} isLoading={healthLoading} />
      )}
      {activeTab === "rate-limits" && <RateLimitsTab token={token} />}
      {activeTab === "webhooks" && <WebhooksTab token={token} />}
    </div>
  );
}

// ── Workers Tab ───────────────────────────────────────────────────────────────

function WorkersTab({ health, isLoading }: { health?: Record<string, unknown>; isLoading: boolean }) {
  if (isLoading) return <div className="h-32 animate-pulse bg-muted rounded-xl" />;

  const workers = (health?.workers as unknown[]) ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-sm">System Health</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-muted-foreground">Workers</p>
              <p className="font-semibold">{workers.length} registered</p>
            </div>
            <div>
              <p className="text-muted-foreground">Status</p>
              <Badge variant="success">Operational</Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {workers.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            <Settings className="h-8 w-8 mx-auto mb-3 opacity-30" />
            No workers registered
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {workers.map((worker, i) => (
            <Card key={i}>
              <CardContent className="pt-4 pb-4 text-sm">
                <pre className="font-mono text-xs text-muted-foreground">
                  {JSON.stringify(worker, null, 2)}
                </pre>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
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

// ── Shared helpers ────────────────────────────────────────────────────────────

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
