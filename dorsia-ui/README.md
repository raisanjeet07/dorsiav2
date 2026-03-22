# Dorsia UI

Next.js app for the **research workflow** experience: create workflows, watch live agent streams, review reports, and approve or request changes.

## Requirements

- Node 20+
- [research-work-flow-ai](../research-work-flow-ai) running and reachable from the browser

## Configuration

Copy `.env.example` to `.env.local` and set URLs to match your deployment:

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Base URL for REST (`/api/v1/...`) |
| `NEXT_PUBLIC_WS_URL` | (Optional) WebSocket origin for workflow events (`/ws/workflows/{id}`). If omitted, the UI builds `ws://` or `wss://` from `NEXT_PUBLIC_API_URL` (same host/port). |

**If the UI loads but live updates stay disconnected:** confirm the research API is reachable from the browser at `NEXT_PUBLIC_API_URL`, and that the WebSocket URL matches (same host as REST unless you set `NEXT_PUBLIC_WS_URL` explicitly). Mixed content (HTTPS page + `ws://`) is blocked by the browser—use `https` + `wss` for production.

**Important:** Do not bake default `NEXT_PUBLIC_WS_URL` into `next.config`—it forces `ws://localhost:8000` in the bundle even when only `NEXT_PUBLIC_API_URL` points elsewhere. This app derives the WS origin from `NEXT_PUBLIC_API_URL` when `NEXT_PUBLIC_WS_URL` is unset.

## Commands

```bash
npm install
npm run dev      # http://localhost:3000
npm run build
npm run start
npm run lint
```

Typecheck:

```bash
npx tsc --noEmit
```

## Production build

```bash
npm run build
npm run start
```

Set env vars in your hosting platform (Vercel, Docker, etc.). Do not commit secrets; these are public browser-facing URLs only.
