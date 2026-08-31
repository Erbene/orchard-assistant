/**
 * Chat message + SSE event shapes. Local to this app - no Vercel AI SDK
 * dependency. `POST /api/chat` (Next) proxies `POST /chat` (orchard-server),
 * which streams the events below.
 */

export type ChatRole = "user" | "assistant";

/** A tool call surfaced in the stream. The stub backend never emits these yet,
 *  but the widgets + approval flow render them when a real agent does. */
export interface ChatToolCall {
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
  state: "call" | "result";
  result?: unknown;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  toolCalls?: ChatToolCall[];
}

/** Wire message sent up to the server (history without client-only fields). */
export interface ChatMessageWire {
  role: ChatRole;
  content: string;
}

export type ChatStreamEvent =
  | { type: "start" }
  | { type: "text-delta"; delta: string }
  | { type: "finish"; finishReason: string }
  | { type: "error"; error: string };
