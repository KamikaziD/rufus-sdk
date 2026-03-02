"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GitBranch, Cpu, CheckSquare, AlertCircle } from "lucide-react";

interface KpiData {
  activeWorkflows: number;
  onlineDevices: number;
  pendingHitl: number;
  failedToday: number;
}

interface KpiCardsProps {
  data?: KpiData;
  isLoading?: boolean;
}

function KpiCard({
  title,
  value,
  icon: Icon,
  description,
  isLoading,
  accent,
}: {
  title: string;
  value: number;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
  isLoading?: boolean;
  accent?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <Icon className={`h-4 w-4 ${accent ?? "text-muted-foreground"}`} />
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="h-8 w-16 animate-pulse bg-muted rounded" />
        ) : (
          <div className="text-2xl font-bold">{value.toLocaleString()}</div>
        )}
        <p className="text-xs text-muted-foreground mt-1">{description}</p>
      </CardContent>
    </Card>
  );
}

export function KpiCards({ data, isLoading }: KpiCardsProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <KpiCard
        title="Active Workflows"
        value={data?.activeWorkflows ?? 0}
        icon={GitBranch}
        description="Currently running"
        isLoading={isLoading}
        accent="text-blue-500"
      />
      <KpiCard
        title="Online Devices"
        value={data?.onlineDevices ?? 0}
        icon={Cpu}
        description="Heartbeat within 2 min"
        isLoading={isLoading}
        accent="text-green-500"
      />
      <KpiCard
        title="Pending Approvals"
        value={data?.pendingHitl ?? 0}
        icon={CheckSquare}
        description="Awaiting human input"
        isLoading={isLoading}
        accent="text-yellow-500"
      />
      <KpiCard
        title="Failed (24h)"
        value={data?.failedToday ?? 0}
        icon={AlertCircle}
        description="Needs investigation"
        isLoading={isLoading}
        accent="text-red-500"
      />
    </div>
  );
}
