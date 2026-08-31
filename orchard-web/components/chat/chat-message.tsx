"use client";

import { Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { isHumanApprovalTool, type ApprovalDecision } from "@/lib/agent/tools";
import type { ChatMessage as ChatMessageT } from "@/lib/chat/types";
import { ToolCallWidget } from "./tool-call-widget";
import { ApprovalCard } from "./approval-card";

interface ChatMessageProps {
  message: ChatMessageT;
  onToolDecision: (toolCallId: string, decision: ApprovalDecision) => void;
  busy: boolean;
}

export function ChatMessage({
  message,
  onToolDecision,
  busy,
}: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-secondary" : "bg-primary text-primary-foreground",
        )}
        aria-hidden
      >
        {isUser ? <User className="size-4" /> : <Bot className="size-4" />}
      </div>

      <div
        className={cn(
          "min-w-0 max-w-[85%] space-y-1 rounded-lg px-3 py-2 text-sm",
          isUser ? "bg-secondary text-secondary-foreground" : "border bg-muted/50",
        )}
      >
        <span className="sr-only">
          {isUser ? "You" : "Orchard Assistant"}:{" "}
        </span>

        {message.content && (
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        )}

        {message.toolCalls?.map((tc) => {
          const awaitingApproval =
            tc.state === "call" && isHumanApprovalTool(tc.toolName);

          return awaitingApproval ? (
            <ApprovalCard
              key={tc.toolCallId}
              toolCall={tc}
              disabled={busy}
              onDecision={(decision) => onToolDecision(tc.toolCallId, decision)}
            />
          ) : (
            <ToolCallWidget key={tc.toolCallId} toolCall={tc} />
          );
        })}
      </div>
    </div>
  );
}
