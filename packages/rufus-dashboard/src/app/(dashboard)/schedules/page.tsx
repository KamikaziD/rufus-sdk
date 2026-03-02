"use client";

import { useState } from "react";
import { useSchedules, useCreateSchedule, usePauseSchedule, useResumeSchedule, useCancelSchedule } from "@/lib/hooks/useSchedules";
import { RoleGate } from "@/components/shared/RoleGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRelativeTime } from "@/lib/utils";
import { Clock, Plus, RefreshCw, Pause, Play, X } from "lucide-react";
import type { Schedule } from "@/lib/api";

type ScheduleStatus = Schedule["status"];

const STATUS_VARIANTS: Record<ScheduleStatus, "success" | "warning" | "secondary" | "destructive" | "info"> = {
  active:    "success",
  paused:    "warning",
  pending:   "info",
  completed: "secondary",
  cancelled: "secondary",
  failed:    "destructive",
};

function ScheduleStatusBadge({ status }: { status: ScheduleStatus }) {
  return (
    <Badge variant={STATUS_VARIANTS[status] ?? "secondary"}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}

interface CreateFormState {
  schedule_name: string;
  command_type: string;
  schedule_type: "one_time" | "recurring";
  device_id: string;
  cron_expression: string;
  execute_at: string;
  max_executions: string;
}

const EMPTY_FORM: CreateFormState = {
  schedule_name: "",
  command_type: "",
  schedule_type: "recurring",
  device_id: "",
  cron_expression: "0 2 * * *",
  execute_at: "",
  max_executions: "",
};

export default function SchedulesPage() {
  const { data, isLoading, refetch } = useSchedules();
  const createSchedule = useCreateSchedule();
  const pauseSchedule = usePauseSchedule();
  const resumeSchedule = useResumeSchedule();
  const cancelSchedule = useCancelSchedule();

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreateFormState>(EMPTY_FORM);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const schedules = data?.schedules ?? [];

  function setField<K extends keyof CreateFormState>(key: K, value: CreateFormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFeedback(null);
    try {
      await createSchedule.mutateAsync({
        schedule_name: form.schedule_name,
        command_type: form.command_type,
        schedule_type: form.schedule_type,
        device_id: form.device_id || undefined,
        cron_expression: form.schedule_type === "recurring" ? form.cron_expression : undefined,
        execute_at: form.schedule_type === "one_time" ? form.execute_at : undefined,
        max_executions: form.max_executions ? Number(form.max_executions) : undefined,
      });
      setFeedback({ type: "success", msg: "Schedule created." });
      setForm(EMPTY_FORM);
      setShowForm(false);
    } catch (err) {
      setFeedback({ type: "error", msg: err instanceof Error ? err.message : "Failed to create schedule." });
    }
  }

  async function handleAction(action: "pause" | "resume" | "cancel", id: string) {
    setFeedback(null);
    try {
      if (action === "pause")  await pauseSchedule.mutateAsync(id);
      if (action === "resume") await resumeSchedule.mutateAsync(id);
      if (action === "cancel") await cancelSchedule.mutateAsync(id);
    } catch (err) {
      setFeedback({ type: "error", msg: err instanceof Error ? err.message : `Failed to ${action} schedule.` });
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Schedules</h1>
          <p className="text-muted-foreground">
            {schedules.filter((s) => s.status === "active").length} active ·{" "}
            {data?.count ?? 0} total
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <RoleGate permission="manageSchedules">
            <Button size="sm" onClick={() => setShowForm((v) => !v)}>
              <Plus className="h-3.5 w-3.5" />
              Create Schedule
            </Button>
          </RoleGate>
        </div>
      </div>

      {/* Feedback */}
      {feedback && (
        <div
          className={`px-4 py-2 rounded-md text-sm ${
            feedback.type === "success"
              ? "bg-green-50 text-green-800 border border-green-200"
              : "bg-red-50 text-red-800 border border-red-200"
          }`}
        >
          {feedback.msg}
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">New Schedule</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <LabeledField label="Schedule Name *">
                  <input
                    required
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    placeholder="Daily health check"
                    value={form.schedule_name}
                    onChange={(e) => setField("schedule_name", e.target.value)}
                  />
                </LabeledField>
                <LabeledField label="Command Type *">
                  <input
                    required
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    placeholder="health_check"
                    value={form.command_type}
                    onChange={(e) => setField("command_type", e.target.value)}
                  />
                </LabeledField>
                <LabeledField label="Device ID (leave blank for fleet)">
                  <input
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    placeholder="device-id or leave blank"
                    value={form.device_id}
                    onChange={(e) => setField("device_id", e.target.value)}
                  />
                </LabeledField>
                <LabeledField label="Schedule Type *">
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    value={form.schedule_type}
                    onChange={(e) => setField("schedule_type", e.target.value as "one_time" | "recurring")}
                  >
                    <option value="recurring">Recurring (cron)</option>
                    <option value="one_time">One-time</option>
                  </select>
                </LabeledField>
                {form.schedule_type === "recurring" ? (
                  <LabeledField label="Cron Expression">
                    <input
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm font-mono"
                      placeholder="0 2 * * *"
                      value={form.cron_expression}
                      onChange={(e) => setField("cron_expression", e.target.value)}
                    />
                  </LabeledField>
                ) : (
                  <LabeledField label="Execute At (ISO 8601)">
                    <input
                      className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                      placeholder="2026-03-01T02:00:00Z"
                      value={form.execute_at}
                      onChange={(e) => setField("execute_at", e.target.value)}
                    />
                  </LabeledField>
                )}
                <LabeledField label="Max Executions (blank = unlimited)">
                  <input
                    type="number"
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    min={1}
                    placeholder="52"
                    value={form.max_executions}
                    onChange={(e) => setField("max_executions", e.target.value)}
                  />
                </LabeledField>
              </div>
              <div className="flex gap-2 justify-end pt-2">
                <Button type="button" variant="outline" size="sm" onClick={() => { setShowForm(false); setForm(EMPTY_FORM); }}>
                  Cancel
                </Button>
                <Button type="submit" size="sm" disabled={createSchedule.isPending}>
                  {createSchedule.isPending ? "Creating…" : "Create"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Schedule table */}
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-12 animate-pulse bg-muted rounded-lg" />
          ))}
        </div>
      ) : schedules.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Clock className="h-8 w-8 mx-auto mb-3 opacity-30" />
            No schedules found
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="text-left px-4 py-3 font-medium">Name</th>
                    <th className="text-left px-4 py-3 font-medium">Command</th>
                    <th className="text-left px-4 py-3 font-medium">Device</th>
                    <th className="text-left px-4 py-3 font-medium">Cron</th>
                    <th className="text-left px-4 py-3 font-medium">Status</th>
                    <th className="text-left px-4 py-3 font-medium">Next Run</th>
                    <th className="text-left px-4 py-3 font-medium">Created</th>
                    <th className="text-left px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {schedules.map((s) => (
                    <tr key={s.schedule_id} className="border-b last:border-0 hover:bg-muted/40">
                      <td className="px-4 py-3 font-medium">{s.schedule_name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{s.command_type}</td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {s.device_id ? s.device_id.slice(0, 12) + "…" : <span className="text-muted-foreground">fleet</span>}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {s.cron_expression ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <ScheduleStatusBadge status={s.status} />
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {s.next_execution_at ? formatRelativeTime(s.next_execution_at) : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {formatRelativeTime(s.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <RoleGate permission="manageSchedules">
                          <div className="flex gap-1">
                            {s.status === "active" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2 text-xs"
                                onClick={() => handleAction("pause", s.schedule_id)}
                              >
                                <Pause className="h-3 w-3" />
                              </Button>
                            )}
                            {s.status === "paused" && (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2 text-xs"
                                onClick={() => handleAction("resume", s.schedule_id)}
                              >
                                <Play className="h-3 w-3" />
                              </Button>
                            )}
                            {(s.status === "active" || s.status === "paused" || s.status === "pending") && (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2 text-xs text-destructive hover:text-destructive"
                                onClick={() => handleAction("cancel", s.schedule_id)}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            )}
                          </div>
                        </RoleGate>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
