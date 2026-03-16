"use client";

interface KpiData {
  activeWorkflows: number;
  onlineDevices: number;
  pendingHitl: number;
  failedToday: number;
  onlineWorkers?: number;
}

interface KpiCardsProps {
  data?: KpiData;
  isLoading?: boolean;
}

function KpiCard({
  title,
  value,
  accentColor,
  isLoading,
}: {
  title: string;
  value: number;
  accentColor: string;
  isLoading?: boolean;
}) {
  return (
    <div className={`bg-[#111113] border border-[#1E1E22] rounded-none p-4 border-l-2 ${accentColor}`}>
      <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">{title}</div>
      {isLoading ? (
        <div className="h-8 w-12 animate-pulse bg-zinc-800 rounded-none" />
      ) : (
        <div className="font-mono text-3xl font-semibold text-[#E4E4E7]">{value.toLocaleString()}</div>
      )}
    </div>
  );
}

export function KpiCards({ data, isLoading }: KpiCardsProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
      <KpiCard
        title="Active Workflows"
        value={data?.activeWorkflows ?? 0}
        accentColor="border-l-amber-500"
        isLoading={isLoading}
      />
      <KpiCard
        title="Online Devices"
        value={data?.onlineDevices ?? 0}
        accentColor="border-l-emerald-500"
        isLoading={isLoading}
      />
      <KpiCard
        title="Pending Approvals"
        value={data?.pendingHitl ?? 0}
        accentColor="border-l-yellow-500"
        isLoading={isLoading}
      />
      <KpiCard
        title="Failed (24h)"
        value={data?.failedToday ?? 0}
        accentColor="border-l-red-500"
        isLoading={isLoading}
      />
      <KpiCard
        title="Online Workers"
        value={data?.onlineWorkers ?? 0}
        accentColor="border-l-blue-500"
        isLoading={isLoading}
      />
    </div>
  );
}
