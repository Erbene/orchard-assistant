# Orchard Web

Next.js (App Router) frontend for the Orchard Management System. A persistent
collapsible sidebar:

| Route | Page |
| ----- | ---- |
| `/assistant` (and `/`) | Full-page ChatGPT-style assistant. Streams SSE from the backend; the model is a stub. |
| `/trees` | Trees CRUD data table (`@tanstack/react-table`) — search, sort, paginate, row actions, modal form. The edit dialog has a **Linked Sources** multi-select. |
| `/zones` | Zones CRUD data table — same shape. |
| `/sources` | Knowledge-base sources: CRUD table + modal to upload a file or paste text. |

`species`, `variety`, `soil_drainage` and zone `water_source` are free-text
inputs, stored exactly as typed by [orchard-server](../orchard-server) (no
enums). Zone ids are auto-assigned.

## Layout

```
app/
  layout.tsx          <Sidebar/> + <MobileHeader/> + <main> shell
  page.tsx            redirect → /assistant
  assistant/page.tsx  header (status) · centered max-w-3xl message list · fixed composer
  trees/page.tsx      header · <DataTable/> · create/edit <Dialog> · <DetailsDialog> · <ConfirmDialog>
  zones/page.tsx      same
  sources/page.tsx    same shape (upload/paste modal, rename, view raw_content)
  api/chat/route.ts        SSE forward to ${FASTAPI_URL}/api/v1/chat
  api/v1/sources/route.ts  GET + multipart POST proxy — the rewrite drops FormData bodies

components/
  sidebar.tsx              persistent rail (localStorage collapse) + mobile <Sheet> drawer
  ui/data-table.tsx        reusable TanStack table: global search, sortable headers, pagination
  ui/{dialog,sheet,dropdown-menu,table,confirm-dialog,details-dialog}.tsx
  data-table/{row-actions,cells}.tsx      "…" menu (View/Edit/Delete) + shared cell renderers
  {trees,zones,sources}/columns.tsx       ColumnDef factories
  forms/{tree,zone}-entity-form.tsx       reused inside the create/edit Dialog
  sources/source-upload-form.tsx          file / paste-text toggle → multipart POST
  trees/linked-sources.tsx                multi-select: GET + PUT /api/v1/trees/{id}/sources
  chat/{chat-message,tool-call-widget,approval-card}.tsx
```

> **Multipart caveat.** Next's `rewrites()` proxy drops `multipart/form-data`
> request bodies, so `POST /api/v1/sources` goes through a real route handler
> (`app/api/v1/sources/route.ts`) that re-serializes the FormData. Everything
> else still flows through the rewrite.

## Backend communication

Unchanged from before: the frontend talks **directly to FastAPI**.
`next.config.ts` rewrites `/api/v1/:path*` → `${FASTAPI_URL}/api/v1/:path*`
(`FASTAPI_URL` default `http://localhost:8000`). UI code calls same-origin
`/api/v1/...` through [lib/api.ts](lib/api.ts) (`apiClient` + `ApiError` +
`zonesApi`/`treesApi`).

## Chat / `useChat`

The assistant uses [lib/chat/use-orchard-chat.ts](lib/chat/use-orchard-chat.ts)
— a hand-rolled `fetch` + `ReadableStream` SSE consumer with the same surface
as Vercel AI SDK's `useChat` (`{ messages, status, send, stop, ... }`). The
Vercel AI SDK was removed earlier (per the "no model scaffolding" decision) and
the backend streams plain SSE, not the AI SDK data-stream protocol. To adopt
`useChat` later: re-add `ai`, switch `app/api/chat/route.ts` to
`streamText(...).toDataStreamResponse()`, and swap the hook in
`app/assistant/page.tsx`.

## Setup

```sh
cd orchard-web
npm install                       # @tanstack/react-table, @radix-ui/react-{dialog,dropdown-menu}, lucide-react, …
cp .env.example .env.local        # FASTAPI_URL (default http://localhost:8000)
```

```sh
cd ../orchard-server && .venv/Scripts/python -m uvicorn app.main:app --reload
cd ../orchard-web    && npm run dev        # http://localhost:3000
```

`npm run build` · `npm run typecheck`.
