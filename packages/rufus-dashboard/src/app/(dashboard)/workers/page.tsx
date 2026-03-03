"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { listWorkers, type WorkerSummary } from "@/lib/api";
import { hasPermission } from "@/lib/roles";
import { WorkerCommandModal } from "@/components/workers/WorkerCommandModal";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/utils";
import { Server, RefreshCw, Wifi, WifiOff, ChevronRight, Radio } from "lucide-react";

const STATUS_OPTIONS = ["all", "online", "offline"] as const;

function useToken() {
  const { data: session } = useSession();
  return (session as unknown as { accessToken?: string })?.accessToken;
}

function useRoles() {
  const { data: session } = useSession();
  return (session?.user as unknown as { roles?: string[] })?.roles ?? [];
}

function WorkerStatusBadge({ status }: { status: string }) {
  const online = status === "online";
  return (
    <Badge variant={online ? "success" : "secondary"} className="gap-1">
      {online
        ? <Wifi className="h-3 w-3" />
        : <WifiOff className="h-3 w-3" />}
      {status}
    </Badge>
  );
}

export default function WorkersPage() {
  const token = useToken();
  const roles = useRoles();
  const canManage = hasPermission(roles, "manageWorkers");

  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "offline">("all");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  // Single-worker command modal state
  const [cmdModal, setCmdModal] = useState<{
    open: boolean;
    workerId: string;
    hostname: string;
  }>({ open: false, workerId: "", hostname: "" });

  // Broadcast modal state
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Worker Fleet</h1>
          <p className="text-muted-foreground">{total} worker{total !== 1 ? "s" : ""} registered</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          {canManage && (
            <Button size="sm" onClick={() => setBroadcastOpen(true)}>
              <Radio className="h-3.5 w-3.5" />
              Broadcast
            </Button>
          )}
        </div>
      </div>

      {/* Status filter */}
      <div className="flex gap-2">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1); }}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              statusFilter === s
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border text-muted-foreground hover:border-foreground"
            }`}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-12 animate-pulse bg-muted rounded" />
              ))}
            </div>
          ) : workers.length === 0 ? (
            <div className="py-16 text-center text-muted-foreground">
              <Server className="h-10 w-10 mx-auto mb-3 opacity-30" />
              <p>No workers found</p>
              {statusFilter !== "all" && (
                <p className="text-xs mt-1">Try clearing the status filter</p>
              )}
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="text-left px-4 py-3 font-medium">Worker ID</th>
                  <th className="text-left px-4 py-3 font-medium">Hostname</th>
                  <th className="text-left px-4 py-3 font-medium">Region / Zone</th>
                  <th className="text-left px-4 py-3 font-medium">Status</th>
                  <th className="text-left px-4 py-3 font-medium">SDK</th>
                  <th className="text-left px-4 py-3 font-medium">Pending</th>
                  <th className="text-left px-4 py-3 font-medium">Last Heartbeat</th>
                  <th className="text-right px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {workers.map((w) => (
                  <tr key={w.worker_id} className="border-b last:border-0 hover:bg-muted/40 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs truncate max-w-[160px]" title={w.worker_id}>
                      {w.worker_id.length > 20 ? w.worker_id.slice(0, 20) + "…" : w.worker_id}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{w.hostname}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {w.region}
                      {w.zone && <span className="ml-1 text-muted-foreground/60">/ {w.zone}</span>}
                    </td>
                    <td className="px-4 py-3">
                      <WorkerStatusBadge status={w.status} />
                    </td>
                    <td className="px-4 py-3 text-xs font-mono">
                      {w.sdk_version ?? <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums">
                      {w.pending_command_count > 0
                        ? <Badge variant="outline" className="text-xs">{w.pending_command_count}</Badge>
                        : <span className="text-muted-foreground">0</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground tabular-nums">
                      {w.last_heartbeat ? formatRelativeTime(w.last_heartbeat) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {canManage && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            onClick={() => setCmdModal({ open: true, workerId: w.worker_id, hostname: w.hostname })}
                          >
                            Send Cmd
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" className="h-7 px-2" asChild>
                          <Link href={`/workers/${encodeURIComponent(w.worker_id)}`}>
                            <ChevronRight className="h-4 w-4" />
                          </Link>
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            ← Prev
          </Button>
          <span>Page {page} of {pageCount}</span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pageCount}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </Button>
        </div>
      )}

      {/* Single-worker command modal */}
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
