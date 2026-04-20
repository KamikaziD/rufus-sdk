"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Copy, Check } from "lucide-react";

interface StatePanelProps {
  state: Record<string, unknown>;
}

export function StatePanel({ state }: StatePanelProps) {
  const [copied, setCopied] = useState(false);
  const [expandAll, setExpandAll] = useState(false);

  const json = JSON.stringify(state, null, 2);

  function handleCopy() {
    navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // Render value with syntax highlighting (simple approach)
  function renderValue(val: unknown, depth = 0): React.ReactNode {
    if (val === null) return <span className="text-slate-400">null</span>;
    if (typeof val === "boolean") return <span className="text-purple-600">{String(val)}</span>;
    if (typeof val === "number") return <span className="text-blue-600">{String(val)}</span>;
    if (typeof val === "string") return <span className="text-green-700">&quot;{val}&quot;</span>;
    if (Array.isArray(val)) {
      if (!expandAll && val.length > 3) {
        return <span className="text-muted-foreground">[{val.length} items]</span>;
      }
      return (
        <span>
          [
          {val.map((item, i) => (
            <span key={i}>
              {"\n" + "  ".repeat(depth + 1)}
              {renderValue(item, depth + 1)}
              {i < val.length - 1 ? "," : ""}
            </span>
          ))}
          {"\n" + "  ".repeat(depth)}]
        </span>
      );
    }
    if (typeof val === "object") {
      const entries = Object.entries(val as Record<string, unknown>);
      if (!expandAll && entries.length > 5) {
        return <span className="text-muted-foreground">{"{"}{entries.length} keys{"}"}</span>;
      }
      return (
        <span>
          {"{"}
          {entries.map(([k, v], i) => (
            <span key={k}>
              {"\n" + "  ".repeat(depth + 1)}
              <span className="text-red-700">&quot;{k}&quot;</span>: {renderValue(v, depth + 1)}
              {i < entries.length - 1 ? "," : ""}
            </span>
          ))}
          {"\n" + "  ".repeat(depth)}
          {"}"}
        </span>
      );
    }
    return <span>{String(val)}</span>;
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm">Workflow State</CardTitle>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setExpandAll(!expandAll)}>
            {expandAll ? "Collapse" : "Expand All"}
          </Button>
          <Button variant="ghost" size="icon" onClick={handleCopy} aria-label="Copy">
            {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <pre className="text-xs font-mono overflow-auto max-h-96 p-4 bg-muted rounded leading-5">
          {json}
        </pre>
      </CardContent>
    </Card>
  );
}
