"use client";

import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { WorkflowChart } from "@/components/metrics/WorkflowChart";
import * as api from "@/lib/api";

const HOURS = 12;

export function WorkflowChartServer() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const { data = [] } = useQuery({
    queryKey: ["workflow-chart"],
    queryFn: async () => {
      const buckets = await api.getMetricsThroughput(token!, HOURS);

      // Key by epoch-hour integer so fractional-minute client slots
      // match date_trunc'd server buckets regardless of wall-clock minutes.
      // e.g. client slot "07:38" → floor(epoch/3600000) == server bucket "07:00"
      const byEpochHour = new Map(
        buckets.map((b) => [
          Math.floor(new Date(b.hour).getTime() / 3_600_000),
          { completed: b.completed, failed: b.failed },
        ])
      );

      // Generate all HOURS slots so the X-axis is always continuous
      const now = Date.now();
      return Array.from({ length: HOURS }, (_, i) => {
        const slotStart = now - (HOURS - i) * 3_600_000;
        const epochHour = Math.floor(slotStart / 3_600_000);
        const label = new Date(slotStart).toLocaleTimeString("en-US", {
          hour: "2-digit", minute: "2-digit", hour12: false,
        });
        const bucket = byEpochHour.get(epochHour);
        return { time: label, completed: bucket?.completed ?? 0, failed: bucket?.failed ?? 0 };
      });
    },
    enabled: !!token,
    refetchInterval: 15_000,
  });

  return <WorkflowChart data={data} />;
}
