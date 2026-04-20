"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, User } from "lucide-react";

interface HitlFormProps {
  workflowId: string;
  inputSchema?: Record<string, unknown>;
  stepName: string;
  onSubmit: (data: Record<string, unknown>) => void;
  isSubmitting?: boolean;
}

/** Derive a Zod schema from a JSON Schema object (shallow, best-effort). */
function deriveZodSchema(schema?: Record<string, unknown>): z.ZodObject<z.ZodRawShape> {
  if (!schema || typeof schema !== "object") return z.object({});
  const props = (schema.properties as Record<string, { type?: string; description?: string }>) ?? {};
  const shape: z.ZodRawShape = {};
  for (const [key, fieldDef] of Object.entries(props)) {
    if (fieldDef.type === "number" || fieldDef.type === "integer") {
      shape[key] = z.number().optional();
    } else if (fieldDef.type === "boolean") {
      shape[key] = z.boolean().optional();
    } else {
      shape[key] = z.string().optional();
    }
  }
  return z.object(shape);
}

export function HitlForm({
  workflowId,
  inputSchema,
  stepName,
  onSubmit,
  isSubmitting = false,
}: HitlFormProps) {
  const zodSchema = deriveZodSchema(inputSchema);
  const props = (inputSchema?.properties as Record<string, { type?: string; description?: string; title?: string }>) ?? {};
  const fields = Object.entries(props);

  const { register, handleSubmit, formState: { errors } } = useForm({
    resolver: zodResolver(zodSchema),
  });

  function onValid(data: Record<string, unknown>) {
    onSubmit(data);
  }

  // Fallback: no schema — just a freeform JSON textarea
  if (fields.length === 0) {
    return <FreeformHitlForm stepName={stepName} onSubmit={onSubmit} isSubmitting={isSubmitting} />;
  }

  return (
    <Card className="border-yellow-200 bg-yellow-50/30">
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <User className="h-4 w-4 text-yellow-500" />
          Human Input Required — {stepName}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onValid as Parameters<typeof handleSubmit>[0])} className="space-y-4">
          {fields.map(([key, fieldDef]) => {
            const label = fieldDef.title ?? key;
            const isBoolean = fieldDef.type === "boolean";
            const isNumber  = fieldDef.type === "number" || fieldDef.type === "integer";

            return (
              <div key={key} className="space-y-1.5">
                <label className="text-sm font-medium">{label}</label>
                {fieldDef.description && (
                  <p className="text-xs text-muted-foreground">{fieldDef.description}</p>
                )}
                {isBoolean ? (
                  <input type="checkbox" {...register(key)} className="h-4 w-4 rounded border-input" />
                ) : (
                  <input
                    type={isNumber ? "number" : "text"}
                    {...register(key, { valueAsNumber: isNumber })}
                    className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                    placeholder={fieldDef.description ?? label}
                  />
                )}
                {errors[key] && (
                  <p className="text-xs text-destructive">{(errors[key] as { message?: string })?.message}</p>
                )}
              </div>
            );
          })}

          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Submit
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function FreeformHitlForm({
  stepName,
  onSubmit,
  isSubmitting,
}: {
  stepName: string;
  onSubmit: (data: Record<string, unknown>) => void;
  isSubmitting: boolean;
}) {
  const { register, handleSubmit } = useForm<{ raw: string }>({
    defaultValues: { raw: "{}" },
  });

  function onValid({ raw }: { raw: string }) {
    try {
      onSubmit(JSON.parse(raw));
    } catch {
      onSubmit({});
    }
  }

  return (
    <Card className="border-yellow-200 bg-yellow-50/30">
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          <User className="h-4 w-4 text-yellow-500" />
          Human Input Required — {stepName}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onValid)} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Input (JSON)</label>
            <textarea
              {...register("raw")}
              className="flex min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
            />
          </div>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Submit
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
