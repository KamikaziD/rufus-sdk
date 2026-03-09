"use client";

import { useState } from "react";
import { useSendCommand } from "@/lib/hooks/useDevice";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { listDeviceCommands } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, Send, AlertCircle, CheckCircle2 } from "lucide-react";
import { formatRelativeTime } from "@/lib/utils";

interface CommandSenderProps {
  deviceId: string;
}

const STATUS_VARIANT: Record<string, "success" | "destructive" | "secondary" | "info"> = {
  pending:      "secondary",
  sent:         "info",
  acknowledged: "success",
  failed:       "destructive",
};

const COMMAND_TYPES = ["force_sync", "reload_config", "update_workflow", "update_model"] as const;
type CommandType = typeof COMMAND_TYPES[number];

const PRIORITIES = ["low", "normal", "high", "critical"] as const;

const INPUT_CLS = "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const SELECT_CLS = INPUT_CLS;

function FieldWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
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
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
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
      <Card>
        <CardHeader><CardTitle className="text-sm">Send Command</CardTitle></CardHeader>
        <CardContent>
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
              <p className="text-xs text-destructive flex items-center gap-1">
                <AlertCircle className="h-3 w-3" />
                {(sendCommand.error as Error).message}
              </p>
            )}
            {success && (
              <p className="text-xs text-green-600 flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                {success}
              </p>
            )}

            <Button type="submit" size="sm" disabled={sendCommand.isPending}>
              {sendCommand.isPending
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <Send className="h-3.5 w-3.5" />}
              Send Command
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Command history */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Command History</CardTitle></CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {[...Array(3)].map((_, i) => <div key={i} className="h-8 animate-pulse bg-muted rounded" />)}
            </div>
          ) : commands.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground text-center">No commands sent yet</p>
          ) : (
            <div className="divide-y">
              {commands.map((cmd) => (
                <div key={cmd.command_id} className="flex items-center justify-between px-4 py-2 text-sm">
                  <div>
                    <span className="font-medium">{cmd.command_type}</span>
                    <span className="text-xs text-muted-foreground ml-2">{formatRelativeTime(cmd.created_at)}</span>
                  </div>
                  <Badge variant={STATUS_VARIANT[cmd.status] ?? "secondary"}>{cmd.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
