"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useDevice } from "@/lib/hooks/useDevice";
import {
  getDeviceSafTransactions,
  getAdminDeviceConfig,
  saveAdminDeviceConfig,
  saveDeviceConfig,
  broadcastDeviceCommand,
  getDeviceMeshStats,
  type DeviceConfigData,
} from "@/lib/api";
import { DeviceStatusBadge } from "@/components/shared/StatusBadge";
import { CommandSender } from "@/components/devices/CommandSender";
import { formatRelativeTime } from "@/lib/utils";
import { ChevronLeft, RefreshCw, DatabaseZap, AlertCircle, CheckCircle2 } from "lucide-react";
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
        <div className="space-y-4">
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
          <MeshStatsPanel deviceId={id} />
        </div>
      )}

      {activeTab === "commands" && <CommandSender deviceId={id} />}

      {activeTab === "config" && <ConfigTab deviceId={id} />}

      {activeTab === "saf" && <SafTab deviceId={id} pendingCount={device.pending_saf_count} />}
    </div>
  );
}

function MeshStatsPanel({ deviceId }: { deviceId: string }) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const { data } = useQuery({
    queryKey: ["mesh-stats", deviceId],
    queryFn: () => getDeviceMeshStats(token!, deviceId),
    enabled: !!token,
    refetchInterval: 15000,
  });

  if (!data || (data.relayed_for_others === 0 && data.saved_by_peers === 0)) return null;

  return (
    <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
      <p className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-3">Mesh Relay Activity</p>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="font-mono text-[10px] text-zinc-500 uppercase tracking-wider">Relayed for Others</p>
          <p className="font-mono text-2xl text-[#ff7043] font-bold">{data.relayed_for_others}</p>
          <p className="font-mono text-[10px] text-zinc-600">transactions carried</p>
        </div>
        <div>
          <p className="font-mono text-[10px] text-zinc-500 uppercase tracking-wider">Saved by Peers</p>
          <p className="font-mono text-2xl text-amber-400 font-bold">{data.saved_by_peers}</p>
          <p className="font-mono text-[10px] text-zinc-600">transactions rescued</p>
        </div>
      </div>
      {data.last_relay_at && (
        <p className="font-mono text-[10px] text-zinc-700 mt-3">Last relay: {formatRelativeTime(data.last_relay_at)}</p>
      )}
    </div>
  );
}

function bumpPatchVersion(v: string): string {
  const parts = v.split(".");
  if (parts.length < 3) return v;
  const patch = parseInt(parts[2] ?? "0", 10);
  return `${parts[0]}.${parts[1]}.${isNaN(patch) ? 0 : patch + 1}`;
}

const CFG_INPUT = "flex h-9 w-full border border-[#1E1E22] bg-[#0A0A0B] px-3 py-1 font-mono text-sm text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50 transition-colors";

function ConfigTab({ deviceId }: { deviceId: string }) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const queryClient = useQueryClient();

  const { data: configData, isLoading } = useQuery({
    queryKey: ["device-config", deviceId],
    queryFn: () => getAdminDeviceConfig(token!, deviceId),
    enabled: !!token,
  });

  const [local, setLocal] = useState<DeviceConfigData | null>(null);
  const [description, setDescription] = useState("");
  const [fraudJson, setFraudJson] = useState<string | null>(null);
  const [fraudErr, setFraudErr] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [broadcastStatus, setBroadcastStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  // Use local edits if set, else fall back to fetched data
  const cfg: DeviceConfigData = local ?? configData?.config_data ?? {};
  const currentVersion = configData?.config_version ?? "1.0.0";
  const nextVersion = bumpPatchVersion(currentVersion);

  function setField<K extends keyof DeviceConfigData>(key: K, val: DeviceConfigData[K]) {
    setLocal((prev) => ({ ...(prev ?? cfg), [key]: val }));
  }
  function setFeature(name: string, enabled: boolean) {
    setLocal((prev) => ({
      ...(prev ?? cfg),
      features: { ...(cfg.features ?? {}), [name]: enabled },
    }));
  }

  const saveMut = useMutation({
    mutationFn: () => {
      let fraud_rules = cfg.fraud_rules ?? [];
      if (fraudJson !== null) {
        fraud_rules = JSON.parse(fraudJson);
      }
      return saveDeviceConfig(token!, deviceId, {
        config_version: nextVersion,
        config_data: { ...cfg, fraud_rules },
        description: description || undefined,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["device-config", deviceId] });
      setLocal(null);
      setFraudJson(null);
      setSaveStatus({ ok: true, msg: `Saved as v${nextVersion}` });
      setTimeout(() => setSaveStatus(null), 4000);
    },
    onError: (e: Error) => setSaveStatus({ ok: false, msg: e.message }),
  });

  const broadcastMut = useMutation({
    mutationFn: async () => {
      let fraud_rules = cfg.fraud_rules ?? [];
      if (fraudJson !== null) {
        fraud_rules = JSON.parse(fraudJson);
      }
      await saveDeviceConfig(token!, deviceId, {
        config_version: nextVersion,
        config_data: { ...cfg, fraud_rules },
        description: description || undefined,
      });
      return broadcastDeviceCommand(token!, {
        command_type: "reload_config",
        target_filter: { device_id: deviceId },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["device-config", deviceId] });
      setLocal(null);
      setFraudJson(null);
      setBroadcastStatus({ ok: true, msg: `Saved v${nextVersion} & broadcast reload_config` });
      setTimeout(() => setBroadcastStatus(null), 5000);
    },
    onError: (e: Error) => setBroadcastStatus({ ok: false, msg: e.message }),
  });

  function handleSave(e: React.FormEvent, withBroadcast: boolean) {
    e.preventDefault();
    setFraudErr(null);
    setSaveStatus(null);
    setBroadcastStatus(null);
    if (fraudJson !== null) {
      try { JSON.parse(fraudJson); } catch {
        setFraudErr("Invalid JSON in fraud rules");
        return;
      }
    }
    if (withBroadcast) broadcastMut.mutate();
    else saveMut.mutate();
  }

  const features = cfg.features ?? {};
  const FEATURE_KEYS: { key: string; label: string }[] = [
    { key: "offline_mode",  label: "Offline mode" },
    { key: "contactless",   label: "Contactless" },
    { key: "chip_fallback", label: "Chip fallback" },
    { key: "manual_entry",  label: "Manual entry" },
  ];

  const inFlight = saveMut.isPending || broadcastMut.isPending;

  if (isLoading) return <div className="h-48 animate-pulse bg-[#111113] border border-[#1E1E22]" />;

  return (
    <form onSubmit={(e) => handleSave(e, false)} className="space-y-4">
      {/* Header */}
      <div className="bg-[#111113] border border-[#1E1E22] px-4 py-3 flex items-center justify-between">
        <div>
          <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">DEVICE CONFIG</span>
          <span className="font-mono text-[10px] text-zinc-700 ml-3">v{currentVersion}</span>
        </div>
        {configData?.created_at && (
          <span className="font-mono text-[10px] text-zinc-700">updated {formatRelativeTime(configData.created_at)}</span>
        )}
      </div>

      {/* Row 1: Transaction limits + Payment thresholds */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-[#111113] border border-[#1E1E22] p-4 space-y-3">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-1">TRANSACTION LIMITS</div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Floor Limit (USD)</label>
            <input
              type="number" step="0.01" min="0"
              className={CFG_INPUT}
              value={cfg.floor_limit ?? ""}
              onChange={(e) => setField("floor_limit", parseFloat(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Max Offline Transactions</label>
            <input
              type="number" min="0"
              className={CFG_INPUT}
              value={cfg.max_offline_transactions ?? ""}
              onChange={(e) => setField("max_offline_transactions", parseInt(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Offline Timeout (hours)</label>
            <input
              type="number" min="0"
              className={CFG_INPUT}
              value={cfg.offline_timeout_hours ?? ""}
              onChange={(e) => setField("offline_timeout_hours", parseInt(e.target.value))}
            />
          </div>
        </div>

        <div className="bg-[#111113] border border-[#1E1E22] p-4 space-y-3">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-1">PAYMENT THRESHOLDS</div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">PIN Required Above (USD)</label>
            <input
              type="number" step="0.01" min="0"
              className={CFG_INPUT}
              value={cfg.require_pin_above ?? ""}
              onChange={(e) => setField("require_pin_above", parseFloat(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Signature Required Above (USD)</label>
            <input
              type="number" step="0.01" min="0"
              className={CFG_INPUT}
              value={cfg.require_signature_above ?? ""}
              onChange={(e) => setField("require_signature_above", parseFloat(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Card Types (comma-separated)</label>
            <input
              type="text"
              className={CFG_INPUT}
              value={(cfg.supported_card_types ?? []).join(", ")}
              onChange={(e) => setField("supported_card_types", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
            />
          </div>
        </div>
      </div>

      {/* Row 2: Feature flags + Sync settings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-[#111113] border border-[#1E1E22] p-4">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-3">FEATURE FLAGS</div>
          <div className="space-y-2">
            {FEATURE_KEYS.map(({ key, label }) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-amber-500"
                  checked={features[key] ?? false}
                  onChange={(e) => setFeature(key, e.target.checked)}
                />
                <span className="font-mono text-xs text-zinc-400">{label}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="bg-[#111113] border border-[#1E1E22] p-4 space-y-3">
          <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-1">SYNC SETTINGS</div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Sync Interval (seconds)</label>
            <input
              type="number" min="10"
              className={CFG_INPUT}
              value={cfg.sync_interval_seconds ?? ""}
              onChange={(e) => setField("sync_interval_seconds", parseInt(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">Heartbeat Interval (seconds)</label>
            <input
              type="number" min="5"
              className={CFG_INPUT}
              value={cfg.heartbeat_interval_seconds ?? ""}
              onChange={(e) => setField("heartbeat_interval_seconds", parseInt(e.target.value))}
            />
          </div>
        </div>
      </div>

      {/* Fraud rules */}
      <div className="bg-[#111113] border border-[#1E1E22] p-4">
        <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">FRAUD RULES (JSON)</div>
        <textarea
          rows={4}
          className="font-mono text-xs bg-[#0A0A0B] border border-[#1E1E22] p-3 w-full text-zinc-300 rounded-none focus:outline-none focus:border-amber-500/50 transition-colors"
          value={fraudJson ?? JSON.stringify(cfg.fraud_rules ?? [], null, 2)}
          onChange={(e) => {
            setFraudJson(e.target.value);
            setFraudErr(null);
          }}
        />
        {fraudErr && (
          <p className="font-mono text-xs text-red-400 mt-1 flex items-center gap-1">
            <AlertCircle className="h-3 w-3" />{fraudErr}
          </p>
        )}
      </div>

      {/* Description */}
      <div className="bg-[#111113] border border-[#1E1E22] p-4">
        <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">DESCRIPTION (optional)</div>
        <input
          type="text"
          className={CFG_INPUT}
          placeholder="What changed in this version?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={inFlight}
          className="border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 font-mono text-xs px-4 py-1.5 rounded-none disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {saveMut.isPending ? "Saving…" : "Save Config"}
        </button>
        <button
          type="button"
          disabled={inFlight}
          onClick={(e) => handleSave(e as unknown as React.FormEvent, true)}
          className="border border-zinc-600 text-zinc-400 hover:bg-zinc-700/20 font-mono text-xs px-4 py-1.5 rounded-none disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
        >
          {broadcastMut.isPending ? "Saving…" : "Save & Broadcast Reload ▶"}
        </button>
      </div>

      {saveStatus && (
        <p className={`font-mono text-xs flex items-center gap-1 ${saveStatus.ok ? "text-emerald-400" : "text-red-400"}`}>
          {saveStatus.ok ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
          {saveStatus.msg}
        </p>
      )}
      {broadcastStatus && (
        <p className={`font-mono text-xs flex items-center gap-1 ${broadcastStatus.ok ? "text-emerald-400" : "text-red-400"}`}>
          {broadcastStatus.ok ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
          {broadcastStatus.msg}
        </p>
      )}
    </form>
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
              {["TRANSACTION ID", "AMOUNT", "MERCHANT", "STATUS", "VIA", "WORKFLOW", "CREATED", "SYNCED"].map((h) => (
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
                <td className="px-4 py-3 font-mono text-[11px] text-[#ff7043]">
                  {tx.relay_device_id ? tx.relay_device_id.slice(0, 12) + "…" : "—"}
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
