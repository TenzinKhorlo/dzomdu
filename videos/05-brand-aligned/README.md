# Dzomdu — Brand aligned revision

Delivery: `../05-dzomdu-brand-aligned-15s.mp4`.

The original 15-second animation and score are preserved, with interfaces rebuilt from the app's design tokens and components. No screenshots are used. The editable animation is `source/dzomdu-brand-aligned.ecproj`; the finishing sequence is `source/dzomdu-brand-aligned.filmcraft`. The original score session is retained in `../04-signal-to-substance/source/dzomdu-score.scraft`.

## Source of truth

- `web/src/app/layout.tsx`: Geist Sans and Geist Mono, bundled locally by the Geist package.
- `web/src/app/globals.css`: semantic colors, corner radii, tracking, typography, and card shadow.
- `web/src/components/ui/card.tsx`: 8px card corners, 20px padding, 15px semibold titles, and 13px descriptions.
- `web/src/components/common.tsx` and `web/src/lib/format.ts`: avatar sizes, name-based speaker palette, and 18% OKLCH background tints.
- `web/src/components/transcript-editor.tsx`: left-aligned speaker rows, 32px avatars, 12px gaps, and mono timestamps.
- `web/src/components/action-list.tsx`: green completed tasks, muted text with a strikethrough, owner avatars, outline due-date badges, and separators.
- `web/src/components/animate-ui/components/radix/checkbox.tsx`: 20px default checkbox, 2px corner radius, 14px indicator.
- `web/src/components/animate-ui/primitives/radix/checkbox.tsx`: exact check path `M4.5 12.75l6 6 9-13.5`, 3.5 stroke width, round caps/joins, 0.2-second delayed stroke reveal.
- `web/src/app/meetings/view/page.tsx`: numbered decisions, separate from completion checkboxes.
- The CalendarClock icon uses the installed Lucide package geometry, recreated in VectorCraft. Its license is in `assets/LUCIDE-LICENSE`.

## Mapping to video

Product UI is drawn at 2.2× its CSS dimensions for legibility at 1080p. An 8px card corner becomes 17.6px, a 4px badge corner becomes 8.8px, and a 2px checkbox corner becomes 4.4px. Padding, type, avatars, and icon strokes scale proportionally. Large promotional titles use Geist with the app's tight headline tracking; mono labels and timestamps use Geist Mono.

Primary is #004182; light canvas is #fafaf9; foreground is #1e1c1b; borders are #e4e4e2; accent is #edf3fa; completed tasks use #15803d. Avatar colors and their tints follow the app's deterministic speaker-color function. Extracted values are retained in `source/brand-tokens.json`.

Fonts used by the native project are bundled in `assets/fonts` with their license. EffectCraft needs those fonts available when opening the project on another computer. ArtCraft command plans are retained for traceability; the native project includes the final layout and compositing adjustments.

## Validation

- All text uses Geist or Geist Mono; no Helvetica fallback remains in the composition.
- Card, badge, and checkbox corner radii verified in the saved native properties.
- Reviewed the full animation at half-second intervals and full-sized interface previews.
- Delivery contains 450 frames at 30 fps, 1920×1080 H.264, 48 kHz stereo AAC, with both streams and container exactly 15.000 seconds.
