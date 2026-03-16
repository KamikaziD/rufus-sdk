"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { queryAuditLogs, exportAuditLogs } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { FileText, RefreshCw, Download } from "lucide-react";

const EVENT_CLS: Record<string, string> = {
  COMPLETED: "border-emerald-500/40 text-emerald-400",
  FAILED:    "border-red-500/40 text-red-400",
  STARTED:   "border-blue-500/40 text-blue-400",
  STEP:      "border-zinc-600 text-zinc-500",
};

function eventCls(eventType: string) {
  const upper = eventType?.toUpperCase() ?? "";
  if (upper.includes("COMPLETE")) return EVENT_CLS.COMPLETED;
  if (upper.includes("FAIL"))     return EVENT_CLS.FAILED;
  if (upper.includes("START"))    return EVENT_CLS.STARTED;
  return EVENT_CLS.STEP;
}

export default function AuditPage() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const [page, setPage] = useState(1);
  const [exportFormat, setExportFormat] = useState<"json" | "csv">("json");
  const [isExporting, setIsExporting] = useState(false);

  async function handleExport() {
    if (!token) return;
    setIsExporting(true);
    try { await exportAuditLogs(token, exportFormat); }
    catch (e) { console.error("Export failed", e); }
    finally { setIsExporting(false); }
  }

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["audit", page],
    queryFn: () => queryAuditLogs(token!, { limit: 50, page }),
    enabled: !!token,
  });

  const logs = data?.logs ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / 50);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">AUDIT LOG</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">{total} entries total</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
          <select
            value={exportFormat}
            onChange={(e) => setExportFormat(e.target.value as "json" | "csv")}
            className="font-mono text-xs border border-zinc-700 bg-[#0A0A0B] text-zinc-400 px-2 py-1 rounded-none"
          >
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select>
          <button
            onClick={handleExport}
            disabled={isExporting}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none disabled:opacity-40 transition-colors"
          >
            <Download className="h-3 w-3" />
            {isExporting ? "Exporting…" : "Export"}
          </button>
        </div>
      </div>

      <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
        {isLoading ? (
          <div className="p-6 space-y-2">
            {[...Array(8)].map((_, i) => <div key={i} className="h-8 animate-pulse bg-zinc-800/50 rounded-none" />)}
          </div>
        ) : logs.length === 0 ? (
          <div className="py-12 text-center">
            <FileText className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
            <p className="font-mono text-xs text-zinc-600">NO AUDIT ENTRIES</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
                  {["TIMESTAMP", "EVENT", "ENTITY", "ACTOR"].map((h) => (
                    <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logs.map((entry) => (
                  <tr key={entry.log_id} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                    <td className="px-4 py-2 font-mono text-[11px] text-zinc-600 tabular-nums whitespace-nowrap">
                      {formatDateTime(entry.timestamp)}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`font-mono text-[10px] border px-1.5 py-0.5 rounded-none ${eventCls(entry.event_type)}`}>
                        {entry.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono text-[11px] text-zinc-500">
                      {entry.entity_type}/{entry.entity_id}
                    </td>
                    <td className="px-4 py-2 font-mono text-[11px] text-zinc-400">{entry.actor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
            className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-3 py-1 rounded-none disabled:opacity-40 transition-colors"
          >
            ← Prev
          </button>
          <span className="font-mono text-xs text-zinc-600">{page} / {pageCount}</span>
          <button
            disabled={page === pageCount}
            onClick={() => setPage((p) => p + 1)}
            className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 px-3 py-1 rounded-none disabled:opacity-40 transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
