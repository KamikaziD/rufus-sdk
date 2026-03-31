"use client";

import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { KpiCards } from "@/components/metrics/KpiCards";
import * as api from "@/lib/api";

export function KpiCardsServer() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const { data, isLoading } = useQuery({
    queryKey: ["kpi-overview"],
    queryFn: async () => {
      const since24h = new Date(Date.now() - 86400000).toISOString();
      const [hitl, failed, devices, impact] = await Promise.allSettled([
        api.listWorkflows(token!, { status: "WAITING_HUMAN", limit: 1 }),
        api.listWorkflows(token!, { status: "FAILED", limit: 1, since: since24h }),
        api.listDevices(token!),
        api.getEdgeImpact(token!),
      ]);
      return {
        safRecoveredCents:   impact.status === "fulfilled" ? (impact.value.saf_recovered_cents   ?? 0) : 0,
        fraudPreventedCents: impact.status === "fulfilled" ? (impact.value.fraud_prevented_cents ?? 0) : 0,
        pendingHitl:         hitl.status    === "fulfilled" ? (hitl.value.total    ?? 0) : 0,
        failedToday:         failed.status  === "fulfilled" ? (failed.value.total  ?? 0) : 0,
        onlineDevices:       devices.status === "fulfilled"
          ? devices.value.devices.filter((d) => d.status === "online").length : 0,
      };
    },
    enabled: !!token,
    refetchInterval: 30_000,
  });

  return <KpiCards data={data} isLoading={isLoading} />;
}
