"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { listWorkers, type WorkerSummary } from "@/lib/api";
import { hasPermission } from "@/lib/roles";
import { WorkerCommandModal } from "@/components/workers/WorkerCommandModal";
import { formatRelativeTime } from "@/lib/utils";
import { Server, RefreshCw, Radio, ChevronRight } from "lucide-react";

const STATUS_OPTIONS = ["all", "online", "offline"] as const;

function useToken() {
  const { data: session } = useSession();
  return (session as unknown as { accessToken?: string })?.accessToken;
}

function useRoles() {
  const { data: session } = useSession();
  return (session?.user as unknown as { roles?: string[] })?.roles ?? [];
}

function WorkerStatusDot({ status }: { status: string }) {
  const online = status === "online";
  return (
    <span className={`font-mono text-xs ${online ? "text-emerald-400" : "text-zinc-600"}`}>
      {online ? "●" : "○"} {status.toUpperCase()}
    </span>
  );
}

export default function WorkersPage() {
  const token = useToken();
  const roles = useRoles();
  const canManage = hasPermission(roles, "manageWorkers");

  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "offline">("all");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  const [cmdModal, setCmdModal] = useState<{
    open: boolean;
    workerId: string;
    hostname: string;
  }>({ open: false, workerId: "", hostname: "" });

  const [broadcastOpen, setBroadcastOpen] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["workers", statusFilter, page],
    queryFn: () =>
      listWorkers(token, {
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    enabled: !!token,
    refetchInterval: 30_000,
  });

  const workers: WorkerSummary[] = data?.workers ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">WORKER FLEET</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">
            {total} worker{total !== 1 ? "s" : ""} registered
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
          {canManage && (
            <button
              onClick={() => setBroadcastOpen(true)}
              className="inline-flex items-center gap-1.5 font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-2 py-1 rounded-none transition-colors"
            >
              <Radio className="h-3 w-3" /> Broadcast
            </button>
          )}
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex gap-1.5">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1); }}
            className={`font-mono text-[10px] border px-2 py-1 rounded-none transition-colors ${
              statusFilter === s
                ? "bg-amber-500/10 border-amber-500/40 text-amber-400"
                : "border-zinc-700 text-zinc-500 hover:text-zinc-300 hover:border-zinc-500"
            }`}
          >
            {s.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-10 animate-pulse bg-zinc-800/50 rounded-none" />
            ))}
          </div>
        ) : workers.length === 0 ? (
          <div className="py-16 text-center">
            <Server className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
            <p className="font-mono text-xs text-zinc-600">NO WORKERS FOUND</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                  {["WORKER ID", "HOSTNAME", "REGION / ZONE", "STATUS", "SDK", "PENDING", "LAST HEARTBEAT", ""].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {workers.map((w) => (
                  <tr key={w.worker_id} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-zinc-400 truncate max-w-[140px]" title={w.worker_id}>
                      {w.worker_id.length > 18 ? w.worker_id.slice(0, 18) + "…" : w.worker_id}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-300">{w.hostname}</td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                      {w.region}
                      {w.zone && <span className="text-zinc-600"> / {w.zone}</span>}
                    </td>
                    <td className="px-4 py-3">
                      <WorkerStatusDot status={w.status} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                      {w.sdk_version ?? <span className="text-zinc-700">—</span>}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums">
                      {w.pending_command_count > 0 ? (
                        <span className="font-mono text-[10px] border border-amber-500/40 text-amber-400 px-1.5 py-0.5">
                          {w.pending_command_count}
                        </span>
                      ) : (
                        <span className="text-zinc-700">0</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500 tabular-nums">
                      {w.last_heartbeat ? formatRelativeTime(w.last_heartbeat) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {canManage && (
                          <button
                            onClick={() => setCmdModal({ open: true, workerId: w.worker_id, hostname: w.hostname })}
                            className="font-mono text-[10px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-2 py-0.5 rounded-none transition-colors"
                          >
                            CMD
                          </button>
                        )}
                        <Link
                          href={`/workers/${encodeURIComponent(w.worker_id)}`}
                          className="font-mono text-[10px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-2 py-0.5 rounded-none transition-colors"
                        >
                          <ChevronRight className="h-3 w-3" />
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            disabled={page === 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-3 py-1 rounded-none disabled:opacity-40 transition-colors"
          >
            ← Prev
          </button>
          <span className="font-mono text-xs text-zinc-600">Page {page} of {pageCount}</span>
          <button
            disabled={page >= pageCount}
            onClick={() => setPage((p) => p + 1)}
            className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-3 py-1 rounded-none disabled:opacity-40 transition-colors"
          >
            Next →
          </button>
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
