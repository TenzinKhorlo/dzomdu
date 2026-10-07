export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const pad = (n: number) => String(n).padStart(2, "0")
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`
}

export function duration(seconds: number): string {
  if (!seconds) return "0 min"
  if (seconds < 60) return `${Math.round(seconds)} s`
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} min`
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return ""
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" })
}

export function longDate(iso: string | null | undefined): string {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return ""
  const then = new Date(iso)
  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000)
  if (days < 1) {
    return `Today, ${then.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`
  }
  if (days < 2) return "Yesterday"
  if (days < 7) return `${days} days ago`
  return shortDate(iso)
}

export function initials(name: string): string {
  const parts = name.replace(/\?$/, "").trim().split(/\s+/)
  if (!parts[0]) return "?"
  return ((parts[0][0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase()
}

export function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"
}

const PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
]

/** A stable colour per person/label, shared by avatars, transcripts and charts. */
export function colorFor(label: string | null | undefined): string {
  if (!label || /^unknown speaker|^…$/i.test(label)) return "var(--muted-foreground)"
  let hash = 0
  for (const ch of label.replace(/\?$/, "")) hash = (hash * 31 + ch.charCodeAt(0)) | 0
  return PALETTE[Math.abs(hash) % PALETTE.length]
}
