# Dzomdu dashboard

The web interface for Dzomdu: a Next.js 16 app built with
[shadcn/ui](https://ui.shadcn.com) and [Animate UI](https://animate-ui.com). It's exported as
static files, and the Python backend serves them, so day to day you only run `dzomdu ui`.

## Build once (and after updates)

```bash
cd web
npm install
npm run build        # writes web/out/, which `dzomdu ui` serves at http://localhost:8765
```

## Develop with hot reload

```bash
dzomdu ui --no-open          # terminal 1: the API on :8765
cd web && npm run dev        # terminal 2: the dashboard on http://localhost:3000
```

`.env.development` points the dev server at the API (`NEXT_PUBLIC_DZOMDU_API`). In the built
version the API is on the same origin.

## Layout

| Path | Contents |
|---|---|
| `src/app/` | Pages: `/` dashboard, `/record`, `/meetings`, `/meetings/view?id=`, `/people`, `/projects`, `/settings` |
| `src/components/` | App components (sidebar, header, charts, action list, recording views) |
| `src/components/ui/`, `src/components/animate-ui/` | shadcn/ui and Animate UI registry code. Update it with `npx shadcn add`, not by hand. |
| `src/lib/api.ts` | Typed API client |
| `src/lib/recorder.ts` | Microphone capture: AudioWorklet → 16 kHz PCM → WebSocket |

Add components with the shadcn CLI. Animate UI is configured as the `@animate-ui` registry in
`components.json`:

```bash
npx shadcn@latest add dialog
npx shadcn@latest add @animate-ui/components-radix-accordion
```

The repo's `.mcp.json` also gives Claude Code the **shadcn** MCP server, for browsing and
adding components, and the **next-devtools** MCP server, for inspecting the running dev server.
