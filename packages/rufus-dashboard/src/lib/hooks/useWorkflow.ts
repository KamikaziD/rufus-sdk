"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import * as api from "@/lib/api";
// NOTE: mutation return types are `unknown` — the server returns simple status objects,
// not full WorkflowExecution shapes, for next/resume/cancel/retry/rewind.

export function useWorkflowList(params: { status?: string; type?: string; limit?: number; page?: number } = {}) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useQuery({
    queryKey: ["workflows", params],
    queryFn: () => api.listWorkflows(token!, params),
    enabled: !!token,
    refetchInterval: 15_000,
  });
}

export function useWorkflow(id: string) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useQuery({
    queryKey: ["workflow", id],
    queryFn: () => api.getWorkflow(token!, id),
    enabled: !!token && !!id,
    refetchInterval: 5_000,
  });
}

export function useWorkflowTypes() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useQuery({
    queryKey: ["workflow-types"],
    queryFn: () => api.getWorkflowTypes(token!),
    enabled: !!token,
    staleTime: 60_000,
  });
}

export function useStartWorkflow() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useMutation({
    mutationFn: (body: { workflow_type: string; initial_data?: Record<string, unknown>; dry_run?: boolean }) =>
      api.startWorkflow(token!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useResumeWorkflow() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useMutation({
    mutationFn: ({ id, userInput }: { id: string; userInput: Record<string, unknown> }) =>
      api.resumeWorkflow(token!, id, userInput),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ["workflow", id] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
}

export function useCancelWorkflow() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useMutation({
    mutationFn: (id: string) => api.cancelWorkflow(token!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
}

export function useNextStep() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useMutation({
    mutationFn: ({ id, userInput }: { id: string; userInput?: Record<string, unknown> }) =>
      api.nextWorkflowStep(token!, id, userInput ?? {}),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ["workflow", id] });
    },
  });
}

export function useRewindWorkflow() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useMutation({
    mutationFn: (id: string) => api.rewindWorkflow(token!, id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["workflow", id] });
    },
  });
}
