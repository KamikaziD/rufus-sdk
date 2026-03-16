"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface DataPoint {
  time: string;
  completed: number;
  failed: number;
}

interface WorkflowChartProps {
  data?: DataPoint[];
}

export function WorkflowChart({ data = [] }: WorkflowChartProps) {
  return (
    <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4">
      <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-4">
        WORKFLOW THROUGHPUT · 12H
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="colorCompleted" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#10B981" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="colorFailed" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#EF4444" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1E1E22" />
          <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#52525B", fontFamily: "var(--font-mono)" }} />
          <YAxis tick={{ fontSize: 10, fill: "#52525B", fontFamily: "var(--font-mono)" }} />
          <Tooltip
            contentStyle={{ background: "#111113", border: "1px solid #1E1E22", borderRadius: 0, fontFamily: "var(--font-mono)", fontSize: 11 }}
            labelStyle={{ color: "#71717A" }}
          />
          <Area type="monotone" dataKey="completed" stroke="#10B981" fill="url(#colorCompleted)" strokeWidth={1.5} name="Completed" />
          <Area type="monotone" dataKey="failed"    stroke="#EF4444" fill="url(#colorFailed)"    strokeWidth={1.5} name="Failed" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
