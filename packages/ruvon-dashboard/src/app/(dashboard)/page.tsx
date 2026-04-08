import { Suspense } from "react";
import { KpiCardsServer } from "@/components/metrics/KpiCardsServer";
import { RecentWorkflows } from "@/components/workflows/RecentWorkflows";
import { WorkflowChartServer } from "@/components/metrics/WorkflowChartServer";

export default function OverviewPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-[#E4E4E7]">Overview</h1>
        <p className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mt-0.5">
          Real-time status · Rufus Edge deployment
        </p>
      </div>

      <Suspense fallback={<KpiCardsSkeleton />}>
        <KpiCardsServer />
      </Suspense>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Suspense fallback={<ChartSkeleton />}>
          <WorkflowChartServer />
        </Suspense>
        <RecentWorkflows />
      </div>
    </div>
  );
}

function KpiCardsSkeleton() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="bg-[#111113] border border-[#1E1E22] rounded-none p-4 animate-pulse">
          <div className="h-3 w-24 bg-zinc-800 rounded-none mb-3" />
          <div className="h-8 w-16 bg-zinc-800 rounded-none" />
        </div>
      ))}
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="bg-[#111113] border border-[#1E1E22] rounded-none p-4 animate-pulse">
      <div className="h-3 w-40 bg-zinc-800 rounded-none mb-4" />
      <div className="h-48 bg-zinc-800 rounded-none" />
    </div>
  );
}
