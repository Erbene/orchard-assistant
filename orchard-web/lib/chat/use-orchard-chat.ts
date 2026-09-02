"use client";

import * as React from "react";
import { conversationsApi } from "@/lib/api";
import type {
  ChatMessage,
  ChatStreamEvent,
  ChatToolCall,
} from "./types";

type Status = "ready" | "streaming" | "error";

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

interface Options {
  /** Fired when a turn resolves its conversation (new id, or a fresh title). */
  onConversation?: (c: { id: number; title: string; isNew: boolean }) => void;
}

/**
 * Chat hook. History is server-owned: we POST `{ conversation_id, message }`
 * to `/api/chat` and consume the SSE stream. The `conversation` event carries
 * the thread id (assigned on the first turn). No external SDK - fetch + stream.
 */
export function useOrchardChat({ onConversation }: Options = {}) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [status, setStatus] = React.useState<Status>("ready");
  const [conversationId, setConversationId] = React.useState<number | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);

  const stop = React.useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("ready");
  }, []);

  const newChat = React.useCallback(() => {
    stop();
    setMessages([]);
    setConversationId(null);
    setStatus("ready");
  }, [stop]);

  /** Load a past thread into the view. */
  const loadConversation = React.useCallback(
    async (id: number) => {
      stop();
      const detail = await conversationsApi.get(id);
      setConversationId(detail.id);
      setMessages(
        detail.messages.map((m): ChatMessage => ({
          id: String(m.id),
          role: m.role,
          content: m.content,
          toolCalls: m.meta.tool_calls?.map((tc): ChatToolCall => ({
            toolCallId: uid(),
            toolName: tc.tool,
            args: tc.args,
            state: "result",
            result: tc.result,
          })),
          redirect: m.meta.redirect,
        })),
      );
      setStatus("ready");
    },
    [stop],
  );

  const patchAssistant = React.useCallback(
    (id: string, fn: (m: ChatMessage) => ChatMessage) => {
      setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));
    },
    [],
  );

  const send = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || status === "streaming") return;

      const userMsg: ChatMessage = { id: uid(), role: "user", content: trimmed };
      const assistantId = uid();

      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: assistantId, role: "assistant", content: "" },
      ]);
      setStatus("streaming");

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            conversation_id: conversationId,
            message: trimmed,
          }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          throw new Error(`Chat request failed (${res.status})`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const apply = (evt: ChatStreamEvent) => {
          if (evt.type === "conversation") {
            setConversationId(evt.id);
            onConversation?.({ id: evt.id, title: evt.title, isNew: evt.new });
          } else if (evt.type === "text-delta") {
            patchAssistant(assistantId, (m) => ({
              ...m,
              content: m.content + evt.delta,
            }));
          } else if (evt.type === "tool") {
            patchAssistant(assistantId, (m) => ({
              ...m,
              toolCalls: [
                ...(m.toolCalls ?? []),
                {
                  toolCallId: uid(),
                  toolName: evt.toolName,
                  args: evt.args,
                  state: "result",
                  result: evt.result,
                },
              ],
            }));
          } else if (evt.type === "redirect") {
            patchAssistant(assistantId, (m) => ({
              ...m,
              redirect: { href: evt.href, label: evt.label },
            }));
          } else if (evt.type === "error") {
            throw new Error(evt.error);
          }
        };

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const dataLine = frame
              .split("\n")
              .find((l) => l.startsWith("data:"));
            if (!dataLine) continue;
            const json = dataLine.slice(dataLine.indexOf(":") + 1).trim();
            if (!json || json === "[DONE]") continue;
            apply(JSON.parse(json) as ChatStreamEvent);
          }
        }
        setStatus("ready");
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setStatus("error");
        patchAssistant(assistantId, (m) =>
          m.content
            ? m
            : { ...m, content: "⚠ Could not reach the orchard assistant." },
        );
      } finally {
        abortRef.current = null;
      }
    },
    [conversationId, status, patchAssistant, onConversation],
  );

  /** Resolve a rendered tool call (used by the HITL approval card). */
  const resolveToolCall = React.useCallback(
    (toolCallId: string, result: unknown) => {
      setMessages((prev) =>
        prev.map((m) => ({
          ...m,
          toolCalls: m.toolCalls?.map((tc): ChatToolCall =>
            tc.toolCallId === toolCallId
              ? { ...tc, state: "result", result }
              : tc,
          ),
        })),
      );
    },
    [],
  );

  return {
    messages,
    status,
    conversationId,
    send,
    stop,
    newChat,
    loadConversation,
    resolveToolCall,
  };
}
