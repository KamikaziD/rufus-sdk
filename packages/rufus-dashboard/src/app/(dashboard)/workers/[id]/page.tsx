"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getWorkerById, listWorkerCommands, cancelWorkerCommand, type WorkerCommand } from "@/lib/api";
import { hasPermission } from "@/lib/roles";
import { WorkerCommandModal } from "@/components/workers/WorkerCommandModal";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/utils";
import {
  ChevronLeft, RefreshCw, Wifi, WifiOff, Server, MapPin, Clock, Terminal
} from "lucide-react";

function useToken() {
  const { data: session } = useSession();
  return (session as unknown as { accessToken?: string })?.accessToken;
}

function useRoles() {
  const { data: session } = useSession();
  return (session?.user as unknown as { roles?: string[] })?.roles ?? [];
}

function statusVariant(status: string): "success" | "destructive" | "secondary" | "outline" {
  if (status === "completed") return "success";
  if (status === "failed") return "destructive";
  if (status === "pending" || status === "executing") return "outline";
  return "secondary";
}

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

  function handleRefresh() {
    refetchWorker();
    refetchCmds();
  }

  if (workerLoading) {
    return <div className="animate-pulse h-32 bg-muted rounded-xl" />;
  }

  if (!worker) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/workers"><ChevronLeft className="h-4 w-4" /> Workers</Link>
        </Button>
        <div className="text-muted-foreground">Worker not found</div>
      </div>
    );
  }

  const isOnline = worker.status === "online";
  const capabilityKeys = Object.keys(worker.capabilities ?? {});
  const commands: WorkerCommand[] = cmdData?.commands ?? [];
  const cmdTotal = cmdData?.total ?? 0;
  const cmdPageCount = Math.ceil(cmdTotal / CMD_PAGE_SIZE);

  return (
    <div className="space-y-6">
      {/* Back + Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/workers"><ChevronLeft className="h-4 w-4" /> Workers</Link>
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold font-mono">{worker.hostname}</h1>
            <Badge variant={isOnline ? "success" : "secondary"} className="gap-1">
              {isOnline ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
              {worker.status}
            </Badge>
          </div>
          <p className="text-muted-foreground text-sm font-mono">{worker.worker_id}</p>
        </div>
        <div className="flex items-center gap-2">
          {canManage && (
            <Button size="sm" onClick={() => setCmdModalOpen(true)}>
              <Terminal className="h-3.5 w-3.5" />
              Send Command
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={handleRefresh}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Hero info card */}
      <Card>
        <CardContent className="pt-5 pb-5">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <MapPin className="h-3 w-3" /> Region
              </span>
              <span className="font-medium">{worker.region || "—"}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Zone</span>
              <span className="font-medium">{worker.zone || "—"}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">SDK Version</span>
              <span className="font-mono font-medium">{worker.sdk_version ?? "—"}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" /> Last Heartbeat
              </span>
              <span className="font-medium tabular-nums">
                {worker.last_heartbeat ? formatRelativeTime(worker.last_heartbeat) : "—"}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">Pending Commands</span>
              <span className="font-medium tabular-nums">{worker.pending_command_count}</span>
            </div>
          </div>

          {capabilityKeys.length > 0 && (
            <div className="mt-4 pt-4 border-t">
              <p className="text-xs text-muted-foreground mb-2">Capabilities</p>
              <div className="flex flex-wrap gap-2">
                {capabilityKeys.map((k) => (
                  <Badge key={k} variant="secondary" className="text-xs font-mono">
                    {k}: {String(worker.capabilities[k])}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Commands section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Command History</CardTitle>
        </div>

        {/* Status filter */}
        <div className="flex gap-2 flex-wrap">
          {CMD_STATUS_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => { setCmdFilter(s); setCmdPage(1); }}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                cmdFilter === s
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-border text-muted-foreground hover:border-foreground"
              }`}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>

        <Card>
          <CardContent className="p-0">
            {cmdsLoading ? (
              <div className="p-6 space-y-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-10 animate-pulse bg-muted rounded" />
                ))}
              </div>
            ) : commands.length === 0 ? (
              <div className="py-12 text-center text-muted-foreground">
                <Server className="h-8 w-8 mx-auto mb-2 opacity-30" />
                <p className="text-sm">No commands found</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="text-left px-4 py-3 font-medium">Type</th>
                    <th className="text-left px-4 py-3 font-medium">Status</th>
                    <th className="text-left px-4 py-3 font-medium">Priority</th>
                    <th className="text-left px-4 py-3 font-medium">Created</th>
                    <th className="text-left px-4 py-3 font-medium">Completed</th>
                    <th className="text-left px-4 py-3 font-medium">Result</th>
                    <th className="text-right px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {commands.map((cmd) => (
                    <>
                      <tr key={cmd.command_id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-3 font-mono text-xs">{cmd.command_type}</td>
                        <td className="px-4 py-3">
                          <Badge variant={statusVariant(cmd.status)} className="text-xs">{cmd.status}</Badge>
                        </td>
                        <td className="px-4 py-3 text-xs capitalize">{cmd.priority}</td>
                        <td className="px-4 py-3 text-xs text-muted-foreground tabular-nums">
                          {cmd.created_at ? formatRelativeTime(cmd.created_at) : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-muted-foreground tabular-nums">
                          {cmd.completed_at ? formatRelativeTime(cmd.completed_at) : "—"}
                        </td>
                        <td className="px-4 py-3">
                          {cmd.result && Object.keys(cmd.result).length > 0 ? (
                            <button
                              onClick={() =>
                                setExpandedResult(
                                  expandedResult === cmd.command_id ? null : cmd.command_id
                                )
                              }
                              className="text-xs text-primary hover:underline"
                            >
                              {expandedResult === cmd.command_id ? "Collapse" : "Expand"}
                            </button>
                          ) : cmd.error_message ? (
                            <span className="text-xs text-destructive truncate max-w-[120px] block" title={cmd.error_message}>
                              {cmd.error_message}
                            </span>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {cmd.status === "pending" && canManage && (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-xs text-destructive hover:text-destructive"
                              disabled={cancelMut.isPending}
                              onClick={() => cancelMut.mutate(cmd.command_id)}
                            >
                              Cancel
                            </Button>
                          )}
                        </td>
                      </tr>
                      {expandedResult === cmd.command_id && cmd.result && (
                        <tr key={`${cmd.command_id}-result`} className="bg-muted/20 border-b">
                          <td colSpan={7} className="px-4 py-3">
                            <pre className="text-xs overflow-auto max-h-48 font-mono whitespace-pre-wrap break-all">
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
          </CardContent>
        </Card>

        {/* Pagination */}
        {cmdPageCount > 1 && (
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <Button
              variant="outline"
              size="sm"
              disabled={cmdPage === 1}
              onClick={() => setCmdPage((p) => Math.max(1, p - 1))}
            >
              ← Prev
            </Button>
            <span>Page {cmdPage} of {cmdPageCount}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={cmdPage >= cmdPageCount}
              onClick={() => setCmdPage((p) => p + 1)}
            >
              Next →
            </Button>
          </div>
        )}
      </div>

      {/* Command modal */}
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
