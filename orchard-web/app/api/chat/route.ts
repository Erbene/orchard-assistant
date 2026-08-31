/**
 * Chat route handler — kept as a real route (not a rewrite) because it
 * coordinates Vercel AI SDK streaming / tool calls for the chat widget.
 *
 * It forwards to the FastAPI backend's `POST /api/v1/chat` and streams the
 * `text/event-stream` response straight back to the browser. (No model is
 * called in this app; the backend owns the chat implementation.)
 */
const FASTAPI_URL = process.env.FASTAPI_URL ?? "http://localhost:8000";

// Streaming can outlast the default serverless budget.
export const maxDuration = 60;

export async function POST(req: Request) {
  const body = await req.text();

  let upstream: Response;
  try {
    upstream = await fetch(`${FASTAPI_URL}/api/v1/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
  } catch {
    return sseError("The chat backend is unreachable.");
  }

  if (!upstream.ok || !upstream.body) {
    return sseError(`Chat backend responded ${upstream.status}.`);
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
    },
  });
}

function sseError(message: string): Response {
  const frame = `data: ${JSON.stringify({ type: "error", error: message })}\n\n`;
  return new Response(frame, {
    status: 200,
    headers: { "content-type": "text/event-stream; charset=utf-8" },
  });
}
