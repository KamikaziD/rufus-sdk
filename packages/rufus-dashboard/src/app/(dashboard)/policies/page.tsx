"use client";

import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { listPolicies } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Shield, RefreshCw } from "lucide-react";
import type { PolicyStatus } from "@/types";

const STATUS_VARIANT: Record<PolicyStatus, "success" | "secondary" | "outline"> = {
  ACTIVE:   "success",
  PAUSED:   "secondary",
  ARCHIVED: "outline",
};

export default function PoliciesPage() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["policies"],
    queryFn: () => listPolicies(token!),
    enabled: !!token,
  });

  const policies = data?.policies ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Policies</h1>
          <p className="text-muted-foreground">{policies.length} policies configured</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(4)].map((_, i) => <div key={i} className="h-12 animate-pulse bg-muted rounded" />)}
            </div>
          ) : policies.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">
              <Shield className="h-8 w-8 mx-auto mb-3 opacity-30" />
              No policies configured
            </div>
          ) : (
            <div className="divide-y">
              {policies.map((policy) => (
                <div key={policy.policy_id} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <p className="font-medium">{policy.name}</p>
                    <p className="text-xs text-muted-foreground">{policy.description}</p>
                  </div>
                  <Badge variant={STATUS_VARIANT[policy.status]}>{policy.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
