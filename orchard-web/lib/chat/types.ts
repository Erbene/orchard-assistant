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

export interface ChatRedirect {
  href: string;
  label: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  toolCalls?: ChatToolCall[];
  /** Set when the assistant hands off to another page (e.g. the scheduler). */
  redirect?: ChatRedirect;
}

/** A persisted conversation thread (history sidebar). */
export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

/** One stored message, as returned by GET /conversations/{id}. */
export interface StoredChatMessage {
  id: number;
  role: ChatRole;
  content: string;
  meta: {
    route?: string;
    tool_calls?: { tool: string; args: Record<string, unknown>; result: unknown }[];
    redirect?: ChatRedirect;
  };
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: StoredChatMessage[];
}

export type ChatStreamEvent =
  | { type: "start" }
  | { type: "conversation"; id: number; title: string; new: boolean }
  | { type: "text-delta"; delta: string }
  | {
      type: "tool";
      toolName: string;
      args: Record<string, unknown>;
      result: unknown;
    }
  | { type: "redirect"; href: string; label: string }
  | { type: "finish"; finishReason: string }
  | { type: "error"; error: string };
