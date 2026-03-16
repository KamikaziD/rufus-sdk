"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useDeviceList } from "@/lib/hooks/useDevice";
import { registerDevice } from "@/lib/api";
import { DeviceStatusBadge } from "@/components/shared/StatusBadge";
import { RoleGate } from "@/components/shared/RoleGate";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { formatRelativeTime } from "@/lib/utils";
import { Cpu, RefreshCw, Plus, Wifi, WifiOff } from "lucide-react";
import type { Device, DeviceStatus } from "@/types";

const INPUT_CLS = "flex h-9 w-full border border-[#1E1E22] bg-[#0A0A0B] px-3 py-1 font-mono text-sm text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50 transition-colors";

const STATUS_OPTIONS: Array<"ALL" | DeviceStatus> = ["ALL", "online", "offline", "maintenance"];

interface RegForm {
  device_id: string;
  device_type: string;
  device_name: string;
  merchant_id: string;
  firmware_version: string;
  sdk_version: string;
  location: string;
}

const EMPTY_REG: RegForm = {
  device_id: "",
  device_type: "pos",
  device_name: "",
  merchant_id: "",
  firmware_version: "1.0.0",
  sdk_version: "1.0.0rc3",
  location: "",
};

export default function DevicesPage() {
  const [statusFilter, setStatusFilter] = useState<"ALL" | DeviceStatus>("ALL");
  const { data, isLoading, refetch } = useDeviceList();
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState<RegForm>(EMPTY_REG);
  const [regResult, setRegResult] = useState<{ api_key: string } | null>(null);
  const [regError, setRegError] = useState<string | null>(null);

  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const queryClient = useQueryClient();

  const registerMut = useMutation({
    mutationFn: (body: Parameters<typeof registerDevice>[1]) => registerDevice(token!, body),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["devices"] });
      setRegResult({ api_key: res.api_key });
    },
    onError: (e) => setRegError(e instanceof Error ? e.message : "Registration failed."),
  });

  const devices = (data?.devices ?? []).filter(
    (d) => statusFilter === "ALL" || d.status === statusFilter
  );

  function setField<K extends keyof RegForm>(k: K, v: RegForm[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function handleOpenModal() {
    setForm(EMPTY_REG);
    setRegResult(null);
    setRegError(null);
    setShowModal(true);
  }

  function handleCloseModal() {
    setShowModal(false);
    setRegResult(null);
    setRegError(null);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setRegError(null);
    registerMut.mutate({
      device_id: form.device_id || undefined as unknown as string,
      device_type: form.device_type,
      device_name: form.device_name,
      merchant_id: form.merchant_id,
      firmware_version: form.firmware_version,
      sdk_version: form.sdk_version,
      location: form.location || undefined,
    });
  }

  const onlineCount = data?.devices.filter((d) => d.status === "online").length ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-sm font-semibold text-[#E4E4E7] tracking-wider uppercase">DEVICE FLEET</h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">
            {onlineCount} online · {data?.total ?? 0} total
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 px-2 py-1 rounded-none transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
          <RoleGate permission="registerDevice">
            <button
              onClick={handleOpenModal}
              className="inline-flex items-center gap-1.5 font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-2 py-1 rounded-none transition-colors"
            >
              <Plus className="h-3 w-3" /> Register Device
            </button>
          </RoleGate>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex gap-1.5">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`font-mono text-[10px] border px-2 py-1 rounded-none transition-colors ${
              statusFilter === s
                ? "bg-amber-500/10 border-amber-500/40 text-amber-400"
                : "border-zinc-700 text-zinc-500 hover:text-zinc-300 hover:border-zinc-500"
            }`}
          >
            {s === "ALL" ? "ALL" : s.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Device grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-36 animate-pulse bg-[#111113] border border-[#1E1E22] rounded-none" />
          ))}
        </div>
      ) : devices.length === 0 ? (
        <div className="bg-[#111113] border border-[#1E1E22] rounded-none py-12 text-center">
          <Cpu className="h-8 w-8 mx-auto mb-3 text-zinc-700" />
          <p className="font-mono text-xs text-zinc-600">NO DEVICES FOUND</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {devices.map((device) => (
            <DeviceCard key={device.device_id} device={device} />
          ))}
        </div>
      )}

      {/* Register Device Modal */}
      <Dialog open={showModal} onOpenChange={(open) => !open && handleCloseModal()}>
        <DialogContent className="bg-[#111113] border border-[#1E1E22] rounded-none max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm text-[#E4E4E7] uppercase tracking-wider">Register Device</DialogTitle>
            <DialogDescription className="font-mono text-xs text-zinc-600">
              Register a new edge device with the control plane.
            </DialogDescription>
          </DialogHeader>

          {regResult ? (
            <div className="space-y-3">
              <div className="border border-amber-500/30 bg-amber-500/5 p-4">
                <p className="font-mono text-xs text-amber-400 mb-2">DEVICE REGISTERED — save this API key</p>
                <code className="block font-mono text-xs text-amber-400 bg-[#0A0A0B] border border-amber-500/30 px-3 py-2 mt-1 break-all">
                  {regResult.api_key}
                </code>
              </div>
              <DialogFooter>
                <button
                  onClick={handleCloseModal}
                  className="font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-none"
                >
                  Close
                </button>
              </DialogFooter>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3">
              {regError && (
                <div className="border-l-4 border-red-500 bg-red-500/5 font-mono text-xs text-red-400 px-3 py-2">{regError}</div>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FieldWrap label="Device ID (blank = auto-generate)">
                  <input className={INPUT_CLS} value={form.device_id}
                    onChange={(e) => setField("device_id", e.target.value)} placeholder="pos-terminal-001" />
                </FieldWrap>
                <FieldWrap label="Device Type *">
                  <select required className={INPUT_CLS} value={form.device_type}
                    onChange={(e) => setField("device_type", e.target.value)}>
                    <option value="pos">POS Terminal</option>
                    <option value="atm">ATM</option>
                    <option value="kiosk">Kiosk</option>
                    <option value="mobile">Mobile Reader</option>
                  </select>
                </FieldWrap>
                <FieldWrap label="Device Name *">
                  <input required className={INPUT_CLS} value={form.device_name}
                    onChange={(e) => setField("device_name", e.target.value)} placeholder="Store 42 POS" />
                </FieldWrap>
                <FieldWrap label="Merchant ID *">
                  <input required className={INPUT_CLS} value={form.merchant_id}
                    onChange={(e) => setField("merchant_id", e.target.value)} placeholder="merchant-123" />
                </FieldWrap>
                <FieldWrap label="Firmware Version *">
                  <input required className={INPUT_CLS} value={form.firmware_version}
                    onChange={(e) => setField("firmware_version", e.target.value)} placeholder="1.0.0" />
                </FieldWrap>
                <FieldWrap label="SDK Version *">
                  <input required className={INPUT_CLS} value={form.sdk_version}
                    onChange={(e) => setField("sdk_version", e.target.value)} placeholder="1.0.0rc3" />
                </FieldWrap>
                <FieldWrap label="Location (optional)">
                  <input className={INPUT_CLS} value={form.location}
                    onChange={(e) => setField("location", e.target.value)} placeholder="Store 42, Aisle 3" />
                </FieldWrap>
              </div>
              <DialogFooter>
                <button
                  type="button"
                  onClick={handleCloseModal}
                  className="font-mono text-xs border border-zinc-700 text-zinc-400 hover:text-zinc-200 px-4 py-2 rounded-none"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={registerMut.isPending}
                  className="font-mono text-xs border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 px-4 py-2 rounded-none disabled:opacity-40"
                >
                  {registerMut.isPending ? "REGISTERING…" : "REGISTER DEVICE"}
                </button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DeviceCard({ device }: { device: Device }) {
  return (
    <Link href={`/devices/${device.device_id}`}>
      <div className="bg-[#111113] border border-[#1E1E22] rounded-none hover:border-zinc-600 cursor-pointer transition-colors p-4">
        <div className="flex items-start justify-between mb-3">
          <div>
            <p className="font-mono text-xs font-semibold text-[#E4E4E7]">{device.device_id.slice(0, 12)}…</p>
            <p className="font-mono text-[11px] text-zinc-500 mt-0.5 uppercase">{device.device_type}</p>
          </div>
          {device.status === "online" ? (
            <Wifi className="h-4 w-4 text-emerald-400 mt-0.5 flex-shrink-0" />
          ) : (
            <WifiOff className="h-4 w-4 text-zinc-600 mt-0.5 flex-shrink-0" />
          )}
        </div>

        <div className="flex items-center justify-between">
          <DeviceStatusBadge status={device.status} />
          {device.pending_saf_count > 0 && (
            <span className="font-mono text-[10px] border border-amber-500/40 text-amber-400 bg-amber-500/10 px-1.5 py-0.5">
              {device.pending_saf_count} SAF
            </span>
          )}
        </div>

        <p className="font-mono text-[11px] text-zinc-600 mt-2">
          {device.last_heartbeat
            ? `Last seen ${formatRelativeTime(device.last_heartbeat)}`
            : "Never connected"}
        </p>
      </div>
    </Link>
  );
}

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">{label}</label>
      {children}
    </div>
  );
}
