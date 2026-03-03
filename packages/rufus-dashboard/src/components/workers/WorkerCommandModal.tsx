"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQueryClient } from "@tanstack/react-query";
import { sendWorkerCommand, broadcastWorkerCommand } from "@/lib/api";
import { Button } from "@/components/ui/button";

const COMMAND_TYPES = [
  "restart",
  "pool_restart",
  "drain",
  "update_code",
  "update_config",
  "pause_queue",
  "resume_queue",
  "set_concurrency",
  "check_health",
] as const;

type CommandType = typeof COMMAND_TYPES[number];

const PRIORITIES = ["low", "normal", "high", "critical"] as const;

const INPUT_CLS = "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm";
const SELECT_CLS = INPUT_CLS;

type SingleProps = {
  open: boolean;
  onClose: () => void;
  mode: "single";
  workerId: string;
  workerHostname: string;
};

type BroadcastProps = {
  open: boolean;
  onClose: () => void;
  mode: "broadcast";
  targetFilter?: Record<string, unknown>;
};

type WorkerCommandModalProps = SingleProps | BroadcastProps;

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}

function CommandDataFields({
  commandType,
  commandData,
  setCommandData,
}: {
  commandType: CommandType;
  commandData: Record<string, unknown>;
  setCommandData: (d: Record<string, unknown>) => void;
}) {
  function set(key: string, value: unknown) {
    setCommandData({ ...commandData, [key]: value });
  }

  switch (commandType) {
    case "restart":
      return (
        <FieldWrap label="Delay (seconds)">
          <input
            type="number"
            min={0}
            className={INPUT_CLS}
            value={(commandData.delay_seconds as number) ?? 5}
            onChange={(e) => set("delay_seconds", Number(e.target.value))}
          />
        </FieldWrap>
      );

    case "drain":
      return (
        <>
          <FieldWrap label="Queue">
            <input
              className={INPUT_CLS}
              value={(commandData.queue as string) ?? "default"}
              onChange={(e) => set("queue", e.target.value)}
            />
          </FieldWrap>
          <FieldWrap label="Wait (seconds)">
            <input
              type="number"
              min={0}
              className={INPUT_CLS}
              value={(commandData.wait_seconds as number) ?? 60}
              onChange={(e) => set("wait_seconds", Number(e.target.value))}
            />
          </FieldWrap>
        </>
      );

    case "update_code": {
      const isWheel = !!(commandData.wheel_url);
      return (
        <>
          <FieldWrap label="Install method">
            <select
              className={SELECT_CLS}
              value={isWheel ? "wheel" : "pypi"}
              onChange={(e) => {
                if (e.target.value === "wheel") {
                  setCommandData({ wheel_url: "" });
                } else {
                  setCommandData({ package: "", version: "" });
                }
              }}
            >
              <option value="pypi">PyPI package</option>
              <option value="wheel">Wheel URL</option>
            </select>
          </FieldWrap>
          {isWheel ? (
            <FieldWrap label="Wheel URL">
              <input
                className={INPUT_CLS}
                value={(commandData.wheel_url as string) ?? ""}
                onChange={(e) => set("wheel_url", e.target.value)}
                placeholder="https://example.com/package-1.0-py3-none-any.whl"
              />
            </FieldWrap>
          ) : (
            <>
              <FieldWrap label="Package name">
                <input
                  className={INPUT_CLS}
                  value={(commandData.package as string) ?? ""}
                  onChange={(e) => set("package", e.target.value)}
                  placeholder="rufus-sdk"
                />
              </FieldWrap>
              <FieldWrap label="Version">
                <input
                  className={INPUT_CLS}
                  value={(commandData.version as string) ?? ""}
                  onChange={(e) => set("version", e.target.value)}
                  placeholder="0.7.3"
                />
              </FieldWrap>
              <FieldWrap label="Index URL (optional)">
                <input
                  className={INPUT_CLS}
                  value={(commandData.index_url as string) ?? ""}
                  onChange={(e) => set("index_url", e.target.value || undefined)}
                  placeholder="https://test.pypi.org/simple/"
                />
              </FieldWrap>
            </>
          )}
        </>
      );
    }

    case "update_config": {
      const caps = (commandData.capabilities as Record<string, string>) ?? {};
      const entries = Object.entries(caps);
      return (
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">Capability key-value pairs</label>
          {entries.map(([k, v], i) => (
            <div key={i} className="flex gap-2 items-center">
              <input
                className={INPUT_CLS}
                placeholder="key"
                value={k}
                onChange={(e) => {
                  const newCaps = { ...caps };
                  delete newCaps[k];
                  if (e.target.value) newCaps[e.target.value] = v;
                  set("capabilities", newCaps);
                }}
              />
              <input
                className={INPUT_CLS}
                placeholder="value"
                value={v}
                onChange={(e) => {
                  set("capabilities", { ...caps, [k]: e.target.value });
                }}
              />
              <button
                type="button"
                className="text-destructive text-sm px-2"
                onClick={() => {
                  const newCaps = { ...caps };
                  delete newCaps[k];
                  set("capabilities", newCaps);
                }}
              >
                ×
              </button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => set("capabilities", { ...caps, "": "" })}
          >
            + Add key
          </Button>
        </div>
      );
    }

    case "pause_queue":
    case "resume_queue":
      return (
        <FieldWrap label="Queue">
          <input
            className={INPUT_CLS}
            value={(commandData.queue as string) ?? "default"}
            onChange={(e) => set("queue", e.target.value)}
          />
        </FieldWrap>
      );

    case "set_concurrency":
      return (
        <>
          <FieldWrap label="Direction">
            <div className="flex gap-4 pt-1">
              {["grow", "shrink"].map((d) => (
                <label key={d} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="radio"
                    name="direction"
                    value={d}
                    checked={(commandData.direction as string) === d}
                    onChange={() => set("direction", d)}
                  />
                  {d.charAt(0).toUpperCase() + d.slice(1)}
                </label>
              ))}
            </div>
          </FieldWrap>
          <FieldWrap label="N (workers)">
            <input
              type="number"
              min={1}
              className={INPUT_CLS}
              value={(commandData.n as number) ?? 1}
              onChange={(e) => set("n", Number(e.target.value))}
            />
          </FieldWrap>
        </>
      );

    // pool_restart and check_health have no extra fields
    default:
      return null;
  }
}

export function WorkerCommandModal(props: WorkerCommandModalProps) {
  const { open, onClose } = props;
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const queryClient = useQueryClient();

  const [commandType, setCommandType] = useState<CommandType>("check_health");
  const [commandData, setCommandData] = useState<Record<string, unknown>>({});
  const [priority, setPriority] = useState<string>("normal");
  const [expiresIn, setExpiresIn] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function resetForm() {
    setCommandType("check_health");
    setCommandData({});
    setPriority("normal");
    setExpiresIn("");
    setError(null);
    setSuccess(null);
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);

    const body = {
      command_type: commandType,
      command_data: Object.keys(commandData).length ? commandData : undefined,
      priority,
      expires_in_seconds: expiresIn ? Number(expiresIn) : undefined,
    };

    try {
      if (props.mode === "single") {
        await sendWorkerCommand(token, props.workerId, body);
        queryClient.invalidateQueries({ queryKey: ["worker", props.workerId] });
        queryClient.invalidateQueries({ queryKey: ["worker-commands", props.workerId] });
        queryClient.invalidateQueries({ queryKey: ["workers"] });
        setSuccess(`Command "${commandType}" sent to ${props.workerHostname}`);
      } else {
        await broadcastWorkerCommand(token, {
          ...body,
          target_filter: props.targetFilter,
        });
        queryClient.invalidateQueries({ queryKey: ["workers"] });
        setSuccess(`Broadcast "${commandType}" queued for all matching workers`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send command");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  const title = props.mode === "broadcast"
    ? "Broadcast Command"
    : `Send Command — ${props.workerHostname}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={handleClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-md rounded-lg border bg-background shadow-lg">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h2 className="font-semibold text-sm">{title}</h2>
          <button
            onClick={handleClose}
            className="text-muted-foreground hover:text-foreground text-lg leading-none"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {success ? (
            <div className="rounded-md bg-green-50 border border-green-200 p-3 text-sm text-green-700">
              {success}
            </div>
          ) : (
            <>
              <FieldWrap label="Command type">
                <select
                  className={SELECT_CLS}
                  value={commandType}
                  onChange={(e) => {
                    setCommandType(e.target.value as CommandType);
                    setCommandData({});
                  }}
                >
                  {COMMAND_TYPES.map((t) => (
                    <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </FieldWrap>

              <CommandDataFields
                commandType={commandType}
                commandData={commandData}
                setCommandData={setCommandData}
              />

              <div className="grid grid-cols-2 gap-3">
                <FieldWrap label="Priority">
                  <select
                    className={SELECT_CLS}
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </FieldWrap>
                <FieldWrap label="Expires in (seconds, optional)">
                  <input
                    type="number"
                    min={1}
                    className={INPUT_CLS}
                    value={expiresIn}
                    onChange={(e) => setExpiresIn(e.target.value)}
                    placeholder="e.g. 300"
                  />
                </FieldWrap>
              </div>

              {error && (
                <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
                  {error}
                </div>
              )}
            </>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" size="sm" onClick={handleClose}>
              {success ? "Close" : "Cancel"}
            </Button>
            {!success && (
              <Button type="submit" size="sm" disabled={submitting || !token}>
                {submitting ? "Sending…" : "Send Command"}
              </Button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
