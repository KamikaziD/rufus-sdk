"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getWorkerById, listWorkerCommands, cancelWorkerCommand, type WorkerCommand } from "@/lib/api";
import { hasPermission } from "@/lib/roles";
import { WorkerCommandModal } from "@/components/workers/WorkerCommandModal";
import { formatRelativeTime } from "@/lib/utils";
import { ChevronLeft, RefreshCw, Server, Terminal } from "lucide-react";

function useToken() {
  const { data: session } = useSession();
  return (session as unknown as { accessToken?: string })?.accessToken;
}

function useRoles() {
  const { data: session } = useSession();
  return (session?.user as unknown as { roles?: string[] })?.roles ?? [];
}

const CMD_STATUS_CLS: Record<string, string> = {
  completed: "border-emerald-500/40 text-emerald-400",
  failed:    "border-red-500/40 text-red-400",
  pending:   "border-blue-500/40 text-blue-400",
  executing: "border-amber-500/40 text-amber-400",
  cancelled: "border-zinc-600 text-zinc-500",
};

const CMD_STATUS_OPTIONS = ["all", "pending", "completed", "failed", "cancelled"] as const;

export default function WorkerDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const token = useToken();
  const roles = useRoles();
  const queryClient = useQueryClient();
  const canManage = hasPermission(roles, "manageWorkers");

  const [cmdFilter, setCmdFilter] = useState<string>("all");
  const [cmdPage, setCmdPage] = useState(1);
  const [expandedResult, setExpandedResult] = useState<string | null>(null);
  const [cmdModalOpen, setCmdModalOpen] = useState(false);
  const CMD_PAGE_SIZE = 20;

  const { data: worker, isLoading: workerLoading, refetch: refetchWorker } = useQuery({
    queryKey: ["worker", id],
    queryFn: () => getWorkerById(token, id),
    enabled: !!token && !!id,
    refetchInterval: 15_000,
  });

  const { data: cmdData, isLoading: cmdsLoading, refetch: refetchCmds } = useQuery({
    queryKey: ["worker-commands", id, cmdFilter, cmdPage],
    queryFn: () =>
      listWorkerCommands(token, id, {
        status: cmdFilter === "all" ? undefined : cmdFilter,
        limit: CMD_PAGE_SIZE,
        offset: (cmdPage - 1) * CMD_PAGE_SIZE,
      }),
    enabled: !!token && !!id,
    refetchInterval: 15_000,
  });

  const cancelMut = useMutation({
    mutationFn: (commandId: string) => cancelWorkerCommand(token, commandId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["worker-commands", id] });
      queryClient.invalidateQueries({ queryKey: ["worker", id] });
    },
  });

  if (workerLoading) return <div className="animate-pulse h-32 bg-[#111113] border border-[#1E1E22]" />;

  if (!worker) {
    return (
      <div className="space-y-4">
        <Link href="/workers" className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-2 py-1 rounded-none flex items-center gap-1 w-fit">
          <ChevronLeft className="h-3 w-3" /> Workers
        </Link>
        <div className="font-mono text-sm text-zinc-600">Worker not found</div>
      </div>
    );
  }

  const isOnline = worker.status === "online";
  const capabilityKeys = Object.keys(worker.capabilities ?? {});
  const commands: WorkerCommand[] = cmdData?.commands ?? [];
  const cmdTotal = cmdData?.total ?? 0;
  const cmdPageCount = Math.ceil(cmdTotal / CMD_PAGE_SIZE);

  return (
    <div className="space-y-5">
      {/* Hero */}
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
        <div className="flex items-center gap-4">
          <Link href="/workers" className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors flex items-center gap-1">
            <ChevronLeft className="h-3 w-3" /> Workers
          </Link>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm font-semibold text-[#E4E4E7]">{worker.hostname}</span>
              <span className={`font-mono text-xs ${isOnline ? "text-emerald-400" : "text-zinc-600"}`}>
                {isOnline ? "●" : "○"} {worker.status.toUpperCase()}
              </span>
            </div>
            <p className="font-mono text-[10px] text-zinc-600 mt-0.5">{worker.worker_id}</p>
          </div>
          <div className="flex items-center gap-2">
            {canManage && (
              <button
                onClick={() => setCmdModalOpen(true)}
                className="inline-flex items-center gap-1.5 font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-2 py-1 rounded-none transition-colors"
              >
                <Terminal className="h-3 w-3" /> Send Command
              </button>
            )}
            <button
              onClick={() => { refetchWorker(); refetchCmds(); }}
              className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 p-1 rounded-none transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4 pt-4 border-t border-[#1E1E22] font-mono text-xs">
          <div>
            <span className="text-zinc-600 uppercase tracking-widest text-[10px]">Region</span>
            <p className="text-zinc-300 mt-0.5">{worker.region || "—"}</p>
          </div>
          <div>
            <span className="text-zinc-600 uppercase tracking-widest text-[10px]">Zone</span>
            <p className="text-zinc-300 mt-0.5">{worker.zone || "—"}</p>
          </div>
          <div>
            <span className="text-zinc-600 uppercase tracking-widest text-[10px]">SDK</span>
            <p className="text-zinc-300 mt-0.5">{worker.sdk_version ?? "—"}</p>
          </div>
          <div>
            <span className="text-zinc-600 uppercase tracking-widest text-[10px]">Last Heartbeat</span>
            <p className="text-zinc-300 mt-0.5 tabular-nums">
              {worker.last_heartbeat ? formatRelativeTime(worker.last_heartbeat) : "—"}
            </p>
          </div>
        </div>

        {capabilityKeys.length > 0 && (
          <div className="mt-4 pt-4 border-t border-[#1E1E22]">
            <p className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">Capabilities</p>
            <div className="flex flex-wrap gap-1.5">
              {capabilityKeys.map((k) => (
                <span key={k} className="font-mono text-[9px] border border-zinc-700 text-zinc-500 px-1 rounded-none">
                  {k}: {String(worker.capabilities[k])}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Command history */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">COMMAND HISTORY</span>
        </div>

        <div className="flex gap-1.5 flex-wrap">
          {CMD_STATUS_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => { setCmdFilter(s); setCmdPage(1); }}
              className={`font-mono text-[10px] border px-2 py-1 rounded-none transition-colors ${
                cmdFilter === s
                  ? "bg-amber-500/10 border-amber-500/40 text-amber-400"
                  : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {s.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
          {cmdsLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(3)].map((_, i) => <div key={i} className="h-10 animate-pulse bg-zinc-800/50" />)}
            </div>
          ) : commands.length === 0 ? (
            <div className="py-12 text-center">
              <Server className="h-8 w-8 mx-auto mb-2 text-zinc-700" />
              <p className="font-mono text-xs text-zinc-600">NO COMMANDS FOUND</p>
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                  {["TYPE", "STATUS", "PRIORITY", "CREATED", "COMPLETED", "RESULT", ""].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {commands.map((cmd) => (
                  <>
                    <tr key={cmd.command_id} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-zinc-400">{cmd.command_type}</td>
                      <td className="px-4 py-3">
                        <span className={`font-mono text-[10px] border px-1.5 py-0.5 rounded-none ${CMD_STATUS_CLS[cmd.status] ?? "border-zinc-600 text-zinc-500"}`}>
                          {cmd.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-500 capitalize">{cmd.priority}</td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-600 tabular-nums">
                        {cmd.created_at ? formatRelativeTime(cmd.created_at) : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-600 tabular-nums">
                        {cmd.completed_at ? formatRelativeTime(cmd.completed_at) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        {cmd.result && Object.keys(cmd.result).length > 0 ? (
                          <button
                            onClick={() => setExpandedResult(expandedResult === cmd.command_id ? null : cmd.command_id)}
                            className="font-mono text-[10px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-1.5 py-0.5 rounded-none"
                          >
                            {expandedResult === cmd.command_id ? "COLLAPSE" : "EXPAND"}
                          </button>
                        ) : cmd.error_message ? (
                          <span className="font-mono text-[10px] text-red-400 truncate max-w-[120px] block" title={cmd.error_message}>
                            {cmd.error_message}
                          </span>
                        ) : (
                          <span className="text-zinc-700 font-mono text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {cmd.status === "pending" && canManage && (
                          <button
                            disabled={cancelMut.isPending}
                            onClick={() => cancelMut.mutate(cmd.command_id)}
                            className="font-mono text-[10px] border border-red-500/30 text-red-500 hover:bg-red-500/10 px-2 py-0.5 rounded-none disabled:opacity-40"
                          >
                            [✕]
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedResult === cmd.command_id && cmd.result && (
                      <tr key={`${cmd.command_id}-result`} className="bg-[#0A0A0B] border-b border-[#1E1E22]">
                        <td colSpan={7} className="px-4 py-3">
                          <pre className="font-mono text-xs text-zinc-400 overflow-auto max-h-48 whitespace-pre-wrap break-all leading-5">
                            {JSON.stringify(cmd.result, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {cmdPageCount > 1 && (
          <div className="flex items-center justify-center gap-2">
            <button
              disabled={cmdPage === 1}
              onClick={() => setCmdPage((p) => Math.max(1, p - 1))}
              className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-3 py-1 rounded-none disabled:opacity-40"
            >
              ← Prev
            </button>
            <span className="font-mono text-xs text-zinc-600">Page {cmdPage} of {cmdPageCount}</span>
            <button
              disabled={cmdPage >= cmdPageCount}
              onClick={() => setCmdPage((p) => p + 1)}
              className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-3 py-1 rounded-none disabled:opacity-40"
            >
              Next →
            </button>
          </div>
        )}
      </div>

      {worker && (
        <WorkerCommandModal
          open={cmdModalOpen}
          onClose={() => setCmdModalOpen(false)}
          mode="single"
          workerId={worker.worker_id}
          workerHostname={worker.hostname}
        />
      )}
    </div>
  );
}
