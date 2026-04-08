"use client";

interface KpiData {
  safRecoveredCents:   number;
  onlineDevices:       number;
  pendingHitl:         number;
  failedToday:         number;
  fraudPreventedCents: number;
}

interface KpiCardsProps {
  data?: KpiData;
  isLoading?: boolean;
}

function KpiCard({
  title,
  value,
  prefix,
  subtitle,
  accentColor,
  isLoading,
}: {
  title: string;
  value: number;
  prefix?: string;
  subtitle?: string;
  accentColor: string;
  isLoading?: boolean;
}) {
  return (
    <div className={`bg-[#111113] border border-[#1E1E22] rounded-none p-4 border-l-2 ${accentColor}`}>
      <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-2">{title}</div>
      {isLoading ? (
        <div className="h-8 w-12 animate-pulse bg-zinc-800 rounded-none" />
      ) : (
        <>
          <div className="font-mono text-3xl font-semibold text-[#E4E4E7]">
            {prefix && <span className="text-lg text-zinc-500 mr-0.5">{prefix}</span>}
            {value.toLocaleString()}
          </div>
          {subtitle && (
            <div className="font-mono text-[10px] text-zinc-600 mt-1">{subtitle}</div>
          )}
        </>
      )}
    </div>
  );
}

export function KpiCards({ data, isLoading }: KpiCardsProps) {
  const safDollars   = Math.round((data?.safRecoveredCents   ?? 0) / 100);
  const fraudDollars = Math.round((data?.fraudPreventedCents ?? 0) / 100);

  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
      <KpiCard
        title="SAF Recovered"
        value={safDollars}
        prefix="$"
        subtitle="offline txns synced to cloud"
        accentColor="border-l-emerald-400"
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
        title="Fraud Prevented"
        value={fraudDollars}
        prefix="$"
        subtitle="transactions blocked by scorer"
        accentColor="border-l-violet-500"
        isLoading={isLoading}
      />
    </div>
  );
}
