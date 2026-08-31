"use client";

import * as React from "react";
import { Bot, SendHorizonal, Square, X, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { APPROVAL, type ApprovalDecision } from "@/lib/agent/tools";
import { useOrchardChat } from "@/lib/chat/use-orchard-chat";
import { ChatMessage } from "./chat-message";

const SUGGESTIONS = [
  "Which zones have unknown soil drainage?",
  "How old is the oldest mango tree?",
  "Summarize what needs attention this week",
];

export function ChatDrawer({ onClose }: { onClose?: () => void }) {
  const { messages, status, send, stop, reset, resolveToolCall } =
    useOrchardChat();
  const [input, setInput] = React.useState("");
  const busy = status === "streaming";
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    void send(input);
    setInput("");
  }

  function onToolDecision(toolCallId: string, decision: ApprovalDecision) {
    resolveToolCall(
      toolCallId,
      decision === APPROVAL.YES ? "approved by user" : "rejected by user",
    );
  }

  return (
    <section
      aria-label="Orchard assistant"
      className="flex h-full flex-col border-l bg-card"
    >
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <span className="flex size-7 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Bot className="size-4" />
        </span>
        <div className="flex-1">
          <p className="text-sm font-semibold">Orchard Assistant</p>
          <p className="text-xs text-muted-foreground">
            {busy ? "Working…" : "Streamed over SSE · stub reply"}
          </p>
        </div>
        {messages.length > 0 && (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Clear conversation"
            onClick={reset}
            disabled={busy}
          >
            <RotateCcw className="size-4" />
          </Button>
        )}
        {onClose && (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close assistant"
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        )}
      </header>

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="space-y-3 pt-6 text-center">
            <p className="text-sm text-muted-foreground">
              The assistant streams responses from{" "}
              <code className="rounded bg-muted px-1">orchard-server</code> over
              SSE. It currently returns a stub reply — no model is connected.
            </p>
            <div className="flex flex-col gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => void send(s)}
                  className="rounded-md border px-3 py-2 text-left text-xs transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => (
          <ChatMessage
            key={message.id}
            message={message}
            busy={busy}
            onToolDecision={onToolDecision}
          />
        ))}

        {status === "error" && (
          <p
            role="alert"
            className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
          >
            The assistant stream failed. Check that orchard-server is running,
            then try again.
          </p>
        )}
      </div>

      <form
        onSubmit={onSubmit}
        className="flex items-center gap-2 border-t p-3"
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message the orchard assistant…"
          aria-label="Message the orchard assistant"
          disabled={busy}
          autoComplete="off"
        />
        {busy ? (
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Stop generating"
            onClick={stop}
          >
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            aria-label="Send message"
            disabled={!input.trim()}
          >
            <SendHorizonal className="size-4" />
          </Button>
        )}
      </form>
    </section>
  );
}
