import { auth } from "@/lib/auth";
import { WorkflowChart } from "@/components/metrics/WorkflowChart";
import * as api from "@/lib/api";

const HOURS = 12;
const FAILED_PREFIXES = ["FAILED", "FAILED_ROLLED_BACK", "FAILED_WORKER_CRASH", "FAILED_CHILD_WORKFLOW"];

export async function WorkflowChartServer() {
  const session = await auth();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  if (!token) {
    return <WorkflowChart data={[]} />;
  }

  // Build 12 hourly slot labels (oldest → newest)
  const now = Date.now();
  const slots = Array.from({ length: HOURS }, (_, i) => {
    const slotStart = now - (HOURS - i) * 3600_000;
    const label = new Date(slotStart).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    return { time: label, slotStart, completed: 0, failed: 0 };
  });

  try {
    const since = new Date(now - HOURS * 3600_000).toISOString();
    const result = await api.listWorkflows(token, { limit: 200, since });

    for (const wf of result.workflows) {
      const ts = wf.started_at ? new Date(wf.started_at).getTime() : null;
      if (!ts) continue;

      // Find which hourly bucket this workflow falls into
      const bucketIdx = slots.findIndex(
        (s, i) =>
          ts >= s.slotStart &&
          (i === slots.length - 1 || ts < slots[i + 1].slotStart)
      );
      if (bucketIdx === -1) continue;

      if (wf.status === "COMPLETED") {
        slots[bucketIdx].completed += 1;
      } else if (FAILED_PREFIXES.some((p) => wf.status?.startsWith(p))) {
        slots[bucketIdx].failed += 1;
      }
    }
  } catch {
    // Silently degrade — chart shows empty rather than crashing the page
  }

  const data = slots.map(({ time, completed, failed }) => ({ time, completed, failed }));
  return <WorkflowChart data={data} />;
}
