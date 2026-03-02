"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { queryAuditLogs, exportAuditLogs } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FileText, RefreshCw, Download } from "lucide-react";

export default function AuditPage() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const [page, setPage] = useState(1);
  const [exportFormat, setExportFormat] = useState<"json" | "csv">("json");
  const [isExporting, setIsExporting] = useState(false);

  async function handleExport() {
    if (!token) return;
    setIsExporting(true);
    try {
      await exportAuditLogs(token, exportFormat);
    } catch (e) {
      console.error("Export failed", e);
    } finally {
      setIsExporting(false);
    }
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Audit Log</h1>
          <p className="text-muted-foreground">{total} entries total</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <select
            value={exportFormat}
            onChange={(e) => setExportFormat(e.target.value as "json" | "csv")}
            className="text-xs border rounded px-2 py-1 bg-background"
          >
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select>
          <Button variant="outline" size="sm" onClick={handleExport} disabled={isExporting}>
            <Download className="h-3.5 w-3.5" />
            {isExporting ? "Exporting…" : "Export"}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-8 animate-pulse bg-muted rounded" />
              ))}
            </div>
          ) : logs.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">
              <FileText className="h-8 w-8 mx-auto mb-3 opacity-30" />
              No audit entries
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Timestamp</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Event</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Entity</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Actor</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((entry) => (
                    <tr key={entry.log_id} className="border-b hover:bg-muted/30">
                      <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                        {new Date(entry.timestamp).toLocaleString()}
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant="outline">{entry.event_type}</Badge>
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {entry.entity_type}/{entry.entity_id}
                      </td>
                      <td className="px-4 py-2">{entry.actor}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {pageCount}</span>
          <Button variant="outline" size="sm" disabled={page === pageCount} onClick={() => setPage(p => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
