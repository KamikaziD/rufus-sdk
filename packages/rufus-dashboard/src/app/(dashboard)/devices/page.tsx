"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useDeviceList } from "@/lib/hooks/useDevice";
import { registerDevice } from "@/lib/api";
import { DeviceStatusBadge } from "@/components/shared/StatusBadge";
import { RoleGate } from "@/components/shared/RoleGate";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

const INPUT_CLS = "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm";

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
  sdk_version: "0.6.1",
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Device Fleet</h1>
          <p className="text-muted-foreground">
            {data?.devices.filter((d) => d.status === "online").length ?? 0} online ·{" "}
            {data?.total ?? 0} total
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <RoleGate permission="registerDevice">
            <Button size="sm" onClick={handleOpenModal}>
              <Plus className="h-3.5 w-3.5" />
              Register Device
            </Button>
          </RoleGate>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              statusFilter === s
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border text-muted-foreground hover:border-foreground"
            }`}
          >
            {s === "ALL" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Device grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-36 animate-pulse bg-muted rounded-xl" />
          ))}
        </div>
      ) : devices.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Cpu className="h-8 w-8 mx-auto mb-3 opacity-30" />
            No devices found
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {devices.map((device) => (
            <DeviceCard key={device.device_id} device={device} />
          ))}
        </div>
      )}

      {/* Register Device Modal */}
      <Dialog open={showModal} onOpenChange={(open) => !open && handleCloseModal()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Register Device</DialogTitle>
            <DialogDescription>
              Register a new edge device with the control plane.
            </DialogDescription>
          </DialogHeader>

          {regResult ? (
            <div className="space-y-3">
              <div className="rounded-md bg-green-50 border border-green-200 p-4">
                <p className="text-sm font-medium text-green-800 mb-2">Device registered successfully!</p>
                <p className="text-xs text-green-700 mb-1">Save this API key — it will not be shown again:</p>
                <code className="block text-xs font-mono bg-white border rounded px-3 py-2 mt-1 break-all">
                  {regResult.api_key}
                </code>
              </div>
              <DialogFooter>
                <Button onClick={handleCloseModal}>Close</Button>
              </DialogFooter>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3">
              {regError && (
                <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{regError}</p>
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
                    onChange={(e) => setField("sdk_version", e.target.value)} placeholder="0.6.1" />
                </FieldWrap>
                <FieldWrap label="Location (optional)">
                  <input className={INPUT_CLS} value={form.location}
                    onChange={(e) => setField("location", e.target.value)} placeholder="Store 42, Aisle 3" />
                </FieldWrap>
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={handleCloseModal}>Cancel</Button>
                <Button type="submit" disabled={registerMut.isPending}>
                  {registerMut.isPending ? "Registering…" : "Register Device"}
                </Button>
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
      <Card className="hover:border-primary transition-colors cursor-pointer">
        <CardContent className="pt-5 pb-4">
          <div className="flex items-start justify-between mb-3">
            <div>
              <p className="font-mono text-xs text-muted-foreground">{device.device_id.slice(0, 12)}…</p>
              <p className="font-medium text-sm mt-0.5">{device.device_type}</p>
            </div>
            {device.status === "online" ? (
              <Wifi className="h-4 w-4 text-green-500 mt-0.5" />
            ) : (
              <WifiOff className="h-4 w-4 text-muted-foreground mt-0.5" />
            )}
          </div>

          <div className="flex items-center justify-between">
            <DeviceStatusBadge status={device.status} />
            {device.pending_saf_count > 0 && (
              <Badge variant="warning">{device.pending_saf_count} SAF</Badge>
            )}
          </div>

          <p className="text-xs text-muted-foreground mt-2">
            {device.last_heartbeat
              ? `Last seen ${formatRelativeTime(device.last_heartbeat)}`
              : "Never connected"}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
