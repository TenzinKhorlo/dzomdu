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
| `src/lib/motion.ts` | Motion tokens (springs), the momentum projection and rubber-band functions, haptics |
| `src/components/meeting/player.tsx` | Meeting audio player: provider, scrubber, floating player bar |
| `src/components/swipe-to-complete.tsx` | Swipe gesture for action items |
| `src/components/confirm.tsx` | `useConfirm()`, an in-app dialog for irreversible actions only |

## Visual style

- **Surfaces.** A grey sidebar canvas, white cards with a hairline border and
  `shadow-[var(--shadow-card)]`, 12px card corners (`rounded-xl`) and 8px controls
  (`rounded-lg`).
- **Type.** Inter (bundled via `@fontsource-variable/inter`) for the interface, Geist Mono for
  timestamps. Page titles are `text-xl`; labels, table text and descriptions are 13px.
- **Colour.**
  - Primary actions are near-black (`bg-primary`).
  - The one accent, `brand` (orange #ea580c), is for highlights only: the "New recording"
    button (`variant="brand"`), the activity chart and open-item chips.
  - Speaker and project colours come from `colorFor()`.
- **Charts.**
  - One hue on the neutral `track` colour, with 2px gaps between marks.
  - A dark tooltip on hover and keyboard focus.
  - Values sit at the bar tips. Text is never drawn in a data colour.

## Interaction conventions

- **Motion.** Use the springs in `src/lib/motion.ts`, not ad-hoc durations or curves.
  `MotionConfig reducedMotion="user"` in `providers.tsx` already respects Reduce motion. Anything
  that animates outside motion (CSS, scrolling, count-ups) must check `useReducedMotion()` or
  `prefers-reduced-motion` itself.
- **Gestures.**
  - Track the pointer 1:1 and allow a grab mid-animation (`x.stop()`, then continue from the
    on-screen value).
  - Decide on release with `project(velocity)`.
  - Hand the release velocity to the spring.
  - Rubber-band past the edges.
- **Undo, not "are you sure?".** Reversible changes show a toast with **Undo**. Only
  irreversible ones use `useConfirm()`. Cancel takes focus there, so Enter is always safe.
- **Materials.** Use `material` (bars) and `material-thick` (floating controls) for translucent
  surfaces. They become solid under Reduce transparency.
- **Backdrop filter.** Write only `backdrop-filter` and let the build add the `-webkit-` prefix.
  A hand-written prefixed pair gets collapsed to the prefixed form only, which Chromium ignores.

Add components with the shadcn CLI. Animate UI is configured as the `@animate-ui` registry in
`components.json`:

```bash
npx shadcn@latest add dialog
npx shadcn@latest add @animate-ui/components-radix-accordion
```

The repo's `.mcp.json` also gives Claude Code the **shadcn** MCP server, for browsing and
adding components, and the **next-devtools** MCP server, for inspecting the running dev server.
