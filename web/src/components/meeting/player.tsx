"use client"

import * as React from "react"
import { Pause, Play, RotateCcw, RotateCw } from "lucide-react"
import {
  AnimatePresence,
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type MotionValue,
} from "motion/react"

import { SpeakerAvatar } from "@/components/common"
import { Button } from "@/components/ui/button"
import { apiUrl, type Turn } from "@/lib/api"
import { clock } from "@/lib/format"
import { rubberband, spring, springSnappy } from "@/lib/motion"
import { cn } from "@/lib/utils"

// -- playback state shared by the player bar, transcript and notes ------------------------------

type Player = {
  available: boolean | null // null while loading
  playing: boolean
  time: number // coarse (a few times a second): for the transcript and labels
  progress: MotionValue<number> // smooth (every frame): for the scrubber
  duration: number
  rate: number
  seek: (t: number, play?: boolean) => void
  toggle: () => void
  skip: (delta: number) => void
  cycleRate: () => void
}

const PlayerContext = React.createContext<Player | null>(null)

export function usePlayer() {
  return React.useContext(PlayerContext)
}

const RATES = [1, 1.25, 1.5, 2]

export function PlayerProvider({
  meetingId,
  fallbackDuration,
  children,
}: {
  meetingId: string
  fallbackDuration: number
  children: React.ReactNode
}) {
  const audio = React.useRef<HTMLAudioElement>(null)
  const progress = useMotionValue(0)
  const [available, setAvailable] = React.useState<boolean | null>(null)
  const [playing, setPlaying] = React.useState(false)
  const [time, setTime] = React.useState(0)
  const [duration, setDuration] = React.useState(fallbackDuration)
  const [rate, setRate] = React.useState(1)

  // smooth progress while playing, driven by the display's refresh
  React.useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      if (audio.current) progress.set(audio.current.currentTime)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, progress])

  const seek = React.useCallback(
    (t: number, play = false) => {
      const el = audio.current
      if (!el) return
      const clamped = Math.max(0, Math.min(t, el.duration || duration))
      el.currentTime = clamped
      progress.set(clamped)
      setTime(clamped)
      if (play) void el.play().catch(() => {})
    },
    [duration, progress],
  )

  const value: Player = {
    available,
    playing,
    time,
    progress,
    duration,
    rate,
    seek,
    toggle: () => {
      const el = audio.current
      if (!el) return
      if (el.paused) void el.play().catch(() => {})
      else el.pause()
    },
    skip: (delta) => seek((audio.current?.currentTime ?? 0) + delta),
    cycleRate: () => {
      const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length]
      if (audio.current) audio.current.playbackRate = next
      setRate(next)
    },
  }

  return (
    <PlayerContext.Provider value={value}>
      <audio
        ref={audio}
        src={apiUrl(`/api/meetings/${encodeURIComponent(meetingId)}/audio`)}
        preload="metadata"
        onLoadedMetadata={(e) => {
          setAvailable(true)
          if (Number.isFinite(e.currentTarget.duration)) setDuration(e.currentTarget.duration)
        }}
        onError={() => setAvailable(false)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => {
          setTime(e.currentTarget.currentTime)
          if (e.currentTarget.paused) progress.set(e.currentTarget.currentTime)
        }}
        hidden
      />
      {children}
    </PlayerContext.Provider>
  )
}

/** Index of the turn being spoken at time `t` (turns are sorted by start). */
export function turnAt(turns: Turn[], t: number): number {
  let lo = 0
  let hi = turns.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (turns[mid].start <= t) {
      found = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return found
}

// -- scrubber ----------------------------------------------------------------------------------

/**
 * A timeline you can grab: tracks the pointer 1:1 (keeping the offset from where you grabbed
 * the thumb), grows on press, shows the time under your finger, and stretches softly when
 * dragged past either end instead of stopping dead.
 */
function Scrubber({
  progress,
  duration,
  onSeek,
}: {
  progress: MotionValue<number>
  duration: number
  onSeek: (t: number) => void
}) {
  const track = React.useRef<HTMLDivElement>(null)
  const reduce = useReducedMotion()
  const scrub = useMotionValue<number | null>(null) // value while dragging
  const stretch = useMotionValue(0) // px past an end (rubber-banded)
  const [active, setActive] = React.useState(false)
  const [preview, setPreview] = React.useState(0)
  const state = React.useRef({ id: -1, offset: 0 })

  const shown = useTransform(() => {
    const v = scrub.get() ?? progress.get()
    return duration > 0 ? Math.min(1, Math.max(0, v / duration)) : 0
  })
  const fillWidth = useTransform(shown, (f) => `${f * 100}%`)
  const thumbLeft = useTransform(shown, (f) => `${f * 100}%`)
  const scaleX = useTransform(stretch, (s) => {
    const w = track.current?.offsetWidth || 1
    return 1 + Math.abs(s) / w
  })
  const origin = useTransform(stretch, (s) => (s < 0 ? "100% 50%" : "0% 50%"))

  function valueAt(clientX: number) {
    const rect = track.current!.getBoundingClientRect()
    const raw = clientX + state.current.offset - rect.left
    const over = raw < 0 ? raw : raw > rect.width ? raw - rect.width : 0
    stretch.set(rubberband(over, rect.width) * 0.12)
    const f = Math.min(1, Math.max(0, raw / rect.width))
    return f * duration
  }

  function onPointerDown(e: React.PointerEvent) {
    if (e.button !== 0 || !duration) return
    e.preventDefault()
    const rect = track.current!.getBoundingClientRect()
    const thumbX = rect.left + shown.get() * rect.width
    // grabbing the thumb keeps the offset; pressing the track jumps there (like any timeline)
    state.current = {
      id: e.pointerId,
      offset: Math.abs(e.clientX - thumbX) <= 12 ? thumbX - e.clientX : 0,
    }
    track.current!.setPointerCapture(e.pointerId)
    setActive(true)
    const v = valueAt(e.clientX)
    scrub.set(v)
    setPreview(v)
  }
  function onPointerMove(e: React.PointerEvent) {
    if (e.pointerId !== state.current.id) return
    const v = valueAt(e.clientX)
    scrub.set(v)
    setPreview(v)
  }
  function onPointerUp(e: React.PointerEvent) {
    if (e.pointerId !== state.current.id) return
    state.current.id = -1
    const v = scrub.get()
    if (v !== null) onSeek(v)
    scrub.set(null)
    setActive(false)
    if (reduce) stretch.set(0)
    else animate(stretch, 0, spring)
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const now = progress.get()
    const step = { ArrowLeft: -5, ArrowRight: 5, PageDown: -30, PageUp: 30 }[e.key]
    if (step !== undefined) onSeek(now + step)
    else if (e.key === "Home") onSeek(0)
    else if (e.key === "End") onSeek(duration)
    else return
    e.preventDefault()
  }

  return (
    <div
      ref={track}
      role="slider"
      tabIndex={0}
      aria-label="Playback position"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(preview || progress.get())}
      aria-valuetext={clock(active ? preview : progress.get())}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
      className="group relative flex h-8 flex-1 cursor-pointer touch-none items-center outline-none focus-visible:[&>div:first-child]:ring-[3px] focus-visible:[&>div:first-child]:ring-ring/50"
    >
      <motion.div
        style={{ scaleX, transformOrigin: origin }}
        animate={{ height: active ? 8 : 5 }}
        transition={springSnappy}
        className="relative w-full overflow-hidden rounded-full bg-foreground/12"
      >
        <motion.div style={{ width: fillWidth }} className="h-full rounded-full bg-primary" />
      </motion.div>
      <motion.div
        style={{ left: thumbLeft }}
        className="pointer-events-none absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
      >
        <motion.div
          animate={{ scale: active ? 1.25 : 1 }}
          transition={springSnappy}
          className="size-3.5 rounded-full bg-background shadow-[0_0_0_1.5px_var(--primary),0_2px_6px_rgb(0_0_0/0.2)] opacity-0 group-hover:opacity-100 data-[active=true]:opacity-100"
          data-active={active}
        />
        <AnimatePresence>
          {active && (
            <motion.div
              initial={{ opacity: 0, y: 4, scale: 0.9, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: 4, scale: 0.9, filter: "blur(4px)" }}
              transition={springSnappy}
              className="material-thick absolute bottom-6 left-1/2 -translate-x-1/2 rounded-md px-2 py-1 font-mono text-xs font-medium tabular-nums"
            >
              {clock(preview)}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}

// -- the floating player bar -------------------------------------------------------------------

export function PlayerBar({ turns, className }: { turns: Turn[]; className?: string }) {
  const p = usePlayer()
  if (!p) return null
  const current = turns[turnAt(turns, p.time)]

  if (p.available === false) {
    return (
      <div className={cn("material-thick rounded-2xl px-4 py-3 text-sm text-muted-foreground", className)}>
        The recording for this meeting is no longer on disk, so it can&apos;t be played.
      </div>
    )
  }

  return (
    <div
      className={cn(
        "material-thick sticky bottom-4 z-20 flex items-center gap-3 rounded-2xl px-3 py-2.5",
        className,
      )}
    >
      <Button
        size="icon"
        onClick={p.toggle}
        disabled={!p.available}
        className="size-10 shrink-0 rounded-full"
        aria-label={p.playing ? "Pause" : "Play recording"}
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={p.playing ? "pause" : "play"}
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.5 }}
            transition={springSnappy}
            className="flex"
          >
            {p.playing ? <Pause className="fill-current" /> : <Play className="ml-0.5 fill-current" />}
          </motion.span>
        </AnimatePresence>
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="hidden shrink-0 sm:inline-flex"
        onClick={() => p.skip(-15)}
        aria-label="Back 15 seconds"
      >
        <RotateCcw />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="hidden shrink-0 sm:inline-flex"
        onClick={() => p.skip(15)}
        aria-label="Forward 15 seconds"
      >
        <RotateCw />
      </Button>
      <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
        {clock(p.time)}
      </span>
      <Scrubber progress={p.progress} duration={p.duration} onSeek={(t) => p.seek(t)} />
      <span className="w-14 shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
        {clock(p.duration)}
      </span>
      <div className="hidden w-36 min-w-0 items-center gap-2 md:flex">
        <AnimatePresence mode="popLayout" initial={false}>
          {current && (
            <motion.div
              key={current.label}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="flex min-w-0 items-center gap-2"
            >
              <SpeakerAvatar name={current.label} size="sm" className="ring-0" />
              <span className="truncate text-xs font-medium">{current.label}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={p.cycleRate}
        className={cn("w-12 shrink-0 font-mono text-xs tabular-nums", p.rate !== 1 && "text-brand")}
        aria-label={`Playback speed ${p.rate}×`}
      >
        {p.rate}×
      </Button>
    </div>
  )
}
