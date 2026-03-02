import { Suspense } from "react";
import { KpiCardsServer } from "@/components/metrics/KpiCardsServer";
import { RecentWorkflows } from "@/components/workflows/RecentWorkflows";
import { WorkflowChart } from "@/components/metrics/WorkflowChart";

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
        <WorkflowChart />
        <RecentWorkflows />
      </div>
    </div>
  );
}

function KpiCardsSkeleton() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="rounded-xl border bg-card p-6 animate-pulse">
          <div className="h-4 w-24 bg-muted rounded mb-3" />
          <div className="h-8 w-16 bg-muted rounded" />
        </div>
      ))}
    </div>
  );
}
