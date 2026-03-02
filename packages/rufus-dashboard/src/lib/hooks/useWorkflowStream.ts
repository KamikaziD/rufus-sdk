"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useSession } from "next-auth/react";

const API_BASE = process.env.NEXT_PUBLIC_RUFUS_API_URL ?? "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

type StreamMessage = {
  type: string;
  workflow_id?: string;
  status?: string;
  step?: string;
  state?: Record<string, unknown>;
  [key: string]: unknown;
};

interface UseWorkflowStreamOptions {
  workflowId?: string;
  onMessage?: (msg: StreamMessage) => void;
}

export function useWorkflowStream({ workflowId, onMessage }: UseWorkflowStreamOptions) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<StreamMessage | null>(null);

  const connect = useCallback(() => {
    if (!token) return;

    const url = workflowId
      ? `${WS_BASE}/api/v1/subscribe/${workflowId}?token=${token}`
      : `${WS_BASE}/api/v1/subscribe?token=${token}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      // Reconnect after 3s
      setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      try {
        const msg: StreamMessage = JSON.parse(event.data);
        setLastMessage(msg);
        onMessage?.(msg);
      } catch {}
    };

    return () => {
      ws.onclose = null; // prevent reconnect on intentional close
      ws.close();
    };
  }, [token, workflowId, onMessage]);

  useEffect(() => {
    const cleanup = connect();
    return () => {
      wsRef.current?.close();
      cleanup?.();
    };
  }, [connect]);

  return { connected, lastMessage };
}
