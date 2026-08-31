# Orchard Web

Next.js (App Router) frontend for the Orchard Management System. Two modes on
one dashboard:

- **Manual CRUD** (`components/crud`, `components/forms`) — form-based create /
  update / delete for zones and trees. `species`, `variety`, `soil_drainage`
  and zone `source` are free-text inputs, stored exactly as typed by
  [orchard-server](../orchard-server) (no enums, no coercion). Zone ids are
  auto-assigned. 422 `{ detail, field }` responses (e.g. a tree naming a
  non-existent zone) are shown inline plus as a toast.
- **Agent chat** (`components/chat`) — a streamed assistant. `POST /api/chat`
  (a real route handler, for Vercel AI SDK streaming/tool coordination) forwards
  to the backend's `POST /api/v1/chat`, which streams Server-Sent Events. That
  endpoint currently returns a **stub reply** — no model is called in this app.

## Backend communication

The frontend talks **directly to FastAPI** — there are no per-resource Next API
routes. `next.config.ts` rewrites the versioned namespace:

```
browser ─▶ /api/v1/:path*   ──(next.config.ts rewrite)──▶  ${FASTAPI_URL}/api/v1/:path*
browser ─▶ /api/chat        ──(app/api/chat/route.ts)────▶  ${FASTAPI_URL}/api/v1/chat  (SSE)
```

`FASTAPI_URL` defaults to `http://localhost:8000`. UI code never hardcodes a
host — it calls same-origin `/api/v1/...` through [lib/api.ts](lib/api.ts).

### `lib/api.ts`

```ts
import { apiClient, zonesApi, treesApi, ApiError } from "@/lib/api";

const zones = await apiClient.get<Zone[]>("/api/v1/zones");
const tree  = await zonesApi.create({ name: "North block", soil_drainage: "fast" });

try {
  await treesApi.create(data);
} catch (e) {
  if (e instanceof ApiError) setFieldError(e.field, e.detail); // 422 → { detail, field }
}
```

`apiClient.{get,post,put,patch,del}` — JSON in/out, `204`/empty handled, and
every non-2xx (plus network failure, `status: 0`) throws `ApiError` carrying
`status` / `detail` / `field` / `body`. `zonesApi` + `treesApi` are typed
wrappers over it.

## Setup

```sh
cd orchard-web
npm install
cp .env.example .env.local        # FASTAPI_URL (default http://localhost:8000)
```

Start the backend, then the frontend:

```sh
cd ../orchard-server && .venv/Scripts/python -m uvicorn app.main:app --reload
cd ../orchard-web    && npm run dev        # http://localhost:3000
```

`npm run build` · `npm run typecheck`.

## `app/` layout

```
app/
  layout.tsx            root layout + ToastProvider
  page.tsx              dual-mode dashboard (CRUD + assistant)
  globals.css
  api/
    chat/route.ts       ONLY route handler — SSE forward to ${FASTAPI_URL}/api/v1/chat
```

All zone/tree traffic goes through the `next.config.ts` rewrite — no
`app/api/zones`, `app/api/trees`, or `_proxy.ts`.

## Key modules

| File | Role |
| ---- | ---- |
| [next.config.ts](next.config.ts) | `rewrites()` — `/api/v1/*` → `${FASTAPI_URL}/api/v1/*` |
| [lib/api.ts](lib/api.ts) | `apiClient` fetch wrapper + `ApiError` + `zonesApi` / `treesApi` |
| [lib/types.ts](lib/types.ts) | `Zone` / `Tree` / `*Input` / `*Patch` / `ApiErrorBody` |
| [components/forms/tree-entity-form.tsx](components/forms/tree-entity-form.tsx) | Free-text CRUD form; field-level 422 handling |
| [components/forms/zone-entity-form.tsx](components/forms/zone-entity-form.tsx) | Zone form (id auto-assigned, free-text `source`) |
| [components/crud/entity-manager.tsx](components/crud/entity-manager.tsx) | Tabbed list + inline forms + delete |
| [app/api/chat/route.ts](app/api/chat/route.ts) | SSE forward for the chat widget |
| [lib/chat/use-orchard-chat.ts](lib/chat/use-orchard-chat.ts) | Hand-rolled SSE consumer hook (no Vercel AI SDK) |
| [components/chat/tool-call-widget.tsx](components/chat/tool-call-widget.tsx) · [approval-card.tsx](components/chat/approval-card.tsx) | Inline tool status + HITL Approve/Reject (render when the stream carries tool calls) |
