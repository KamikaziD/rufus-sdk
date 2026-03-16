"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { useDevice } from "@/lib/hooks/useDevice";
import { getDeviceSafTransactions } from "@/lib/api";
import { DeviceStatusBadge } from "@/components/shared/StatusBadge";
import { CommandSender } from "@/components/devices/CommandSender";
import { formatRelativeTime } from "@/lib/utils";
import { ChevronLeft, RefreshCw, DatabaseZap } from "lucide-react";
import Link from "next/link";

type Tab = "overview" | "commands" | "config" | "saf";

export default function DeviceDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const { data: device, isLoading, refetch } = useDevice(id);
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  if (isLoading) return <div className="animate-pulse h-32 bg-[#111113] border border-[#1E1E22]" />;
  if (!device) return <div className="font-mono text-sm text-zinc-600">Device not found</div>;

  const tabs: { key: Tab; label: string }[] = [
    { key: "overview",  label: "OVERVIEW" },
    { key: "commands",  label: "COMMANDS" },
    { key: "config",    label: "CONFIG" },
    { key: "saf",       label: `SAF${device.pending_saf_count > 0 ? ` (${device.pending_saf_count})` : ""}` },
  ];

  return (
    <div className="space-y-5">
      {/* Hero */}
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
        <div className="flex items-center gap-4">
          <Link href="/devices" className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors flex items-center gap-1">
            <ChevronLeft className="h-3 w-3" /> Devices
          </Link>
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm font-semibold text-[#E4E4E7]">{device.device_id.slice(0, 16)}…</span>
              <DeviceStatusBadge status={device.status} />
            </div>
            <p className="font-mono text-[11px] text-zinc-600 mt-0.5">
              {device.device_type} · Merchant: {device.merchant_id}
            </p>
          </div>
          <button onClick={() => refetch()} className="font-mono text-xs border border-zinc-700 text-zinc-500 hover:text-zinc-200 p-1 rounded-none transition-colors">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Tab strip */}
      <div className="flex gap-0 border-b border-[#1E1E22]">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`font-mono text-[10px] px-4 py-2 border-b-2 transition-colors ${
              activeTab === t.key
                ? "border-amber-500 text-amber-400"
                : "border-transparent text-zinc-600 hover:text-zinc-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
            <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-3">DEVICE INFO</div>
            <div className="grid grid-cols-2 gap-1 font-mono text-xs">
              <InfoRow label="Device ID"   value={device.device_id} />
              <InfoRow label="Type"        value={device.device_type} />
              <InfoRow label="Merchant"    value={device.merchant_id} />
              <InfoRow label="Firmware"    value={device.firmware_version ?? "—"} />
              <InfoRow label="SDK"         value={device.sdk_version ?? "—"} />
              <InfoRow label="Last Seen"   value={formatRelativeTime(device.last_heartbeat)} />
              <InfoRow label="Pending SAF" value={String(device.pending_saf_count)} amber={device.pending_saf_count > 0} />
            </div>
          </div>
        </div>
      )}

      {activeTab === "commands" && <CommandSender deviceId={id} />}

      {activeTab === "config" && (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-3">DEVICE CONFIG</div>
          <pre className="font-mono text-xs text-zinc-400 bg-[#0A0A0B] border border-[#1E1E22] p-4 overflow-auto max-h-80 leading-5">
            {JSON.stringify(device.metadata ?? {}, null, 2)}
          </pre>
        </div>
      )}

      {activeTab === "saf" && <SafTab deviceId={id} pendingCount={device.pending_saf_count} />}
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

  if (isLoading) return <div className="h-32 animate-pulse bg-[#111113] border border-[#1E1E22]" />;

  if (pendingCount === 0 && transactions.length === 0) {
    return (
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-12 text-center">
        <DatabaseZap className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
        <p className="font-mono text-xs text-zinc-600">NO PENDING SAF TRANSACTIONS</p>
      </div>
    );
  }

  if (transactions.length === 0) {
    return (
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-12 text-center">
        <DatabaseZap className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
        <p className="font-mono text-xs text-zinc-600">{pendingCount} PENDING SAF TRANSACTION{pendingCount !== 1 ? "S" : ""}</p>
        <p className="font-mono text-[10px] text-zinc-700 mt-1">Will sync automatically when device comes online.</p>
      </div>
    );
  }

  return (
    <div className="bg-[#111113] border border-[#1E1E22] rounded-none">
      <div className="px-4 py-3 border-b border-[#1E1E22] flex items-center gap-2">
        <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">STORE-AND-FORWARD TRANSACTIONS</span>
        {pendingCount > 0 && (
          <span className="font-mono text-[10px] border border-amber-500/40 text-amber-400 bg-amber-500/10 px-1.5 py-0.5">
            {pendingCount} pending
          </span>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="bg-[#0D0D0F] border-b border-[#1E1E22]">
              {["TRANSACTION ID", "AMOUNT", "MERCHANT", "STATUS", "WORKFLOW", "CREATED", "SYNCED"].map((h) => (
                <th key={h} className="text-left px-4 py-2.5 font-mono text-[10px] text-zinc-600 uppercase tracking-widest">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx) => {
              const displayAmount = tx.amount != null
                ? `${tx.currency ?? "USD"} ${tx.amount.toFixed(2)}`
                : tx.amount_cents != null
                  ? `${tx.currency ?? "USD"} ${(tx.amount_cents / 100).toFixed(2)}`
                  : "—";
              return (
              <tr key={tx.transaction_id} className="border-b border-[#1E1E22] hover:bg-[#1A1A1E] transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-zinc-400">{tx.transaction_id.slice(0, 16)}…</td>
                <td className="px-4 py-3 font-mono text-xs text-zinc-300">{displayAmount}</td>
                <td className="px-4 py-3 font-mono text-xs text-zinc-500">{tx.merchant_id ? tx.merchant_id.replace("merch-", "").replace(/-/g, " ") : "—"}</td>
                <td className="px-4 py-3">
                  <span className={`font-mono text-[10px] border px-1.5 py-0.5 rounded-none ${
                    tx.synced_at
                      ? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10"
                      : "border-yellow-500/40 text-yellow-400 bg-yellow-500/10"
                  }`}>
                    {tx.synced_at ? "SYNCED" : "PENDING"}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {tx.workflow_id ? (
                    <Link
                      href={`/workflows/${tx.workflow_id}`}
                      className="text-amber-400 hover:text-amber-300 hover:underline transition-colors"
                    >
                      {tx.workflow_id.slice(0, 8)}…
                    </Link>
                  ) : (
                    <span className="text-zinc-700">—</span>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-zinc-600">{formatRelativeTime(tx.created_at)}</td>
                <td className="px-4 py-3 font-mono text-xs text-zinc-600">{tx.synced_at ? formatRelativeTime(tx.synced_at) : "—"}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InfoRow({ label, value, amber }: { label: string; value: string; amber?: boolean }) {
  return (
    <>
      <span className="text-zinc-600">{label}</span>
      <span className={amber ? "text-amber-400" : "text-zinc-300"}>{value}</span>
    </>
  );
}
