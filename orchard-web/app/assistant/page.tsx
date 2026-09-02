"use client";

import * as React from "react";
import {
  Bot,
  PanelLeft,
  Paperclip,
  Plus,
  SendHorizonal,
  Square,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { APPROVAL, type ApprovalDecision } from "@/lib/agent/tools";
import { useOrchardChat } from "@/lib/chat/use-orchard-chat";
import { ChatMessage } from "@/components/chat/chat-message";
import {
  ConversationRail,
  type ConversationRailHandle,
} from "@/components/chat/conversation-rail";

const SUGGESTIONS = [
  "Why are my young mango's leaves turning yellow?",
  "According to my notes, how often should I water a citrus tree?",
  "Plan my orchard work for this afternoon",
  "I finished tasks 3 and 5",
];

export default function AssistantPage() {
  const railRef = React.useRef<ConversationRailHandle>(null);
  const {
    messages,
    status,
    conversationId,
    send,
    stop,
    newChat,
    loadConversation,
    resolveToolCall,
  } = useOrchardChat({ onConversation: () => railRef.current?.refresh() });
  const [input, setInput] = React.useState("");
  const [railOpen, setRailOpen] = React.useState(false);
  const busy = status === "streaming";
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const doSend = () => {
    const text = input.trim();
    if (!text || busy) return;
    void send(text);
    setInput("");
  };

  const pickConversation = (id: number) => {
    void loadConversation(id);
    setRailOpen(false);
  };

  const startNew = () => {
    newChat();
    setRailOpen(false);
  };

  const onToolDecision = (id: string, decision: ApprovalDecision) =>
    resolveToolCall(
      id,
      decision === APPROVAL.YES ? "approved by user" : "rejected by user",
    );

  return (
    <div className="flex h-full">
      {/* history rail - persistent on md+, slide-over on mobile */}
      <div className="hidden md:flex">
        <ConversationRail
          ref={railRef}
          activeId={conversationId}
          onSelect={pickConversation}
          onNew={startNew}
        />
      </div>
      {railOpen && (
        <div className="fixed inset-0 z-30 flex md:hidden">
          <ConversationRail
            ref={railRef}
            activeId={conversationId}
            onSelect={pickConversation}
            onNew={startNew}
          />
          <button
            type="button"
            aria-label="Close history"
            className="flex-1 bg-black/30"
            onClick={() => setRailOpen(false)}
          />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b px-4 py-3">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label="Conversation history"
            onClick={() => setRailOpen(true)}
          >
            <PanelLeft className="size-4" />
          </Button>
          <span className="flex size-7 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Bot className="size-4" />
          </span>
          <h1 className="flex-1 text-sm font-semibold">Assistant</h1>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-1.5"
            onClick={startNew}
            disabled={messages.length === 0 && conversationId === null}
          >
            <Plus className="size-4" />
            New
          </Button>
          <StatusIndicator status={status} />
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-4 py-6">
            {messages.length === 0 ? (
              <EmptyState onPick={(s) => void send(s)} />
            ) : (
              <div className="space-y-6">
                {messages.map((message) => (
                  <ChatMessage
                    key={message.id}
                    message={message}
                    busy={busy}
                    onToolDecision={onToolDecision}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="border-t bg-background">
          <form
            className="mx-auto max-w-3xl px-4 py-3"
            onSubmit={(e) => {
              e.preventDefault();
              doSend();
            }}
          >
            <div className="flex items-end gap-1.5 rounded-2xl border bg-card p-1.5 shadow-sm focus-within:ring-2 focus-within:ring-ring">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                aria-label="Attach file (coming soon)"
                disabled
              >
                <Paperclip className="size-4" />
              </Button>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    doSend();
                  }
                }}
                rows={1}
                placeholder="Message the orchard assistant…"
                aria-label="Message the orchard assistant"
                className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-1 py-2 text-sm outline-none placeholder:text-muted-foreground"
              />
              {busy ? (
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  className="shrink-0"
                  onClick={stop}
                  aria-label="Stop generating"
                >
                  <Square className="size-4" />
                </Button>
              ) : (
                <Button
                  type="submit"
                  size="icon"
                  className="shrink-0"
                  disabled={!input.trim()}
                  aria-label="Send message"
                >
                  <SendHorizonal className="size-4" />
                </Button>
              )}
            </div>
            <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
              Local model · streamed from orchard-server over SSE
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}

function StatusIndicator({
  status,
}: {
  status: "ready" | "streaming" | "error";
}) {
  const map = {
    ready: { dot: "bg-success", label: "Ready" },
    streaming: { dot: "bg-amber-500 animate-pulse", label: "Thinking…" },
    error: { dot: "bg-destructive", label: "Error" },
  } as const;
  const { dot, label } = map[status];
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn("size-2 rounded-full", dot)} />
      {label}
    </span>
  );
}

function EmptyState({ onPick }: { onPick: (s: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-6 pt-16 text-center">
      <span className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Bot className="size-6" />
      </span>
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">How can I help with the orchard?</h2>
        <p className="text-sm text-muted-foreground">
          I answer agronomy questions from your notes, mark tasks done, and open
          the planner when you want to schedule a work session.
        </p>
      </div>
      <div className="grid w-full gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="rounded-lg border px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
