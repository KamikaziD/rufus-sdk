"use client";

import { useState } from "react";
import { useSendCommand } from "@/lib/hooks/useDevice";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { listDeviceCommands } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, Send, AlertCircle } from "lucide-react";
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

export function CommandSender({ deviceId }: CommandSenderProps) {
  const { data: session } = useSession();
  const token = (session as unknown as { accessToken?: string })?.accessToken;
  const sendCommand = useSendCommand();

  const [commandType, setCommandType] = useState("");
  const [payloadRaw, setPayloadRaw] = useState("{}");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const { data: cmdsData, isLoading } = useQuery({
    queryKey: ["device-commands", deviceId],
    queryFn: () => listDeviceCommands(token!, deviceId),
    enabled: !!token,
    refetchInterval: 10_000,
  });

  const commands = cmdsData?.commands ?? [];

  function validateJson(val: string) {
    try {
      JSON.parse(val);
      setJsonError(null);
    } catch {
      setJsonError("Invalid JSON payload");
    }
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!commandType || jsonError) return;
    const payload = JSON.parse(payloadRaw);
    await sendCommand.mutateAsync({ deviceId, command: { command_type: commandType, payload } });
    setCommandType("");
    setPayloadRaw("{}");
  }

  return (
    <div className="space-y-4">
      {/* Send command form */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Send Command</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={handleSend} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Command Type</label>
              <input
                type="text"
                placeholder="e.g. REBOOT, CONFIG_UPDATE, SAF_SYNC"
                value={commandType}
                onChange={(e) => setCommandType(e.target.value)}
                required
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Payload (JSON)</label>
              <textarea
                className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                value={payloadRaw}
                onChange={(e) => { setPayloadRaw(e.target.value); validateJson(e.target.value); }}
              />
              {jsonError && (
                <p className="text-xs text-destructive flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" /> {jsonError}
                </p>
              )}
            </div>
            {sendCommand.error && (
              <p className="text-xs text-destructive">{(sendCommand.error as Error).message}</p>
            )}
            <Button type="submit" size="sm" disabled={!commandType || !!jsonError || sendCommand.isPending}>
              {sendCommand.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
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
