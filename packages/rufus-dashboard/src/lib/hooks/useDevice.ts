"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import * as api from "@/lib/api";

export function useDeviceList() {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useQuery({
    queryKey: ["devices"],
    queryFn: () => api.listDevices(token!),
    enabled: !!token,
    refetchInterval: 15_000,
  });
}

export function useDevice(id: string) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useQuery({
    queryKey: ["device", id],
    queryFn: () => api.getDevice(token!, id),
    enabled: !!token && !!id,
    refetchInterval: 10_000,
  });
}

export function useSendCommand() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;

  return useMutation({
    mutationFn: ({
      deviceId,
      command,
    }: {
      deviceId: string;
      command: { command_type: string; payload: Record<string, unknown>; priority?: number };
    }) => api.sendDeviceCommand(token!, deviceId, command),
    onSuccess: (_, { deviceId }) => {
      queryClient.invalidateQueries({ queryKey: ["device", deviceId] });
    },
  });
}
