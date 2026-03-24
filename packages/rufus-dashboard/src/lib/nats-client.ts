/**
 * NATS WebSocket client for real-time dashboard updates.
 *
 * Replaces Redis pub/sub polling with direct NATS WebSocket subscriptions.
 * Activated when NEXT_PUBLIC_NATS_WS_URL is set in the environment.
 *
 * Subject hierarchy (mirroring server-side NATSBridge):
 *   workflow.events.{workflowId}   — per-workflow real-time step updates
 *   workflow.events.>              — all workflow events (admin page)
 *   devices.*.heartbeat            — device fleet live view
 *
 * Usage in a component:
 *   import { subscribeWorkflow } from "@/lib/nats-client";
 *
 *   useEffect(() => {
 *     let unsubscribe: (() => void) | undefined;
 *     subscribeWorkflow(workflowId, (event) => {
 *       setWorkflowState(event);
 *     }).then((fn) => { unsubscribe = fn; });
 *     return () => { unsubscribe?.(); };
 *   }, [workflowId]);
 *
 * Falls back gracefully (returns a no-op unsubscribe) when:
 *   - NEXT_PUBLIC_NATS_WS_URL is not set
 *   - NATS server is unreachable
 *   - nats.ws package is not available
 */

const NATS_WS_URL =
  process.env.NEXT_PUBLIC_NATS_WS_URL || "ws://localhost:8080";

/** Event payload shape from NATSEventObserver / EventPublisherObserver */
export interface WorkflowEvent {
  event_type: string;
  workflow_id: string;
  workflow_type?: string;
  timestamp: number;
  step_name?: string;
  step_index?: number;
  status?: string;
  result?: Record<string, unknown>;
  current_state?: Record<string, unknown>;
  old_status?: string;
  new_status?: string;
  error_message?: string;
  duration_ms?: number;
  [key: string]: unknown;
}

/** Heartbeat payload from edge devices */
export interface DeviceHeartbeatEvent {
  device_id?: string;
  device_status: string;
  pending_sync_count?: number;
  last_sync_at?: string;
  config_version?: string;
  sdk_version?: string;
  sent_at?: string;
}

type UnsubscribeFn = () => void;

// Singleton NATS connection shared across all subscriptions
let _nc: Awaited<ReturnType<typeof import("nats.ws").connect>> | null = null;
let _connecting: Promise<typeof _nc> | null = null;

async function getNatsConnection() {
  if (_nc && !_nc.isClosed()) return _nc;
  if (_connecting) return _connecting;

  _connecting = (async () => {
    try {
      const { connect } = await import("nats.ws");
      _nc = await connect({ servers: NATS_WS_URL });
      console.log(`[NATS] Connected to ${NATS_WS_URL}`);
      // Reset on close so next call reconnects
      (async () => {
        for await (const s of _nc!.status()) {
          if (s.type === "disconnect" || s.type === "close") {
            _nc = null;
            _connecting = null;
          }
        }
      })();
      return _nc;
    } catch (err) {
      console.warn("[NATS] Connection failed — real-time updates unavailable:", err);
      _nc = null;
      _connecting = null;
      return null;
    }
  })();

  return _connecting;
}

/**
 * Subscribe to real-time updates for a specific workflow.
 *
 * @param workflowId  Workflow execution ID
 * @param callback    Called with each event as it arrives
 * @returns           Unsubscribe function — call on component unmount
 */
export async function subscribeWorkflow(
  workflowId: string,
  callback: (event: WorkflowEvent) => void
): Promise<UnsubscribeFn> {
  const nc = await getNatsConnection();
  if (!nc) return () => {};

  const subject = `workflow.events.${workflowId}`;
  const { StringCodec } = await import("nats.ws");
  const sc = StringCodec();
  const sub = nc.subscribe(subject);

  (async () => {
    for await (const msg of sub) {
      try {
        const text = sc.decode(msg.data);
        // Strip envelope byte if present (0x01 JSON, 0x02 proto)
        const stripped = text.startsWith("\x01") ? text.slice(1) : text;
        const event: WorkflowEvent = JSON.parse(stripped);
        callback(event);
      } catch (e) {
        console.warn("[NATS] Failed to parse workflow event:", e);
      }
    }
  })();

  console.log(`[NATS] Subscribed to ${subject}`);
  return () => {
    sub.unsubscribe();
    console.log(`[NATS] Unsubscribed from ${subject}`);
  };
}

/**
 * Subscribe to live heartbeats from all edge devices in the fleet.
 *
 * @param callback    Called with each heartbeat as it arrives
 * @returns           Unsubscribe function
 */
export async function subscribeDeviceFleet(
  callback: (event: DeviceHeartbeatEvent) => void
): Promise<UnsubscribeFn> {
  const nc = await getNatsConnection();
  if (!nc) return () => {};

  const subject = "devices.*.heartbeat";
  const { StringCodec } = await import("nats.ws");
  const sc = StringCodec();
  const sub = nc.subscribe(subject);

  (async () => {
    for await (const msg of sub) {
      try {
        const text = sc.decode(msg.data);
        const stripped = text.startsWith("\x01") ? text.slice(1) : text;
        const event: DeviceHeartbeatEvent = JSON.parse(stripped);
        callback(event);
      } catch (e) {
        console.warn("[NATS] Failed to parse heartbeat event:", e);
      }
    }
  })();

  console.log(`[NATS] Subscribed to ${subject}`);
  return () => {
    sub.unsubscribe();
  };
}

/**
 * Subscribe to all workflow events across the system (admin / observability).
 *
 * @param callback    Called with each event as it arrives
 * @returns           Unsubscribe function
 */
export async function subscribeAllWorkflowEvents(
  callback: (event: WorkflowEvent) => void
): Promise<UnsubscribeFn> {
  const nc = await getNatsConnection();
  if (!nc) return () => {};

  const subject = "workflow.events.>";
  const { StringCodec } = await import("nats.ws");
  const sc = StringCodec();
  const sub = nc.subscribe(subject);

  (async () => {
    for await (const msg of sub) {
      try {
        const text = sc.decode(msg.data);
        const stripped = text.startsWith("\x01") ? text.slice(1) : text;
        const event: WorkflowEvent = JSON.parse(stripped);
        callback(event);
      } catch (e) {
        console.warn("[NATS] Failed to parse workflow event:", e);
      }
    }
  })();

  console.log(`[NATS] Subscribed to ${subject}`);
  return () => {
    sub.unsubscribe();
  };
}

/**
 * Close the shared NATS connection (call on app shutdown if needed).
 */
export async function closeNatsConnection(): Promise<void> {
  if (_nc && !_nc.isClosed()) {
    await _nc.drain();
    _nc = null;
    _connecting = null;
  }
}

/**
 * Whether NATS WebSocket is configured (NEXT_PUBLIC_NATS_WS_URL is set).
 * Use to conditionally enable real-time features in UI.
 */
export const isNatsEnabled =
  typeof process !== "undefined" &&
  !!process.env.NEXT_PUBLIC_NATS_WS_URL;
