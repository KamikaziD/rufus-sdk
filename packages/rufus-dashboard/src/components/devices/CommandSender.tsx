"use client";

import { useState } from "react";
import { useSendCommand } from "@/lib/hooks/useDevice";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { listDeviceCommands } from "@/lib/api";
import { Send, AlertCircle, CheckCircle2 } from "lucide-react";
import { formatRelativeTime } from "@/lib/utils";

interface CommandSenderProps {
  deviceId: string;
}

const STATUS_CLS: Record<string, string> = {
  pending:      "border-zinc-600 text-zinc-500",
  sent:         "border-blue-500/40 text-blue-400",
  acknowledged: "border-emerald-500/40 text-emerald-400",
  failed:       "border-red-500/40 text-red-400",
};

const COMMAND_TYPES = ["force_sync", "reload_config", "update_workflow", "update_model"] as const;
type CommandType = typeof COMMAND_TYPES[number];

const PRIORITIES = ["low", "normal", "high", "critical"] as const;

const INPUT_CLS = "flex h-9 w-full border border-[#1E1E22] bg-[#0A0A0B] px-3 py-1 font-mono text-sm text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50 transition-colors";
const SELECT_CLS = INPUT_CLS;

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">{label}</label>
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
  if (commandType === "force_sync" || commandType === "reload_config") {
    return null;
  }

  if (commandType === "update_workflow") {
    return (
      <>
        <FieldWrap label="Workflow type">
          <input
            type="text"
            required
            className={INPUT_CLS}
            placeholder="e.g. PaymentWorkflow"
            value={(commandData.workflow_type as string) ?? ""}
            onChange={(e) =>
              setCommandData({ ...commandData, workflow_type: e.target.value })
            }
          />
        </FieldWrap>
        <FieldWrap label="YAML content">
          <textarea
            required
            rows={6}
            className="flex w-full border border-[#1E1E22] bg-[#0A0A0B] px-3 py-2 font-mono text-sm text-[#E4E4E7] rounded-none focus:outline-none focus:border-amber-500/50 transition-colors"
            placeholder="Paste workflow YAML here..."
            value={(commandData.yaml_content as string) ?? ""}
            onChange={(e) =>
              setCommandData({ ...commandData, yaml_content: e.target.value })
            }
          />
        </FieldWrap>
        <FieldWrap label="Version (optional)">
          <input
            type="text"
            className={INPUT_CLS}
            placeholder="e.g. 1.2.0"
            value={(commandData.version as string) ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              const next = { ...commandData };
              if (v) next.version = v; else delete next.version;
              setCommandData(next);
            }}
          />
        </FieldWrap>
      </>
    );
  }

  if (commandType === "update_model") {
    return (
      <FieldWrap label="Model name">
        <input
          type="text"
          className={INPUT_CLS}
          placeholder="e.g. fraud_detector_v2"
          value={(commandData.model_name as string) ?? ""}
          onChange={(e) =>
            setCommandData({ ...commandData, model_name: e.target.value })
          }
        />
      </FieldWrap>
    );
  }

  return null;
}

export function CommandSender({ deviceId }: CommandSenderProps) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const sendCommand = useSendCommand();

  const [commandType, setCommandType] = useState<CommandType>("force_sync");
  const [commandData, setCommandData] = useState<Record<string, unknown>>({});
  const [priority, setPriority] = useState("normal");
  const [expiresIn, setExpiresIn] = useState("");
  const [success, setSuccess] = useState<string | null>(null);

  const { data: cmdsData, isLoading } = useQuery({
    queryKey: ["device-commands", deviceId],
    queryFn: () => listDeviceCommands(token!, deviceId),
    enabled: !!token,
    refetchInterval: 10_000,
  });

  const commands = cmdsData?.commands ?? [];

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setSuccess(null);
    await sendCommand.mutateAsync({
      deviceId,
      command: {
        type: commandType,
        data: Object.keys(commandData).length ? commandData : undefined,
        priority,
        expires_in_seconds: expiresIn ? Number(expiresIn) : undefined,
      },
    });
    setSuccess(`Command "${commandType}" queued`);
    setCommandData({});
    setExpiresIn("");
  }

  return (
    <div className="space-y-4">
      {/* Send command form */}
      <div className="bg-[#111113] border border-[#1E1E22] p-4">
        <div className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest mb-3">SEND COMMAND</div>
        <form onSubmit={handleSend} className="space-y-4">
          <FieldWrap label="Command type">
            <select
              className={SELECT_CLS}
              value={commandType}
              onChange={(e) => {
                setCommandType(e.target.value as CommandType);
                setCommandData({});
                setSuccess(null);
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
                className={INPUT_CLS}
                placeholder="e.g. 300"
                value={expiresIn}
                onChange={(e) => setExpiresIn(e.target.value)}
                min={1}
              />
            </FieldWrap>
          </div>

          {sendCommand.error && (
            <p className="font-mono text-xs text-red-400 flex items-center gap-1">
              <AlertCircle className="h-3 w-3" />
              {(sendCommand.error as Error).message}
            </p>
          )}
          {success && (
            <p className="font-mono text-xs text-emerald-400 flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />
              {success}
            </p>
          )}

          <button
            type="submit"
            disabled={sendCommand.isPending}
            className="border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 font-mono text-xs px-3 py-1.5 rounded-none flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="h-3.5 w-3.5" />
            {sendCommand.isPending ? "Sending…" : "Send Command"}
          </button>
        </form>
      </div>

      {/* Command history */}
      <div className="bg-[#111113] border border-[#1E1E22]">
        <div className="px-4 py-3 border-b border-[#1E1E22]">
          <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">COMMAND HISTORY</span>
        </div>
        {isLoading ? (
          <div className="p-4 space-y-2">
            {[...Array(3)].map((_, i) => <div key={i} className="h-8 animate-pulse bg-[#1E1E22]" />)}
          </div>
        ) : commands.length === 0 ? (
          <p className="px-4 py-6 font-mono text-xs text-zinc-600 text-center">No commands sent yet</p>
        ) : (
          <div className="divide-y divide-[#1E1E22]">
            {commands.map((cmd) => (
              <div key={cmd.command_id} className="flex items-center justify-between px-4 py-2.5">
                <div>
                  <span className="font-mono text-xs text-zinc-300">{cmd.command_type}</span>
                  <span className="font-mono text-[10px] text-zinc-600 ml-2">{formatRelativeTime(cmd.created_at)}</span>
                </div>
                <span className={`font-mono text-[10px] border px-1.5 py-0.5 rounded-none ${STATUS_CLS[cmd.status] ?? "border-zinc-600 text-zinc-500"}`}>
                  {cmd.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
