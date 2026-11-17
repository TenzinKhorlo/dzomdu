/** Diameter in rem for a bubble whose area is proportional to `value`; the largest value gets `maxRem`. */
export function bubbleDiameter(value: number, max: number, maxRem: number) {
  if (max <= 0 || value <= 0) return 0
  return maxRem * Math.sqrt(value / max)
}

export type Bubble = { cx: number; cy: number; d: number }

function hash(text: string) {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return h >>> 0
}

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Scatters bubbles inside a width x height box. The scatter looks random but is seeded, so the same
 * people always land in the same places. Bubbles may overlap, but never so far that one covers
 * another's centre, so every initial stays readable. Results come back in the order of `values`.
 */
export function scatterBubbles(values: number[], seed: string, width = 100, height = 72, maxDiameter = 44): Bubble[] {
  const rand = mulberry32(hash(seed))
  const max = Math.max(0, ...values)
  const out: Bubble[] = values.map((v) => ({ cx: 0, cy: 0, d: bubbleDiameter(v, max, maxDiameter) }))
  const placed: Bubble[] = []
  const order = values.map((_, i) => i).sort((a, b) => values[b] - values[a])

  for (const i of order) {
    const r = out[i].d / 2
    // how far a candidate sits from being allowed: <= 0 means no bubble covers another's centre
    const clearance = (x: number, y: number) =>
      placed.reduce((worst, p) => Math.max(worst, Math.max(r, p.d / 2) + 0.5 * Math.min(r, p.d / 2) - Math.hypot(x - p.cx, y - p.cy)), -Infinity)
    const valid: { x: number; y: number }[] = []
    let best = { x: width / 2, y: height / 2, score: Infinity }
    for (let n = 0; n < 500 && valid.length < 12; n++) {
      const x = r + rand() * Math.max(0, width - 2 * r)
      const y = r + rand() * Math.max(0, height - 2 * r)
      const score = placed.length ? clearance(x, y) : 0
      if (score <= 0) valid.push({ x, y })
      else if (score < best.score) best = { x, y, score }
    }
    // of the valid spots, take the one nearest the middle so the group stays a cluster
    const pick = valid.length
      ? valid.reduce((a, b) => (Math.hypot(a.x - width / 2, a.y - height / 2) <= Math.hypot(b.x - width / 2, b.y - height / 2) ? a : b))
      : best
    out[i].cx = pick.x
    out[i].cy = pick.y
    placed.push(out[i])
  }
  return out
}
