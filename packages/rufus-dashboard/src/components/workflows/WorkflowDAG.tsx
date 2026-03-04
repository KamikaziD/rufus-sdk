"use client";

import { useMemo, useCallback, useState, useEffect } from "react";
import ReactFlow, {
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  MarkerType,
  Position,
  type Node,
  type Edge,
} from "reactflow";
import "reactflow/dist/style.css";
import type { WorkflowStatus } from "@/types";

// ── Types ────────────────────────────────────────────────────────────────────

export interface StepConfig {
  name: string;
  type: string;
  next?: string;
  routes?: Array<{ condition: string; next: string }> | Record<string, string>;
  tasks?: Array<{ name: string; function?: string }> | string[];
}

interface WorkflowDAGProps {
  stepsConfig: StepConfig[];
  currentStep: string | null;
  status: WorkflowStatus;
  editable?: boolean;
  onSaveYaml?: (yaml: string) => void;
  yamlContent?: string;
}

// ── Colours ──────────────────────────────────────────────────────────────────

const STEP_COLORS: Record<string, string> = {
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

const NODE_W = 180;
const NODE_H = 56;
const V_GAP  = 80;   // vertical gap between ranks
const H_GAP  = 220;  // horizontal gap between nodes on same rank

// ── Simple layout (no external dep) ──────────────────────────────────────────
// Assigns (x, y) positions to nodes using a two-pass topological layout.
// Pass 1: assign rank (y level) via BFS from entry node.
// Pass 2: assign column (x) within each rank, centering each rank.

function layoutNodes(
  steps: StepConfig[]
): Map<string, { x: number; y: number }> {
  if (!steps.length) return new Map();

  // Build adjacency: name → [target names]
  const adj = new Map<string, string[]>();
  steps.forEach((s) => {
    const targets: string[] = [];
    if (s.next) targets.push(s.next);
    if (s.routes) {
      const routeArr = normaliseRoutes(s.routes);
      routeArr.forEach((r) => { if (r.next) targets.push(r.next); });
    }
    if (s.tasks) {
      s.tasks.forEach((t) => {
        const n = typeof t === "object" && "name" in t ? t.name : String(t);
        if (steps.some((s2) => s2.name === n)) targets.push(n);
      });
    }
    if (!targets.length && s !== steps[steps.length - 1]) {
      // implicit sequential link to next step in array
      const idx = steps.indexOf(s);
      if (idx >= 0 && idx < steps.length - 1) targets.push(steps[idx + 1].name);
    }
    adj.set(s.name, targets);
  });

  // BFS to assign ranks
  const ranks = new Map<string, number>();
  const queue: string[] = [steps[0].name];
  ranks.set(steps[0].name, 0);
  while (queue.length) {
    const cur = queue.shift()!;
    const rank = ranks.get(cur)!;
    for (const tgt of adj.get(cur) ?? []) {
      if (!ranks.has(tgt) || ranks.get(tgt)! < rank + 1) {
        ranks.set(tgt, rank + 1);
        queue.push(tgt);
      }
    }
  }
  // Any node not reached gets sequential rank
  steps.forEach((s, i) => { if (!ranks.has(s.name)) ranks.set(s.name, i); });

  // Group nodes by rank
  const byRank = new Map<number, string[]>();
  ranks.forEach((r, name) => {
    if (!byRank.has(r)) byRank.set(r, []);
    byRank.get(r)!.push(name);
  });

  // Assign (x, y): centre each rank horizontally
  const positions = new Map<string, { x: number; y: number }>();
  byRank.forEach((names, rank) => {
    const totalW = names.length * NODE_W + (names.length - 1) * H_GAP;
    const startX = -totalW / 2;
    names.forEach((name, col) => {
      positions.set(name, {
        x: startX + col * (NODE_W + H_GAP),
        y: rank * (NODE_H + V_GAP),
      });
    });
  });

  return positions;
}

// ── Route normalisation ───────────────────────────────────────────────────────

function normaliseRoutes(
  routes: StepConfig["routes"]
): Array<{ condition: string; next: string }> {
  if (!routes) return [];
  if (Array.isArray(routes)) {
    return routes.map((r) =>
      typeof r === "object" && "condition" in r
        ? { condition: r.condition, next: r.next }
        : { condition: String(r), next: "" }
    );
  }
  return Object.entries(routes).map(([condition, next]) => ({ condition, next }));
}

// ── Build ReactFlow nodes/edges ───────────────────────────────────────────────

function buildElements(
  steps: StepConfig[],
  currentStep: string | null,
  status: WorkflowStatus
): { nodes: Node[]; edges: Edge[] } {
  const positions = layoutNodes(steps);
  const stepNames = new Set(steps.map((s) => s.name));

  const nodes: Node[] = steps.map((step, i) => {
    const isActive = step.name === currentStep;
    const currentIdx = steps.findIndex((s) => s.name === currentStep);
    const isPast =
      status === "COMPLETED" || (currentIdx >= 0 && i < currentIdx);
    const isFailed = isActive && status.startsWith("FAILED");

    const color = isFailed
      ? "#ef4444"
      : isActive
      ? "#2563eb"
      : isPast
      ? "#22c55e"
      : (STEP_COLORS[step.type] ?? "#94a3b8");

    const pos = positions.get(step.name) ?? { x: 0, y: i * (NODE_H + V_GAP) };

    return {
      id: step.name,
      type: "default",
      data: {
        label: (
          <div style={{ textAlign: "center", lineHeight: 1.3 }}>
            <div style={{ fontWeight: isActive ? 700 : 400, fontSize: 11 }}>
              {step.name.length > 20 ? step.name.slice(0, 19) + "…" : step.name}
            </div>
            <div style={{ fontSize: 9, opacity: 0.75 }}>{step.type}</div>
          </div>
        ),
        stepType: step.type,
        routes: step.routes,
        stepName: step.name,
      },
      style: {
        background: color,
        color: isActive || isPast ? "white" : "#1e293b",
        border: `${isActive ? 2 : 1}px solid ${color}`,
        borderRadius: step.type === "DECISION" ? 2 : 8,
        opacity: isActive ? 1 : 0.85,
        width: NODE_W,
        height: NODE_H,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      position: pos,
    };
  });

  const edges: Edge[] = [];
  const seen = new Set<string>();

  steps.forEach((step, i) => {
    // Implicit sequential link
    if (!step.next && !step.routes && !step.tasks && i < steps.length - 1) {
      const id = `e-${step.name}-seq-${steps[i + 1].name}`;
      if (!seen.has(id)) {
        seen.add(id);
        edges.push({
          id,
          source: step.name,
          target: steps[i + 1].name,
          markerEnd: { type: MarkerType.ArrowClosed },
          style: { stroke: "#94a3b8" },
        });
      }
    }

    // Explicit next
    if (step.next && stepNames.has(step.next)) {
      const id = `e-${step.name}-next`;
      if (!seen.has(id)) {
        seen.add(id);
        edges.push({
          id,
          source: step.name,
          target: step.next,
          markerEnd: { type: MarkerType.ArrowClosed },
          style: { stroke: "#94a3b8" },
        });
      }
    }

    // DECISION routes
    if (step.routes) {
      normaliseRoutes(step.routes).forEach((r, ri) => {
        if (!stepNames.has(r.next)) return;
        const id = `e-${step.name}-route-${ri}`;
        if (!seen.has(id)) {
          seen.add(id);
          edges.push({
            id,
            source: step.name,
            target: r.next,
            label:
              r.condition.length > 35
                ? r.condition.slice(0, 34) + "…"
                : r.condition,
            labelStyle: { fontSize: 9, fill: "#6366f1" },
            labelBgStyle: { fill: "white", fillOpacity: 0.85 },
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { stroke: "#8b5cf6", strokeDasharray: "5,3" },
          });
        }
      });
    }

    // PARALLEL task fan-out
    if (step.tasks) {
      step.tasks.forEach((t, ti) => {
        const name =
          typeof t === "object" && "name" in t ? t.name : String(t);
        if (!stepNames.has(name)) return;
        const id = `e-${step.name}-task-${ti}`;
        if (!seen.has(id)) {
          seen.add(id);
          edges.push({
            id,
            source: step.name,
            target: name,
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { stroke: "#06b6d4" },
          });
        }
      });
    }
  });

  return { nodes, edges };
}

// ── DECISION Condition Editor ─────────────────────────────────────────────────

const OPERATORS = [">", ">=", "<", "<=", "==", "!=", "in", "not in"];
const CONDITION_RE = /^(.+?)\s*(>=|<=|!=|==|not\s+in|in|>|<)\s*(.+)$/;

interface Parsed { lhs: string; op: string; rhs: string }

function parseCondition(cond: string): Parsed | null {
  const m = cond.match(CONDITION_RE);
  if (!m) return null;
  return { lhs: m[1].trim(), op: m[2].trim(), rhs: m[3].trim() };
}

interface DecisionEditorProps {
  stepName: string;
  routes: StepConfig["routes"];
  onSave: (routes: Array<{ condition: string; next: string }>) => void;
  onClose: () => void;
}

function DecisionEditor({ stepName, routes, onSave, onClose }: DecisionEditorProps) {
  const [rows, setRows] = useState(() =>
    normaliseRoutes(routes).map((r) => {
      const parsed = parseCondition(r.condition);
      return { next: r.next, parsed, raw: r.condition, useRaw: !parsed };
    })
  );

  function setParsedField(i: number, field: keyof Parsed, val: string) {
    setRows((prev) =>
      prev.map((r, idx) =>
        idx !== i || !r.parsed ? r : { ...r, parsed: { ...r.parsed, [field]: val } }
      )
    );
  }

  function save() {
    onSave(
      rows.map((r) => ({
        condition:
          r.useRaw || !r.parsed
            ? r.raw
            : `${r.parsed.lhs} ${r.parsed.op} ${r.parsed.rhs}`,
        next: r.next,
      }))
    );
  }

  return (
    <div className="absolute right-0 top-0 h-full w-80 bg-background border-l shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between p-3 border-b bg-muted/50">
        <span className="text-sm font-semibold">Edit DECISION routes</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">✕</button>
      </div>
      <div className="text-xs text-muted-foreground px-3 pt-2 pb-1 font-mono">{stepName}</div>
      <div className="flex-1 overflow-auto p-3 space-y-4">
        {rows.map((row, i) => (
          <div key={i} className="border rounded p-2 space-y-2">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Route {i + 1}</span>
              <span>→ <span className="font-mono">{row.next}</span></span>
            </div>
            {row.useRaw || !row.parsed ? (
              <textarea
                className="w-full font-mono text-xs border rounded px-2 py-1 bg-muted/30"
                rows={2}
                value={row.raw}
                onChange={(e) =>
                  setRows((prev) => prev.map((r, idx) => idx !== i ? r : { ...r, raw: e.target.value }))
                }
              />
            ) : (
              <div className="flex items-center gap-1">
                <input
                  className="flex-1 min-w-0 text-xs border rounded px-2 py-1 font-mono bg-muted/30"
                  value={row.parsed.lhs}
                  onChange={(e) => setParsedField(i, "lhs", e.target.value)}
                  placeholder="left side"
                />
                <select
                  className="text-xs border rounded px-1 py-1 bg-background"
                  value={row.parsed.op}
                  onChange={(e) => setParsedField(i, "op", e.target.value)}
                >
                  {OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
                </select>
                <input
                  className="flex-1 min-w-0 text-xs border rounded px-2 py-1 font-mono bg-muted/30"
                  value={row.parsed.rhs}
                  onChange={(e) => setParsedField(i, "rhs", e.target.value)}
                  placeholder="right side"
                />
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="p-3 border-t flex gap-2">
        <button
          onClick={save}
          className="flex-1 bg-primary text-primary-foreground text-xs rounded py-1.5 font-medium hover:opacity-90"
        >
          Save &amp; Reload
        </button>
        <button onClick={onClose} className="text-xs border rounded px-3 py-1.5 hover:bg-muted">
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function WorkflowDAG({
  stepsConfig,
  currentStep,
  status,
  editable = false,
  onSaveYaml,
  yamlContent,
}: WorkflowDAGProps) {
  const [selectedDecision, setSelectedDecision] = useState<{
    name: string;
    routes: StepConfig["routes"];
  } | null>(null);

  const { nodes: initNodes, edges: initEdges } = useMemo(
    () => buildElements(stepsConfig, currentStep, status),
    [stepsConfig, currentStep, status]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initEdges);

  useEffect(() => {
    const { nodes: n, edges: e } = buildElements(stepsConfig, currentStep, status);
    setNodes(n);
    setEdges(e);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepsConfig, currentStep, status]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (!editable) return;
      if (node.data.stepType === "DECISION" && node.data.routes) {
        setSelectedDecision({ name: node.data.stepName, routes: node.data.routes });
      }
    },
    [editable]
  );

  function handleSaveRoutes(newRoutes: Array<{ condition: string; next: string }>) {
    if (!selectedDecision || !yamlContent || !onSaveYaml) {
      setSelectedDecision(null);
      return;
    }
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const yaml = require("js-yaml");
      const doc = yaml.load(yamlContent) as Record<string, unknown>;
      const steps = (doc.steps as Record<string, unknown>[]) ?? [];
      doc.steps = steps.map((s) =>
        s.name !== selectedDecision.name ? s : { ...s, routes: newRoutes }
      );
      onSaveYaml(yaml.dump(doc, { lineWidth: 120 }));
    } catch (e) {
      console.error("YAML reassembly failed", e);
    }
    setSelectedDecision(null);
  }

  if (!stepsConfig.length) {
    return <p className="text-sm text-muted-foreground">No workflow definition to visualize.</p>;
  }

  return (
    <div className="relative border rounded-lg overflow-hidden bg-muted/10" style={{ height: 380 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={editable}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#94a3b8" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>

      {editable && selectedDecision && (
        <DecisionEditor
          stepName={selectedDecision.name}
          routes={selectedDecision.routes}
          onSave={handleSaveRoutes}
          onClose={() => setSelectedDecision(null)}
        />
      )}
    </div>
  );
}
