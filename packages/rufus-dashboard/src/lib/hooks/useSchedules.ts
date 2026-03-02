"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import * as api from "@/lib/api";

function useToken() {
  const { data: session } = useSession();
  return (session as unknown as { accessToken?: string })?.accessToken;
}

export function useSchedules(params: { device_id?: string; status?: string } = {}) {
  const token = useToken();
  return useQuery({
    queryKey: ["schedules", params],
    queryFn: () => api.listSchedules(token!, { ...params, limit: 100 }),
    enabled: !!token,
    refetchInterval: 30_000,
  });
}

export function useCreateSchedule() {
  const queryClient = useQueryClient();
  const token = useToken();
  return useMutation({
    mutationFn: (body: Parameters<typeof api.createSchedule>[1]) =>
      api.createSchedule(token!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
  });
}

export function usePauseSchedule() {
  const queryClient = useQueryClient();
  const token = useToken();
  return useMutation({
    mutationFn: (id: string) => api.pauseSchedule(token!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
  });
}

export function useResumeSchedule() {
  const queryClient = useQueryClient();
  const token = useToken();
  return useMutation({
    mutationFn: (id: string) => api.resumeSchedule(token!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
  });
}

export function useCancelSchedule() {
  const queryClient = useQueryClient();
  const token = useToken();
  return useMutation({
    mutationFn: (id: string) => api.cancelSchedule(token!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    },
  });
}
