"use client"

import * as React from "react"
import { BarChart3, Sparkles, Users } from "lucide-react"

import { EmptyState } from "@/components/common"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { Dashboard } from "@/lib/api"
import { colorFor, shortDate } from "@/lib/format"
import { cn } from "@/lib/utils"

const LEVELS = 12 // dots per column

/** A clean axis maximum: 15, 30, 60, 90, 120, 180, 240 … minutes. */
function niceMax(v: number) {
  const steps = [15, 30, 60, 90, 120, 180, 240, 360, 480, 720]
  return steps.find((s) => s >= v) ?? Math.ceil(v / 240) * 240
}

function minutesLabel(m: number) {
  if (m < 60) return `${Math.round(m)} min`
  const h = Math.floor(m / 60)
  const r = Math.round(m - h * 60)
  return r ? `${h} h ${r} min` : `${h} h`
}

/**
 * Time in meetings per day as a dot matrix: each column is a day, each lit dot is a twelfth of
 * the axis. One series in one hue (the brand accent) on a neutral track, a 2px gap between dots,
 * and a per-column tooltip on hover and keyboard focus.
 */
export function ActivityChart({ data }: { data: Dashboard["activity"] }) {
  const [active, setActive] = React.useState<number | null>(null)
  const total = data.reduce((s, r) => s + r.minutes, 0)
  const top = niceMax(Math.max(1, ...data.map((r) => r.minutes)))
  const busiest = data.reduce((a, b) => (b.minutes > a.minutes ? b : a), data[0])
  const labelEvery = Math.max(1, Math.ceil(data.length / 7))
  const hovered = active !== null ? data[active] : null

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Time in meetings</CardTitle>
        <CardDescription>
          {minutesLabel(total)} over the last {data.length} days
          {busiest?.minutes > 0 && ` · busiest day ${shortDate(busiest.date)}`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex gap-3">
          {/* y axis: clean round values only */}
          <div
            className="flex shrink-0 flex-col-reverse justify-between pb-6 text-right text-[11px] text-muted-foreground tabular-nums"
            aria-hidden
          >
            <span>0</span>
            <span>{minutesLabel(top / 2)}</span>
            <span>{minutesLabel(top)}</span>
          </div>
          <div className="relative min-w-0 flex-1">
            <div
              role="group"
              aria-label="Minutes in meetings per day"
              className="grid gap-[2px]"
              style={{ gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))` }}
              onPointerLeave={() => setActive(null)}
            >
              {data.map((d, i) => {
                const lit = d.minutes > 0 ? Math.max(1, Math.round((d.minutes / top) * LEVELS)) : 0
                return (
                  <button
                    key={d.date}
                    type="button"
                    aria-label={`${shortDate(d.date)}: ${minutesLabel(d.minutes)}, ${d.meetings} meeting${d.meetings === 1 ? "" : "s"}`}
                    onPointerEnter={() => setActive(i)}
                    onFocus={() => setActive(i)}
                    onBlur={() => setActive(null)}
                    className={cn(
                      "flex flex-col-reverse items-center gap-[2px] rounded-sm py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                      "transition-opacity duration-200",
                      active !== null && active !== i && "opacity-45",
                    )}
                  >
                    {Array.from({ length: LEVELS }).map((_, level) => (
                      <span
                        key={level}
                        className={cn(
                          "aspect-square w-full max-w-4 rounded-[3px]",
                          level < lit ? "bg-brand" : "bg-track",
                        )}
                      />
                    ))}
                  </button>
                )
              })}
            </div>
            {/* x axis: a few evenly spaced dates, today emphasised */}
            <div
              className="mt-2 grid text-[11px] text-muted-foreground"
              style={{ gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))` }}
              aria-hidden
            >
              {data.map((d, i) => {
                const last = i === data.length - 1
                const show = last || ((data.length - 1 - i) % labelEvery === 0 && data.length - 1 - i >= labelEvery / 2)
                return (
                  <span
                    key={d.date}
                    className={cn("text-center whitespace-nowrap", last && "font-medium text-foreground")}
                  >
                    {show ? (last ? "Today" : shortDate(d.date)) : ""}
                  </span>
                )
              })}
            </div>
            {hovered && active !== null && (
              <div
                className="pointer-events-none absolute -top-2 z-10 min-w-36 -translate-x-1/2 -translate-y-full rounded-lg bg-neutral-900 px-3 py-2 text-xs text-neutral-300 shadow-lg dark:bg-neutral-800"
                style={{ left: `${((active + 0.5) / data.length) * 100}%` }}
                role="status"
              >
                <div className="text-[11px] text-neutral-400">{shortDate(hovered.date)}</div>
                <div className="mt-0.5 text-base font-semibold text-white tabular-nums">
                  {minutesLabel(hovered.minutes)}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span className="h-0.5 w-2.5 rounded-full bg-brand" aria-hidden />
                  {hovered.meetings} meeting{hovered.meetings === 1 ? "" : "s"}
                </div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

/** Speaking time per person: thin bars in each person's own colour, the value at the tip. */
export function SpeakersChart({ data }: { data: Dashboard["speakers"] }) {
  const max = Math.max(1, ...data.map((d) => d.minutes))
  const sum = data.reduce((s, d) => s + d.minutes, 0)
  const top = data[0]

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Who talks most</CardTitle>
        <CardDescription>Speaking time across all meetings</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {data.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No voices yet"
            description="Confirm speakers after a meeting to see who contributes."
            className="h-full py-8"
          />
        ) : (
          <>
            <ul className="space-y-3">
              {data.slice(0, 6).map((d) => (
                <li
                  key={d.name}
                  className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3 text-[13px]"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ backgroundColor: colorFor(d.name) }}
                      aria-hidden
                    />
                    <span className="truncate">{d.name}</span>
                  </span>
                  <span className="h-2 overflow-hidden rounded-full bg-track" aria-hidden>
                    <span
                      className="block h-full rounded-r-[4px]"
                      style={{
                        width: `${(d.minutes / max) * 100}%`,
                        backgroundColor: colorFor(d.name),
                      }}
                    />
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {minutesLabel(d.minutes)}
                  </span>
                </li>
              ))}
            </ul>
            {top && sum > 0 && (
              <div className="mt-auto rounded-lg bg-muted/60 px-3 py-2.5">
                <p className="flex items-center gap-1.5 text-[13px] font-medium">
                  <Sparkles className="size-3.5 text-brand" aria-hidden />
                  {top.name} leads the conversation
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {Math.round((top.minutes / sum) * 100)}% of all speaking time, across{" "}
                  {top.meetings} meeting{top.meetings === 1 ? "" : "s"}.
                </p>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function NoActivity() {
  return (
    <EmptyState
      icon={BarChart3}
      title="No meetings yet"
      description="Record or upload your first meeting. Charts, action items and speaker stats appear here."
    />
  )
}
