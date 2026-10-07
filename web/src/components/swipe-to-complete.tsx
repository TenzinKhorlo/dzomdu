"use client"

import * as React from "react"
import { Check, RotateCcw } from "lucide-react"
import {
  animate,
  motion,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useTransform,
} from "motion/react"

import { haptic, project, rubberband, spring, springMomentum } from "@/lib/motion"
import { cn } from "@/lib/utils"

const SLOP = 10 // px of movement before committing to a direction (hysteresis)
const RUBBER = 0.55

/** Inverse of rubberband(), so a row grabbed mid-flight continues from where it is. */
function unrubber(y: number, d: number, c = RUBBER) {
  const a = Math.min(Math.abs(y), d * 0.99)
  return (Math.sign(y) * a * d) / (c * (d - a))
}

/**
 * Swipe right to complete (or reopen) a task.
 *
 * Tracks the pointer 1:1, resists past the commit point and in the wrong direction, projects
 * momentum to decide (a quick flick commits from a short distance), hands the release velocity
 * to the spring, and can be grabbed again mid-animation.
 */
export function SwipeToComplete({
  done,
  disabled,
  onCommit,
  children,
  className,
}: {
  done: boolean
  disabled?: boolean
  onCommit: () => void
  children: React.ReactNode
  className?: string
}) {
  const ref = React.useRef<HTMLDivElement>(null)
  const reduce = useReducedMotion()
  const x = useMotionValue(0)
  const [armed, setArmed] = React.useState(false)
  const armedRef = React.useRef(false)
  const drag = React.useRef({
    mode: "idle" as "idle" | "pending" | "dragging",
    id: -1,
    startX: 0,
    startY: 0,
    grab: 0, // pointer → raw offset, so the row doesn't jump to the finger
    width: 1,
    commitAt: 96,
    moved: false,
  })

  const progress = useTransform(x, (v) => Math.min(1, Math.max(0, v / drag.current.commitAt)))
  const reveal = useTransform(progress, [0, 0.15, 1], [0, 0.6, 1])
  const iconScale = useTransform(progress, [0, 1], [0.5, 1])

  // causality: the tick fires on the frame the threshold is crossed, not after release
  useMotionValueEvent(x, "change", (v) => {
    const isArmed = v >= drag.current.commitAt
    if (isArmed !== armedRef.current) {
      armedRef.current = isArmed
      setArmed(isArmed)
      if (isArmed && drag.current.mode === "dragging") haptic(8)
    }
  })

  const display = (raw: number, d: number, c: number) => {
    if (raw < 0) return rubberband(raw, d, RUBBER) // nothing to the left: resist
    if (raw > c) return c + rubberband(raw - c, d, RUBBER) // past the commit point: resist
    return raw
  }
  const toRaw = (shown: number, d: number, c: number) => {
    if (shown < 0) return unrubber(shown, d)
    if (shown > c) return c + unrubber(shown - c, d)
    return shown
  }

  function begin(e: React.PointerEvent) {
    const s = drag.current
    s.mode = "dragging"
    s.width = ref.current?.offsetWidth ?? 1
    s.commitAt = Math.min(110, s.width * 0.3)
    x.stop() // interrupt: continue from the on-screen position, never from the target
    s.grab = toRaw(x.get(), s.width, s.commitAt) - e.clientX
    ref.current?.setPointerCapture(e.pointerId)
    // the gesture owns the pointer now: no stray text selection while the row moves
    window.getSelection()?.removeAllRanges()
    document.documentElement.style.userSelect = "none"
  }

  function end() {
    drag.current.mode = "idle"
    document.documentElement.style.userSelect = ""
  }

  function onPointerDown(e: React.PointerEvent) {
    if (disabled || e.button !== 0) return
    const s = drag.current
    s.id = e.pointerId
    s.startX = e.clientX
    s.startY = e.clientY
    s.moved = false
    if (x.isAnimating()) begin(e) // grabbed mid-flight: follow the finger immediately
    else s.mode = "pending"
  }

  function onPointerMove(e: React.PointerEvent) {
    const s = drag.current
    if (e.pointerId !== s.id) return
    if (s.mode === "pending") {
      const dx = e.clientX - s.startX
      const dy = e.clientY - s.startY
      if (Math.abs(dy) > SLOP && Math.abs(dy) > Math.abs(dx)) {
        s.mode = "idle" // it's a scroll; let the browser have it
        return
      }
      if (Math.abs(dx) > SLOP) begin(e)
      else return
    }
    if (s.mode !== "dragging") return
    s.moved = true
    x.set(display(e.clientX + s.grab, s.width, s.commitAt))
  }

  function onPointerUp(e: React.PointerEvent) {
    const s = drag.current
    if (e.pointerId !== s.id || s.mode !== "dragging") {
      s.mode = "idle"
      return
    }
    end()
    const velocity = x.getVelocity()
    // decide from where the gesture is going, not where the finger stopped. A row is a short
    // track, so use the "fast" deceleration rate: a deliberate flick commits from a short
    // distance, a small nudge doesn't.
    const commit = x.get() + project(velocity, 0.99) >= s.commitAt
    if (commit) {
      if (!armedRef.current) haptic(8) // a flick that never reached the threshold
      onCommit()
    }
    if (reduce) x.set(0)
    // a release that carried momentum may overshoot a little; otherwise settle cleanly
    else animate(x, 0, { ...(commit ? springMomentum : spring), velocity })
  }

  return (
    <div className={cn("relative overflow-hidden rounded-lg", className)}>
      <motion.div
        aria-hidden
        style={{ opacity: reveal }}
        className={cn(
          "absolute inset-0 flex items-center gap-2 rounded-lg pl-3 text-sm font-medium",
          done ? "bg-muted text-muted-foreground" : "bg-success/15 text-success",
        )}
      >
        <motion.span
          style={{ scale: iconScale }}
          animate={armed ? { scale: 1.15 } : { scale: 1 }}
          transition={springMomentum}
          className={cn(
            "flex size-6 items-center justify-center rounded-full",
            done ? "bg-muted-foreground/20" : "bg-success text-white",
          )}
        >
          {done ? <RotateCcw className="size-3.5" /> : <Check className="size-3.5" />}
        </motion.span>
        {done ? "Reopen" : "Done"}
      </motion.div>
      <motion.div
        ref={ref}
        style={{ x, touchAction: "pan-y" }}
        className="relative bg-card will-change-transform"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        // a drag must never also count as a click on a link or checkbox inside the row
        onClickCapture={(e) => {
          if (drag.current.moved) {
            e.preventDefault()
            e.stopPropagation()
            drag.current.moved = false
          }
        }}
      >
        {children}
      </motion.div>
    </div>
  )
}
