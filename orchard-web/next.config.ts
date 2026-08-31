import type { NextConfig } from "next";

/**
 * The FastAPI backend base URL. In dev it's the local uvicorn server; in
 * other environments set FASTAPI_URL (e.g. https://api.example.com).
 */
const FASTAPI_URL = process.env.FASTAPI_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  /**
   * Proxy the versioned API straight to FastAPI. The browser calls
   * same-origin `/api/v1/*` (no CORS, no per-route boilerplate) and Next
   * forwards it to `${FASTAPI_URL}/api/v1/*`.
   *
   * `/api/chat` is NOT matched here - it's a real route handler
   * (app/api/chat/route.ts) that coordinates Vercel AI SDK streaming.
   */
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${FASTAPI_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
