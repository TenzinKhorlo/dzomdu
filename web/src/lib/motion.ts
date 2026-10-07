// Motion vocabulary for the whole app (Apple's "Designing Fluid Interfaces", on the web).
//
// Springs, not durations: they start from the on-screen value, carry velocity and can be
// interrupted at any moment. Motion's `bounce` + `duration` map onto Apple's damping ratio and
// response: bounce 0 = damping 1.0 (critically damped, no overshoot).

/** Default for everything: critically damped, no overshoot (damping 1.0, response 0.4). */
export const spring = { type: "spring", bounce: 0, duration: 0.4 } as const

/** Small, quick UI changes such as icons swapping or a thumb growing (response 0.25). */
export const springSnappy = { type: "spring", bounce: 0, duration: 0.25 } as const

/**
 * Slight bounce (damping ≈ 0.8). Only after a gesture that carried momentum, such as a swipe
 * released with velocity. Never for things that simply appear.
 */
export const springMomentum = { type: "spring", bounce: 0.2, duration: 0.4 } as const

/**
 * Where a flick would come to rest, using the same exponential deceleration as scrolling
 * (Apple's projection function). `velocity` is in px/s.
 */
export function project(velocity: number, decelerationRate = 0.998): number {
  return ((velocity / 1000) * decelerationRate) / (1 - decelerationRate)
}

/**
 * Soft boundary: the further past the edge, the less the element follows the pointer.
 * Real things slow down before they stop.
 */
export function rubberband(overshoot: number, dimension: number, constant = 0.55): number {
  if (dimension <= 0) return 0
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot))
}

/** A brief haptic tick on devices that support it (Android). Use only for commits. */
export function haptic(pattern: number | number[] = 8) {
  if (typeof navigator !== "undefined" && "vibrate" in navigator) {
    try {
      navigator.vibrate(pattern)
    } catch {
      // not allowed without a user gesture on some browsers; it's only a nicety
    }
  }
}
