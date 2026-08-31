"use client";

import * as React from "react";
import { Check, X, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { APPROVAL, type ApprovalDecision } from "@/lib/agent/tools";
import type { ChatToolCall } from "@/lib/chat/types";

const TITLES: Record<string, string> = {
  deleteZone: "Delete zone",
  triggerIrrigation: "Trigger irrigation",
};

/**
 * Human-in-the-loop confirmation card, rendered inline in the message stream
 * when the agent calls a high-impact tool. The decision is reported back so
 * the caller can resolve the tool call (and, with a real agent wired up,
 * continue the conversation).
 */
export function ApprovalCard({
  toolCall,
  onDecision,
  disabled,
}: {
  toolCall: ChatToolCall;
  onDecision: (decision: ApprovalDecision) => void;
  disabled?: boolean;
}) {
  const title = TITLES[toolCall.toolName] ?? toolCall.toolName;

  return (
    <div
      role="group"
      aria-label={`Approval required: ${title}`}
      className="my-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3"
    >
      <div className="flex items-center gap-2">
        <ShieldAlert className="size-4 text-destructive" />
        <p className="text-sm font-semibold">{title}</p>
        <span className="ml-auto rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-medium text-destructive">
          approval required
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {Object.entries(toolCall.args ?? {}).map(([key, value]) => (
          <React.Fragment key={key}>
            <dt className="font-medium text-muted-foreground">{key}</dt>
            <dd className="break-words">
              {typeof value === "string" ? value : JSON.stringify(value)}
            </dd>
          </React.Fragment>
        ))}
      </dl>

      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="success"
          disabled={disabled}
          onClick={() => onDecision(APPROVAL.YES)}
        >
          <Check /> Approve
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => onDecision(APPROVAL.NO)}
        >
          <X /> Reject
        </Button>
      </div>
    </div>
  );
}
