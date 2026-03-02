"use client";

import { useMemo } from "react";
import type { WorkflowStatus } from "@/types";

interface StepConfig {
  name: string;
  type: string;
  next?: string;
  routes?: Record<string, string>;
  tasks?: string[];
}

interface WorkflowDAGProps {
  stepsConfig: StepConfig[];
  currentStep: string | null;
  status: WorkflowStatus;
}

const NODE_COLORS: Record<string, string> = {
  STANDARD:        "#3b82f6",
  DECISION:        "#8b5cf6",
  PARALLEL:        "#06b6d4",
  HTTP:            "#f97316",
  ASYNC:           "#6366f1",
  HUMAN_IN_LOOP:   "#eab308",
  LOOP:            "#22c55e",
  FIRE_AND_FORGET: "#ec4899",
  CRON_SCHEDULE:   "#6366f1",
};

export function WorkflowDAG({ stepsConfig, currentStep, status }: WorkflowDAGProps) {
  // Simple SVG-based DAG (no external dependency)
  const nodes = useMemo(() => {
    const nodeWidth  = 160;
    const nodeHeight = 44;
    const hGap = 40;
    const vGap = 20;
    const cols = Math.min(stepsConfig.length, 3);
    const colWidth = nodeWidth + hGap;

    return stepsConfig.map((step, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      return {
        ...step,
        x: col * colWidth + 20,
        y: row * (nodeHeight + vGap) + 20,
        width: nodeWidth,
        height: nodeHeight,
      };
    });
  }, [stepsConfig]);

  if (!stepsConfig.length) {
    return <p className="text-sm text-muted-foreground">No workflow definition to visualize.</p>;
  }

  const cols = Math.min(stepsConfig.length, 3);
  const nodeWidth  = 160;
  const nodeHeight = 44;
  const hGap = 40;
  const vGap = 20;
  const svgWidth  = cols * (nodeWidth + hGap) + 20;
  const rows = Math.ceil(stepsConfig.length / cols);
  const svgHeight = rows * (nodeHeight + vGap) + 40;

  function getNodeColor(step: StepConfig): string {
    if (step.name === currentStep) {
      if (status.startsWith("FAILED")) return "#ef4444";
      return "#2563eb";
    }
    const idx = stepsConfig.findIndex((s) => s.name === step.name);
    const currentIdx = stepsConfig.findIndex((s) => s.name === currentStep);
    if (idx < currentIdx || status === "COMPLETED") return "#22c55e";
    return NODE_COLORS[step.type] ?? "#94a3b8";
  }

  function truncateName(name: string, maxLen = 16): string {
    return name.length > maxLen ? name.slice(0, maxLen) + "…" : name;
  }

  return (
    <div className="overflow-auto border rounded-lg bg-muted/20 p-2">
      <svg width={svgWidth} height={svgHeight} xmlns="http://www.w3.org/2000/svg">
        {/* Draw edges first */}
        {nodes.map((node, i) => {
          const next = nodes[i + 1];
          if (!next) return null;
          // Simple horizontal/vertical arrow
          const x1 = node.x + node.width / 2;
          const y1 = node.y + node.height;
          const x2 = next.x + next.width / 2;
          const y2 = next.y;
          return (
            <line key={`edge-${i}`} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke="#cbd5e1" strokeWidth={1.5} strokeDasharray="4,4"
              markerEnd="url(#arrow)" />
          );
        })}

        {/* Arrow marker */}
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" fill="#94a3b8" />
          </marker>
        </defs>

        {/* Draw nodes */}
        {nodes.map((node) => {
          const color = getNodeColor(node);
          const isCurrent = node.name === currentStep;
          return (
            <g key={node.name}>
              <rect
                x={node.x} y={node.y}
                width={node.width} height={node.height}
                rx={8} ry={8}
                fill={color}
                fillOpacity={isCurrent ? 1 : 0.15}
                stroke={color}
                strokeWidth={isCurrent ? 2 : 1}
              />
              <text
                x={node.x + node.width / 2}
                y={node.y + node.height / 2 - 5}
                textAnchor="middle"
                fontSize={11}
                fontWeight={isCurrent ? "600" : "400"}
                fill={isCurrent ? "white" : "#1e293b"}
              >
                {truncateName(node.name)}
              </text>
              <text
                x={node.x + node.width / 2}
                y={node.y + node.height / 2 + 10}
                textAnchor="middle"
                fontSize={9}
                fill={isCurrent ? "rgba(255,255,255,0.8)" : "#64748b"}
              >
                {node.type}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
