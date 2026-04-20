"use client";

import { cn } from "@/lib/utils";

interface LiveIndicatorProps {
  connected: boolean;
  className?: string;
}

export function LiveIndicator({ connected, className }: LiveIndicatorProps) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", className)}>
      <span
        className={cn(
          "relative flex h-2 w-2",
          connected ? "text-green-500" : "text-slate-400"
        )}
      >
        {connected && (
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
        )}
        <span
          className={cn(
            "relative inline-flex rounded-full h-2 w-2",
            connected ? "bg-green-500" : "bg-slate-400"
          )}
        />
      </span>
      {connected ? "Live" : "Disconnected"}
    </span>
  );
}
