import { Suspense } from "react";
import { KpiCardsServer } from "@/components/metrics/KpiCardsServer";
import { RecentWorkflows } from "@/components/workflows/RecentWorkflows";
import { WorkflowChartServer } from "@/components/metrics/WorkflowChartServer";

export default function OverviewPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
        <p className="text-muted-foreground">
          Real-time status of your Rufus Edge deployment
        </p>
      </div>

      <Suspense fallback={<KpiCardsSkeleton />}>
        <KpiCardsServer />
      </Suspense>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
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
        <div key={i} className="rounded-xl border bg-card p-6 animate-pulse">
          <div className="h-4 w-24 bg-muted rounded mb-3" />
          <div className="h-8 w-16 bg-muted rounded" />
        </div>
      ))}
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="rounded-xl border bg-card p-6 animate-pulse">
      <div className="h-4 w-40 bg-muted rounded mb-4" />
      <div className="h-48 bg-muted rounded" />
    </div>
  );
}
