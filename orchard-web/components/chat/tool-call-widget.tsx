"use client";

import * as React from "react";
import {
  Check,
  ChevronRight,
  Database,
  Loader2,
  ShieldCheck,
  Sprout,
  TriangleAlert,
} from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { toolPresentation } from "@/lib/agent/tools";
import type { ChatToolCall } from "@/lib/chat/types";

const TOOL_ICONS: Record<string, React.ReactNode> = {
  validateInput: <ShieldCheck className="size-3.5" />,
  listZones: <Database className="size-3.5" />,
  listTrees: <Database className="size-3.5" />,
  createTree: <Sprout className="size-3.5" />,
  updateZone: <Sprout className="size-3.5" />,
};

/**
 * Inline, collapsible status badge for a single agent tool call. Renders
 * "running" while the call is open and "done"/"failed" once a result lands.
 */
export function ToolCallWidget({ toolCall }: { toolCall: ChatToolCall }) {
  const { toolName, args, state, result } = toolCall;
  const presentation = toolPresentation(toolName);
  const isDone = state === "result";
  const failed =
    isDone &&
    !!result &&
    typeof result === "object" &&
    "ok" in (result as Record<string, unknown>) &&
    (result as { ok: unknown }).ok === false;

  return (
    <Collapsible className="my-1.5 rounded-md border bg-muted/40 text-xs">
      <CollapsibleTrigger
        className={cn(
          "group flex w-full items-center gap-2 px-2.5 py-1.5 text-left",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
        <span className="shrink-0 text-muted-foreground">
          {TOOL_ICONS[toolName] ?? <Database className="size-3.5" />}
        </span>
        <span className="flex-1 truncate font-medium">
          {isDone ? presentation.done : presentation.running}
        </span>
        {!isDone && (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
        )}
        {isDone && !failed && (
          <Badge variant="success" className="shrink-0 gap-1 py-0">
            <Check className="size-3" /> done
          </Badge>
        )}
        {failed && (
          <Badge variant="destructive" className="shrink-0 gap-1 py-0">
            <TriangleAlert className="size-3" /> failed
          </Badge>
        )}
      </CollapsibleTrigger>

      <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
        <div className="space-y-2 border-t px-2.5 py-2">
          <JsonBlock label="Arguments" value={args} />
          {isDone && <JsonBlock label="Result" value={result} />}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value === undefined) return null;
  return (
    <div>
      <p className="mb-1 font-semibold text-muted-foreground">{label}</p>
      <pre className="max-h-48 overflow-auto rounded bg-background p-2 text-[11px] leading-relaxed">
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
