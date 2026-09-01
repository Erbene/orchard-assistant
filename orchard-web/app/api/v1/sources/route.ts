/**
 * Proxy for the KB source collection endpoint.
 *
 * Everything else under /api/v1/* goes through next.config.ts `rewrites()`,
 * but that proxy drops `multipart/form-data` request bodies, so the file/text
 * upload (POST) needs a real route handler that re-serializes the FormData.
 * GET is proxied here too since a route.ts captures all methods for its path.
 */
const FASTAPI_URL = process.env.FASTAPI_URL ?? "http://localhost:8000";
const UPSTREAM = `${FASTAPI_URL}/api/v1/sources`;

export async function GET(req: Request) {
  const qs = new URL(req.url).search;
  const upstream = await fetch(`${UPSTREAM}${qs}`, { cache: "no-store" });
  return passthrough(upstream);
}

export async function POST(req: Request) {
  const form = await req.formData();
  const upstream = await fetch(UPSTREAM, { method: "POST", body: form });
  return passthrough(upstream);
}

function passthrough(upstream: Response): Response {
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
}
