"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { getMeshTopology, listDevices } from "@/lib/api";
import type { MeshTopologyResponse, MeshTopologyNode, Device } from "@/types";

// ── Seeded LCG scatter layout ──────────────────────────────────────────────
function computeNodePositions(n: number, W: number, H: number) {
  const margin = 40;
  const aspect = W / H;
  const cols   = Math.ceil(Math.sqrt(n * aspect));
  const rows   = Math.ceil(n / cols);
  const cellW  = (W - 2 * margin) / Math.max(1, cols);
  const cellH  = (H - 2 * margin) / Math.max(1, rows);

  let seed = 0xdeadbeef;
  const lcg = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 0xffffffff;
  };

  return Array.from({ length: n }, (_, i) => ({
    x: margin + (i % cols) * cellW + cellW / 2 + (lcg() - 0.5) * cellW * 0.65,
    y: margin + Math.floor(i / cols) * cellH + cellH / 2 + (lcg() - 0.5) * cellH * 0.65,
  }));
}

// ── Tooltip state ──────────────────────────────────────────────────────────
interface TooltipState {
  x: number; y: number;
  node: MeshTopologyNode;
  device: Device | undefined;
}

// ── Canvas topology ────────────────────────────────────────────────────────
function TopologyCanvas({
  data,
  deviceMap,
  onHover,
  onLeave,
}: {
  data: MeshTopologyResponse;
  deviceMap: Map<string, Device>;
  onHover: (tip: TooltipState) => void;
  onLeave: () => void;
}) {
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // Stable refs so mousemove handler always reads latest data without re-registering
  const positionsRef = useRef<{ x: number; y: number }[]>([]);
  const nodesRef     = useRef<MeshTopologyNode[]>([]);
  const deviceMapRef = useRef<Map<string, Device>>(deviceMap);
  deviceMapRef.current = deviceMap;

  // ── Draw ────────────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas    = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || data.nodes.length === 0) return;

    const W = container.clientWidth;
    const H = Math.max(500, Math.round(W * 0.6));
    canvas.width  = W;
    canvas.height = H;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const positions = computeNodePositions(data.nodes.length, W, H);
    positionsRef.current = positions;
    nodesRef.current     = data.nodes;

    const posMap: Record<string, { x: number; y: number }> = {};
    data.nodes.forEach((n, i) => { posMap[n.device_id] = positions[i]; });

    // background
    ctx.fillStyle = "#060810";
    ctx.fillRect(0, 0, W, H);

    // ── relay edges ────────────────────────────────────────────────────
    const maxCount = Math.max(1, ...data.edges.map(e => e.relay_count));
    for (const e of data.edges) {
      const s = posMap[e.source_device_id];
      const t = posMap[e.relay_device_id];
      if (!s || !t) continue;
      const t_norm = e.relay_count / maxCount;
      const alpha  = 0.2 + t_norm * 0.7;
      const sw     = 0.7 + Math.log1p(e.relay_count) * 0.85;
      ctx.save();
      ctx.strokeStyle = `rgba(255,112,67,${alpha})`;
      ctx.lineWidth   = sw;
      if (t_norm > 0.55) { ctx.shadowColor = "#ff7043"; ctx.shadowBlur = 4; }
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();
      ctx.restore();
    }

    // ── nodes ──────────────────────────────────────────────────────────
    for (let i = 0; i < data.nodes.length; i++) {
      const n      = data.nodes[i];
      const pos    = positions[i];
      const dev    = deviceMapRef.current.get(n.device_id);
      const isOnline  = !dev || dev.status === "online";   // optimistic if not in device list
      const isAtm     = n.device_type === "atm";
      const r         = 4 + n.relay_score * 12;

      // Offline: desaturated grey-blue
      const fill = isOnline
        ? (isAtm ? "#8B5CF6" : "#3B82F6")
        : (isAtm ? "#4a3a6a" : "#253759");
      const glow = isAtm ? "#a78bfa" : "#60a5fa";

      ctx.save();
      ctx.globalAlpha = isOnline ? 1 : 0.45;

      if (n.relay_score > 0.05 && isOnline) {
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, r + 5 + n.relay_score * 6, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255,112,67,${n.relay_score * 0.55})`;
        ctx.lineWidth   = 1.5;
        ctx.stroke();
        ctx.shadowColor = glow;
        ctx.shadowBlur  = 10 + n.relay_score * 14;
      }

      ctx.fillStyle = fill;
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2);
      ctx.fill();

      // Online status dot — small bright cap on the node
      if (isOnline && dev) {
        ctx.shadowBlur  = 0;
        ctx.fillStyle   = "#22c55e";
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.arc(pos.x + r * 0.65, pos.y - r * 0.65, 2.2, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.restore();
    }
  }, [data, deviceMap]);

  // ── Mousemove (stable handler via refs) ─────────────────────────────────
  const handleMouseMove = useCallback((e: MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect   = canvas.getBoundingClientRect();
    const scaleX = canvas.width  / rect.width;
    const scaleY = canvas.height / rect.height;
    const mx = (e.clientX - rect.left) * scaleX;
    const my = (e.clientY - rect.top)  * scaleY;

    const positions = positionsRef.current;
    const nodes     = nodesRef.current;
    const HIT_R2    = 144; // 12px hit radius
    for (let i = 0; i < positions.length; i++) {
      const p  = positions[i];
      const dx = mx - p.x, dy = my - p.y;
      if (dx * dx + dy * dy < HIT_R2) {
        onHover({
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
          node: nodes[i],
          device: deviceMapRef.current.get(nodes[i].device_id),
        });
        return;
      }
    }
    onLeave();
  }, [onHover, onLeave]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.addEventListener("mousemove", handleMouseMove);
    canvas.addEventListener("mouseleave", onLeave);
    return () => {
      canvas.removeEventListener("mousemove", handleMouseMove);
      canvas.removeEventListener("mouseleave", onLeave);
    };
  }, [handleMouseMove, onLeave]);

  return (
    <div ref={containerRef} className="w-full relative" style={{ cursor: "crosshair" }}>
      <canvas ref={canvasRef} className="w-full block" />
      {/* Legend */}
      <div className="absolute bottom-4 left-4 flex flex-col gap-1.5 bg-[#060810]/80 px-2 py-2">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-[#3B82F6]" />
          <span className="font-mono text-[10px] text-zinc-500">POS Terminal</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-[#8B5CF6]" />
          <span className="font-mono text-[10px] text-zinc-500">ATM</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-px bg-[#ff7043]" />
          <span className="font-mono text-[10px] text-zinc-500">Relay path</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-[#253759] opacity-50" />
          <span className="font-mono text-[10px] text-zinc-500">Offline</span>
        </div>
      </div>
    </div>
  );
}

// ── Hover tooltip ──────────────────────────────────────────────────────────
function NodeTooltip({ tip }: { tip: TooltipState }) {
  const dev = tip.device;
  const isOnline = !dev || dev.status === "online";

  return (
    <div
      className="absolute z-10 pointer-events-none"
      style={{ left: tip.x + 16, top: tip.y - 8 }}
    >
      <div className="bg-[#0a0a0e] border border-[#2a2a30] shadow-xl min-w-[200px]">
        {/* Device ID header */}
        <div className="px-3 py-2 border-b border-[#1a1a20] flex items-center gap-2">
          <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${isOnline ? "bg-green-500" : "bg-zinc-600"}`} />
          <span className="font-mono text-[11px] text-[#e4e4e7] truncate max-w-[180px]">
            {tip.node.device_id}
          </span>
        </div>
        {/* Stats */}
        <div className="px-3 py-2 space-y-1">
          <div className="flex justify-between gap-6">
            <span className="font-mono text-[10px] text-zinc-500">Type</span>
            <span className="font-mono text-[10px] text-zinc-300 uppercase">{tip.node.device_type}</span>
          </div>
          <div className="flex justify-between gap-6">
            <span className="font-mono text-[10px] text-zinc-500">Status</span>
            <span className={`font-mono text-[10px] ${isOnline ? "text-green-400" : "text-zinc-600"}`}>
              {dev ? dev.status.toUpperCase() : "ONLINE"}
            </span>
          </div>
          {tip.node.relayed_for_others > 0 && (
            <div className="flex justify-between gap-6">
              <span className="font-mono text-[10px] text-zinc-500">Relayed for others</span>
              <span className="font-mono text-[10px] text-[#ff7043] font-bold">{tip.node.relayed_for_others}</span>
            </div>
          )}
          {tip.node.saved_by_peers > 0 && (
            <div className="flex justify-between gap-6">
              <span className="font-mono text-[10px] text-zinc-500">Saved by peers</span>
              <span className="font-mono text-[10px] text-amber-400 font-bold">{tip.node.saved_by_peers}</span>
            </div>
          )}
          {dev?.last_heartbeat && (
            <div className="flex justify-between gap-6">
              <span className="font-mono text-[10px] text-zinc-500">Last seen</span>
              <span className="font-mono text-[10px] text-zinc-400">
                {new Date(dev.last_heartbeat).toLocaleTimeString()}
              </span>
            </div>
          )}
          {dev?.pending_saf_count !== undefined && dev.pending_saf_count > 0 && (
            <div className="flex justify-between gap-6">
              <span className="font-mono text-[10px] text-zinc-500">SAF queue</span>
              <span className="font-mono text-[10px] text-amber-400">{dev.pending_saf_count}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Leaderboard ────────────────────────────────────────────────────────────
function MeshHeroLeaderboard({ nodes, deviceMap }: { nodes: MeshTopologyNode[]; deviceMap: Map<string, Device> }) {
  const heroes = [...nodes]
    .filter(n => n.relayed_for_others > 0)
    .sort((a, b) => b.relayed_for_others - a.relayed_for_others)
    .slice(0, 10);

  if (heroes.length === 0) {
    return <p className="font-mono text-[11px] text-zinc-700 px-3 py-6 text-center">No relay activity yet</p>;
  }

  return (
    <div className="space-y-px">
      {heroes.map((n, i) => {
        const dev      = deviceMap.get(n.device_id);
        const isOnline = !dev || dev.status === "online";
        return (
          <div key={n.device_id}
            className="flex items-center gap-3 px-3 py-2.5 hover:bg-[#0f0f12] transition-colors">
            <span className="font-mono text-[11px] text-zinc-600 w-4 tabular-nums shrink-0">
              {String(i + 1).padStart(2, "0")}
            </span>
            <div className="flex-1 min-w-0">
              <p className="font-mono text-[11px] text-[#d4d4d8] truncate">{n.device_id.slice(0, 22)}…</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <div className={`w-1 h-1 rounded-full ${isOnline ? "bg-green-500" : "bg-zinc-600"}`} />
                <p className="font-mono text-[10px] text-zinc-600">{n.device_type.toUpperCase()}</p>
              </div>
            </div>
            <span className="font-mono text-sm text-[#ff7043] tabular-nums font-bold shrink-0">
              {n.relayed_for_others}
            </span>
            <span className="font-mono text-[10px] text-zinc-600 shrink-0">txns</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────
export default function FleetTopologyPage() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["mesh-topology"],
    queryFn: () => getMeshTopology(token!),
    enabled: !!token,
    refetchInterval: 10000,
  });

  const { data: devicesData } = useQuery({
    queryKey: ["devices-topology"],
    queryFn: () => listDevices(token!),
    enabled: !!token,
    refetchInterval: 15000,
  });

  const deviceMap = new Map<string, Device>(
    (devicesData?.devices ?? []).map(d => [d.device_id, d])
  );

  const onlineCount  = (devicesData?.devices ?? []).filter(d => d.status === "online").length;
  const totalDevices = devicesData?.devices.length ?? 0;
  const totalRelayed = data?.edges.reduce((s, e) => s + e.relay_count, 0) ?? 0;

  const handleHover  = useCallback((tip: TooltipState) => setTooltip(tip), []);
  const handleLeave  = useCallback(() => setTooltip(null), []);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="font-mono text-xs font-semibold text-[#E4E4E7] uppercase tracking-[0.15em]">
            Fleet Mesh Topology
          </h1>
          <p className="font-mono text-[10px] text-zinc-600 mt-0.5">
            Live relay graph · {data?.nodes.length ?? 0} nodes · {data?.edges.length ?? 0} relay paths
            {totalDevices > 0 && (
              <> · <span className="text-green-500">{onlineCount}</span>
              <span className="text-zinc-700"> / {totalDevices} online</span></>
            )}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="font-mono text-[11px] border border-zinc-700 text-zinc-500 hover:text-zinc-200 hover:border-zinc-500 px-3 py-1.5 transition-colors uppercase tracking-wider"
        >
          Refresh
        </button>
      </div>

      {/* Main 2-col */}
      <div className="grid grid-cols-[1fr_260px] gap-4 items-start">
        {/* Canvas */}
        <div className="bg-[#060810] border border-[#1E1E22] overflow-hidden relative">
          {isLoading ? (
            <div className="h-[500px] flex items-center justify-center font-mono text-xs text-zinc-700">
              Loading topology…
            </div>
          ) : data && data.nodes.length > 0 ? (
            <>
              <TopologyCanvas
                data={data}
                deviceMap={deviceMap}
                onHover={handleHover}
                onLeave={handleLeave}
              />
              {tooltip && <NodeTooltip tip={tooltip} />}
            </>
          ) : (
            <div className="h-[500px] flex flex-col items-center justify-center gap-3">
              <p className="font-mono text-xs text-zinc-700">No relay data</p>
              <p className="font-mono text-[10px] text-zinc-800 text-center max-w-xs">
                Cut network in browser demo to generate relay activity, then restore
              </p>
            </div>
          )}
        </div>

        {/* Leaderboard */}
        <div className="bg-[#0a0a0d] border border-[#1E1E22]">
          <div className="px-3 py-3 border-b border-[#1E1E22] flex items-center justify-between">
            <p className="font-mono text-[10px] text-zinc-600 uppercase tracking-[0.15em]">Relay Heroes</p>
            {totalDevices > 0 && (
              <span className="font-mono text-[10px] text-green-500 tabular-nums">
                {onlineCount}/{totalDevices}
              </span>
            )}
          </div>
          {data ? (
            <MeshHeroLeaderboard nodes={data.nodes} deviceMap={deviceMap} />
          ) : (
            <div className="p-3 space-y-2 animate-pulse">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-9 bg-[#111115]" />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Stats bar */}
      {data && (
        <div className="bg-[#0a0a0d] border border-[#1E1E22] px-6 py-4 grid grid-cols-4 gap-8">
          {[
            { label: "Total Relay Paths",  value: data.edges.length },
            { label: "Hero Devices",       value: data.nodes.filter(n => n.relayed_for_others > 0).length },
            { label: "Rescued Devices",    value: data.nodes.filter(n => n.saved_by_peers > 0).length },
            { label: "Total Relayed",      value: totalRelayed },
          ].map(({ label, value }) => (
            <div key={label}>
              <p className="font-mono text-[10px] text-zinc-600 uppercase tracking-wider mb-1">{label}</p>
              <p className="font-mono text-2xl text-[#ff7043] font-bold tabular-nums">{value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
