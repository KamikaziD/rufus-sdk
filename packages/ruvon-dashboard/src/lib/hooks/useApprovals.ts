"use client";

import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import * as api from "@/lib/api";

export function useApprovals() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useQuery({
    queryKey: ["approvals"],
    queryFn: () => api.listWorkflows(token!, { status: "WAITING_HUMAN", limit: 100, include_state: true }),
    enabled: !!token,
    refetchInterval: 10_000,
  });
}
