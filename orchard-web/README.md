# Orchard Web

Next.js (App Router) frontend for the Orchard Assistant. A persistent collapsible
sidebar links the main routes:

| Route | Page |
| ----- | ---- |
| `/assistant` (and `/`) | Grounded chat — SSE from the FastAPI Orchestrator + Ollama (not a stub). |
| `/schedule` | Task inbox + Foreman JIT scheduling dialog (time budget → resources → plan). |
| `/irrigation` | Irrigation planning — supervisor HITL approval queue |
| `/irrigation/sensors` | Sensor readings; demo moisture/rain/last-watered pins when `ORCHARD_DEMO=true`. |
| `/irrigation/schedule` | Rachio zone schedule + supervisor settings |
| `/trees` | Trees CRUD data table — search, sort, paginate, row actions, modal form. |
| `/trees/[id]` | Tree detail with **Care Plan** tab (month strip, baseline wizard, template editing). |
| `/zones` | Irrigation → Zones — live Rachio list, local labels, unused-zone hide; manual water is a real Rachio run (bypasses irrigation HITL). |
| `/sources` | Knowledge-base sources: CRUD table + modal to upload a file or paste text. |

`species` and `variety` are free-text inputs, stored exactly as typed by
[orchard-server](../orchard-server) (no enums). Zone configuration is edited in
the Rachio app. This UI lists zones, stores a local display label, and can
start a manual run.

## Layout

```
app/
  layout.tsx              <Sidebar/> + <MobileHeader/> + <main> shell
  page.tsx                redirect → /assistant
  assistant/page.tsx      conversation rail · message list · composer
  schedule/page.tsx       task inbox · Foreman JIT wizard dialog
  irrigation/layout.tsx   shared header · sub-nav · Run Supervision Task
  irrigation/page.tsx     HITL approval queue
  irrigation/sensors/page.tsx  sensor readings · demo pins
  irrigation/schedule/page.tsx  schedule & supervisor settings
  trees/page.tsx          <DataTable/> · create/edit <Dialog>
  trees/[id]/page.tsx     tree detail · Care Plan tab
  zones/page.tsx          Rachio zone cards · manual water dialog
  sources/page.tsx        upload/paste modal · rename · view raw_content
  api/chat/route.ts       SSE forward to ${FASTAPI_URL}/api/v1/chat
  api/v1/sources/route.ts GET + multipart POST proxy

components/
  sidebar.tsx
  care-plan/{care-plan-tab,baseline-wizard,month-strip}.tsx
  irrigation/{proposal-card,...}.tsx
  chat/{chat-message,tool-call-widget,approval-card}.tsx
  ui/data-table.tsx
  {trees,zones,sources}/columns.tsx
  forms/tree-entity-form.tsx
```

> **Multipart caveat.** Next's `rewrites()` proxy drops `multipart/form-data`
> request bodies, so `POST /api/v1/sources` goes through a real route handler
> (`app/api/v1/sources/route.ts`) that re-serializes the FormData. Everything
> else still flows through the rewrite.

## Backend communication

The frontend talks **directly to FastAPI**. `next.config.ts` rewrites
`/api/v1/:path*` → `${FASTAPI_URL}/api/v1/:path*` (`FASTAPI_URL` default
`http://localhost:8000`). UI code calls same-origin `/api/v1/...` through
[lib/api.ts](lib/api.ts).

## Chat / `useChat`

The assistant uses [lib/chat/use-orchard-chat.ts](lib/chat/use-orchard-chat.ts)
— a hand-rolled `fetch` + `ReadableStream` SSE consumer. The backend streams
plain SSE from the live Orchestrator graph (routing, agronomy retrieval, task
completion, schedule redirect). Ollama must be running or chat returns 503.

## Setup

```powershell
cd orchard-web
npm install
copy .env.example .env.local        # FASTAPI_URL (default http://localhost:8000)
```

From the repo root, `../dev.ps1` brings up Postgres + Chroma and starts both
servers. Or run manually:

```powershell
cd ..\orchard-server && .venv\Scripts\python -m uvicorn app.main:app --reload
cd ..\orchard-web    && npm run dev        # http://localhost:3000
```

`npm run build` · `npm run typecheck`.
