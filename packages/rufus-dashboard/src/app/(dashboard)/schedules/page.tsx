"use client";

import { useState } from "react";
import { useSchedules, useCreateSchedule, usePauseSchedule, useResumeSchedule, useCancelSchedule } from "@/lib/hooks/useSchedules";
import { RoleGate } from "@/components/shared/RoleGate";
import { formatRelativeTime } from "@/lib/utils";
import { Clock, Plus, RefreshCw, Pause, Play, X } from "lucide-react";
import type { Schedule } from "@/lib/api";

type ScheduleStatus = Schedule["status"];

const STATUS_CLS: Record<ScheduleStatus, string> = {
  active:    "border-emerald-500/40 text-emerald-400 bg-emerald-500/10",
  paused:    "border-yellow-500/40 text-yellow-400 bg-yellow-500/10",
  pending:   "border-blue-500/40 text-blue-400 bg-blue-500/10",
  completed: "border-zinc-600 text-zinc-500 bg-zinc-800/50",
  cancelled: "border-zinc-600 text-zinc-500 bg-zinc-800/50",
  failed:    "border-red-500/40 text-red-400 bg-red-500/10",
};

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

const INPUT_CLS = "flex h-9 w-full border border-[#1E1E22] bg-[#0A0A0B] px-3 py-1 font-mono text-sm text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50 transition-colors";

function isImminent(ts: string | undefined | null): boolean {
  if (!ts) return false;
  return (new Date(ts).getTime() - Date.now()) < 60 * 60 * 1000;
}

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
      setFeedback({ type: "error", msg: err instanceof Error ? err.message : "Failed." });
    }
  }

  async function handleAction(action: "pause" | "resume" | "cancel", id: string) {
    setFeedback(null);
    try {
      if (action === "pause")  await pauseSchedule.mutateAsync(id);
      if (action === "resume") await resumeSchedule.mutateAsync(id);
      if (action === "cancel") await cancelSchedule.mutateAsync(id);
    } catch (err) {
      setFeedback({ type: "error", msg: err instanceof Error ? err.message : `Failed to ${action}.` });
    }
  }

  const activeCount = schedules.filter((s) => s.status === "active").length;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">SCHEDULES</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">
            {activeCount} active · {data?.count ?? 0} total
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
          <RoleGate permission="manageSchedules">
            <button
              onClick={() => setShowForm((v) => !v)}
              className="inline-flex items-center gap-1.5 font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-2 py-1 rounded-none transition-colors"
            >
              <Plus className="h-3 w-3" /> Create Schedule
            </button>
          </RoleGate>
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

      {/* Create form */}
      {showForm && (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-4">NEW SCHEDULE</div>
          <form onSubmit={handleCreate} className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <FieldWrap label="Schedule Name *">
                <input required className={INPUT_CLS} placeholder="Daily health check"
                  value={form.schedule_name} onChange={(e) => setField("schedule_name", e.target.value)} />
              </FieldWrap>
              <FieldWrap label="Command Type *">
                <input required className={INPUT_CLS} placeholder="health_check"
                  value={form.command_type} onChange={(e) => setField("command_type", e.target.value)} />
              </FieldWrap>
              <FieldWrap label="Device ID (blank = fleet)">
                <input className={INPUT_CLS} placeholder="device-id or leave blank"
                  value={form.device_id} onChange={(e) => setField("device_id", e.target.value)} />
              </FieldWrap>
              <FieldWrap label="Schedule Type *">
                <select className={INPUT_CLS} value={form.schedule_type}
                  onChange={(e) => setField("schedule_type", e.target.value as "one_time" | "recurring")}>
                  <option value="recurring">Recurring (cron)</option>
                  <option value="one_time">One-time</option>
                </select>
              </FieldWrap>
              {form.schedule_type === "recurring" ? (
                <FieldWrap label="Cron Expression">
                  <input className={INPUT_CLS} placeholder="0 2 * * *"
                    value={form.cron_expression} onChange={(e) => setField("cron_expression", e.target.value)} />
                </FieldWrap>
              ) : (
                <FieldWrap label="Execute At (ISO 8601)">
                  <input className={INPUT_CLS} placeholder="2026-03-01T02:00:00Z"
                    value={form.execute_at} onChange={(e) => setField("execute_at", e.target.value)} />
                </FieldWrap>
              )}
              <FieldWrap label="Max Executions (blank = unlimited)">
                <input type="number" className={INPUT_CLS} min={1} placeholder="52"
                  value={form.max_executions} onChange={(e) => setField("max_executions", e.target.value)} />
              </FieldWrap>
            </div>
            <div className="flex gap-2 justify-end pt-2">
              <button
                type="button"
                onClick={() => { setShowForm(false); setForm(EMPTY_FORM); }}
                className="font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-none"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createSchedule.isPending}
                className="font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-4 py-2 rounded-none disabled:opacity-40"
              >
                {createSchedule.isPending ? "CREATING…" : "CREATE"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => <div key={i} className="h-10 animate-pulse bg-[#111113] border border-[#1E1E22] rounded-none" />)}
        </div>
      ) : schedules.length === 0 ? (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-12 text-center">
          <Clock className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
          <p className="font-mono text-xs text-zinc-600">NO SCHEDULES FOUND</p>
        </div>
      ) : (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                  {["NAME", "COMMAND", "DEVICE", "CRON", "STATUS", "NEXT RUN", "CREATED", ""].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {schedules.map((s) => (
                  <tr key={s.schedule_id} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-[#E4E4E7]">{s.schedule_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500">{s.command_type}</td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                      {s.device_id ? s.device_id.slice(0, 12) + "…" : <span className="text-zinc-700">fleet</span>}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500">{s.cron_expression ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`font-mono text-[10px] border px-1.5 py-0.5 rounded-none ${STATUS_CLS[s.status] ?? "border-zinc-600 text-zinc-500"}`}>
                        {s.status.toUpperCase()}
                      </span>
                    </td>
                    <td className={`px-4 py-3 font-mono text-xs ${isImminent(s.next_execution_at) ? "text-amber-400" : "text-zinc-500"}`}>
                      {s.next_execution_at ? formatRelativeTime(s.next_execution_at) : "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-600">{formatRelativeTime(s.created_at)}</td>
                    <td className="px-4 py-3">
                      <RoleGate permission="manageSchedules">
                        <div className="flex gap-1">
                          {s.status === "active" && (
                            <button onClick={() => handleAction("pause", s.schedule_id)}
                              className="font-mono text-[10px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-1.5 py-0.5 rounded-none">
                              <Pause className="h-3 w-3" />
                            </button>
                          )}
                          {s.status === "paused" && (
                            <button onClick={() => handleAction("resume", s.schedule_id)}
                              className="font-mono text-[10px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-1.5 py-0.5 rounded-none">
                              <Play className="h-3 w-3" />
                            </button>
                          )}
                          {(s.status === "active" || s.status === "paused" || s.status === "pending") && (
                            <button onClick={() => handleAction("cancel", s.schedule_id)}
                              className="font-mono text-[10px] border border-red-500/30 text-red-500 hover:bg-red-500/10 px-1.5 py-0.5 rounded-none">
                              <X className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      </RoleGate>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
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
