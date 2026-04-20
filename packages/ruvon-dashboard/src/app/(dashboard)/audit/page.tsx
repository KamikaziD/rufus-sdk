"use client";

import { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { queryAuditLogs, exportAuditLogs } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { FileText, RefreshCw, Download, ArrowUpDown, X } from "lucide-react";

const EVENT_TYPES = [
  "WORKFLOW_STARTED",
  "WORKFLOW_COMPLETED",
  "WORKFLOW_FAILED",
  "WORKFLOW_CANCELLED",
  "STEP_STARTED",
  "STEP_COMPLETED",
  "STEP_FAILED",
  "WORKFLOW_PAUSED",
  "WORKFLOW_RESUMED",
  "COMPENSATION_STARTED",
  "COMPENSATION_COMPLETED",
];

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

function workflowLink(entityType: string, entityId: string) {
  const combined = `${entityType}/${entityId}`;
  const m = combined?.match(/workflow\/([0-9a-f-]{36})/i);
  if (m) return `/workflows/${m[1]}`;
  // Also try entity_id directly as UUID
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(entityId) && entityType?.toLowerCase().includes("workflow")) {
    return `/workflows/${entityId}`;
  }
  return null;
}

type SortCol = "timestamp" | "event_type" | "entity" | "actor";
type SortDir = "asc" | "desc";

const FILTER_INPUT = "bg-[#0A0A0B] border border-[#1E1E22] font-mono text-xs text-zinc-300 placeholder-zinc-600 px-3 py-1.5 focus:outline-none focus:border-zinc-500 transition-colors rounded-none";

export default function AuditPage() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const [page, setPage] = useState(1);
  const [exportFormat, setExportFormat] = useState<"json" | "csv">("json");
  const [isExporting, setIsExporting] = useState(false);

  // Server-side filters
  const [search, setSearch]         = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [eventType, setEventType]   = useState("");
  const [dateFrom, setDateFrom]     = useState("");
  const [dateTo, setDateTo]         = useState("");
  // Client-side filter
  const [actor, setActor]           = useState("");
  // Sort (client-side, operates on current page)
  const [sortCol, setSortCol] = useState<SortCol>("timestamp");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Debounce text search
  useEffect(() => {
    const t = setTimeout(() => { setDebouncedSearch(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset page on dropdown/date filter change
  useEffect(() => { setPage(1); }, [eventType, dateFrom, dateTo]);

  function toggleSort(col: SortCol) {
    if (sortCol === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("asc"); }
  }

  function clearFilters() {
    setSearch(""); setDebouncedSearch("");
    setEventType(""); setDateFrom(""); setDateTo(""); setActor("");
    setPage(1);
  }

  const hasFilters = !!(search || eventType || dateFrom || dateTo || actor);

  async function handleExport() {
    if (!token) return;
    setIsExporting(true);
    try {
      await exportAuditLogs(token, exportFormat, {
        entity_id: debouncedSearch || undefined,
        event_type: eventType || undefined,
        from: dateFrom || undefined,
        to: dateTo || undefined,
      });
    } catch (e) { console.error("Export failed", e); }
    finally { setIsExporting(false); }
  }

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["audit", page, debouncedSearch, eventType, dateFrom, dateTo],
    queryFn: () =>
      queryAuditLogs(token!, {
        limit: 50,
        page,
        entity_id: debouncedSearch || undefined,
        event_type: eventType || undefined,
        from: dateFrom || undefined,
        to: dateTo || undefined,
      }),
    enabled: !!token,
  });

  const rawLogs = data?.logs ?? [];
  const total   = data?.total ?? 0;
  const pageCount = Math.ceil(total / 50);

  // Client-side actor filter + sort
  const logs = useMemo(() => {
    let rows = rawLogs;
    if (actor) {
      const q = actor.toLowerCase();
      rows = rows.filter((e) => (e.actor ?? "").toLowerCase().includes(q));
    }
    return [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortCol === "timestamp")  cmp = (a.timestamp ?? "").localeCompare(b.timestamp ?? "");
      else if (sortCol === "event_type") cmp = (a.event_type ?? "").localeCompare(b.event_type ?? "");
      else if (sortCol === "entity")     cmp = (`${a.entity_type}/${a.entity_id}`).localeCompare(`${b.entity_type}/${b.entity_id}`);
      else if (sortCol === "actor")      cmp = (a.actor ?? "").localeCompare(b.actor ?? "");
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rawLogs, actor, sortCol, sortDir]);

  function ColHeader({ col, label }: { col: SortCol; label: string }) {
    const active = sortCol === col;
    return (
      <button
        onClick={() => toggleSort(col)}
        className={`flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest hover:text-zinc-300 transition-colors ${active ? "text-amber-400" : "text-zinc-600"}`}
      >
        {label}
        <ArrowUpDown className="h-2.5 w-2.5 opacity-50" />
        {active && <span className="text-[9px]">{sortDir === "asc" ? "↑" : "↓"}</span>}
      </button>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header */}
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

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <input
          type="text"
          placeholder="Search entity…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={`${FILTER_INPUT} w-48`}
        />
        <select
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          className={`${FILTER_INPUT} w-48`}
        >
          <option value="">All events</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className={FILTER_INPUT}
        />
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className={FILTER_INPUT}
        />
        <input
          type="text"
          placeholder="Actor…"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          className={`${FILTER_INPUT} w-32`}
        />
        {hasFilters && (
          <button
            onClick={clearFilters}
            className="inline-flex items-center gap-1 font-mono text-[10px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1.5 rounded-none transition-colors"
          >
            <X className="h-3 w-3" /> Clear
          </button>
        )}
      </div>

      {/* Table */}
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
                  <th className="text-left px-4 py-2.5"><ColHeader col="timestamp" label="TIMESTAMP" /></th>
                  <th className="text-left px-4 py-2.5"><ColHeader col="event_type" label="EVENT" /></th>
                  <th className="text-left px-4 py-2.5"><ColHeader col="entity" label="ENTITY" /></th>
                  <th className="text-left px-4 py-2.5"><ColHeader col="actor" label="ACTOR" /></th>
                </tr>
              </thead>
              <tbody>
                {logs.map((entry) => {
                  const link = workflowLink(entry.entity_type, entry.entity_id);
                  const entityStr = `${entry.entity_type}/${entry.entity_id}`;
                  return (
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
                        {link ? (
                          <Link href={link} className="text-amber-400 hover:text-amber-300 transition-colors">
                            {entityStr}
                          </Link>
                        ) : entityStr}
                      </td>
                      <td className="px-4 py-2 font-mono text-[11px] text-zinc-400">{entry.actor}</td>
                    </tr>
                  );
                })}
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
