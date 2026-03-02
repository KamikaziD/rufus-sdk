"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { useDevice } from "@/lib/hooks/useDevice";
import { getDeviceSafTransactions } from "@/lib/api";
import { DeviceStatusBadge } from "@/components/shared/StatusBadge";
import { CommandSender } from "@/components/devices/CommandSender";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/utils";
import { ChevronLeft, RefreshCw, DatabaseZap } from "lucide-react";
import Link from "next/link";

type Tab = "overview" | "commands" | "config" | "saf";

export default function DeviceDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const { data: device, isLoading, refetch } = useDevice(id);
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  if (isLoading) return <div className="animate-pulse h-32 bg-muted rounded-xl" />;
  if (!device) return <div className="text-muted-foreground">Device not found</div>;

  const tabs: { key: Tab; label: string }[] = [
    { key: "overview",  label: "Overview" },
    { key: "commands",  label: "Commands" },
    { key: "config",    label: "Config" },
    { key: "saf",       label: `SAF${device.pending_saf_count > 0 ? ` (${device.pending_saf_count})` : ""}` },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/devices"><ChevronLeft className="h-4 w-4" /> Devices</Link>
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold font-mono">{device.device_id.slice(0, 16)}…</h1>
            <DeviceStatusBadge status={device.status} />
          </div>
          <p className="text-muted-foreground text-sm">
            {device.device_type} · Merchant: {device.merchant_id}
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* Tabs */}
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

      {activeTab === "overview" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle className="text-sm">Device Info</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Device ID"   value={device.device_id} mono />
              <Row label="Type"        value={device.device_type} />
              <Row label="Merchant"    value={device.merchant_id} />
              <Row label="Firmware"    value={device.firmware_version ?? "—"} />
              <Row label="SDK Version" value={device.sdk_version ?? "—"} />
              <Row label="Last Seen"   value={formatRelativeTime(device.last_heartbeat)} />
              <Row label="Pending SAF" value={String(device.pending_saf_count)} />
            </CardContent>
          </Card>
        </div>
      )}

      {activeTab === "commands" && (
        <CommandSender deviceId={id} />
      )}

      {activeTab === "config" && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Device Config</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs font-mono bg-muted rounded p-4 overflow-auto max-h-80">
              {JSON.stringify(device.metadata ?? {}, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {activeTab === "saf" && (
        <SafTab deviceId={id} pendingCount={device.pending_saf_count} />
      )}
    </div>
  );
}

function SafTab({ deviceId, pendingCount }: { deviceId: string; pendingCount: number }) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const { data, isLoading } = useQuery({
    queryKey: ["device-saf", deviceId],
    queryFn: () => getDeviceSafTransactions(token!, deviceId),
    enabled: !!token,
    refetchInterval: 30_000,
  });

  const transactions = data?.transactions ?? [];

  if (isLoading) return <div className="h-32 animate-pulse bg-muted rounded-xl" />;

  if (pendingCount === 0 && transactions.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          <DatabaseZap className="h-8 w-8 mx-auto mb-3 opacity-30" />
          <p className="font-medium">No pending SAF transactions</p>
          <p className="text-xs mt-1">All offline transactions have been synced.</p>
        </CardContent>
      </Card>
    );
  }

  if (transactions.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          <DatabaseZap className="h-8 w-8 mx-auto mb-3 opacity-30" />
          <p className="font-medium">{pendingCount} pending SAF transaction{pendingCount !== 1 ? "s" : ""}</p>
          <p className="text-xs mt-1">Transactions will sync automatically when the device comes online.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          Store-and-Forward Transactions
          {pendingCount > 0 && (
            <Badge variant="warning">{pendingCount} pending</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="text-left px-4 py-3 font-medium">Transaction ID</th>
                <th className="text-left px-4 py-3 font-medium">Amount</th>
                <th className="text-left px-4 py-3 font-medium">Status</th>
                <th className="text-left px-4 py-3 font-medium">Created</th>
                <th className="text-left px-4 py-3 font-medium">Synced</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((tx) => (
                <tr key={tx.transaction_id} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-4 py-3 font-mono text-xs">{tx.transaction_id.slice(0, 16)}…</td>
                  <td className="px-4 py-3 text-xs">
                    {tx.amount != null
                      ? `${tx.currency ?? ""} ${tx.amount.toFixed(2)}`
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={tx.synced_at ? "success" : "warning"}>
                      {tx.synced_at ? "Synced" : "Pending"}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {formatRelativeTime(tx.created_at)}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {tx.synced_at ? formatRelativeTime(tx.synced_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? "font-mono text-xs" : ""}>{value}</span>
    </div>
  );
}
