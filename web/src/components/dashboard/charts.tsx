"use client"

import * as React from "react"
import { BarChart3, Users } from "lucide-react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@ui-sdk/react/tooltip"

import { EmptyState } from "@/components/common"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/card"
import type { Dashboard } from "@/lib/api"
import { scatterBubbles } from "@/lib/bubbles"
import { colorFor, initials, shortDate } from "@/lib/format"
import { cn } from "@/lib/utils"

const LEVELS = 16 // marks per column; the chart height stays fixed across date ranges

/** A clean axis maximum: 15, 30, 60, 90, 120, 180, 240 … minutes. */
function niceMax(v: number) {
  const steps = [15, 30, 60, 90, 120, 180, 240, 360, 480, 720]
  return steps.find((s) => s >= v) ?? Math.ceil(v / 240) * 240
}

// same shape as duration() in lib/format: "15 min", "2 h 05 min"
export function minutesLabel(m: number) {
  if (m < 60) return `${Math.round(m)} min`
  const h = Math.floor(m / 60)
  const r = Math.round(m - h * 60)
  return r ? `${h} h ${String(r).padStart(2, "0")} min` : `${h} h`
}

/**
 * Time in meetings per day as a dot matrix: each column is a day, each lit mark is a sixteenth of
 * the axis. One series: the busiest day takes the brand accent, every other day a neutral step, on a
 * neutral track, with a per-column tooltip on hover and keyboard focus.
 */
export function ActivityChart({ data }: { data: Dashboard["activity"] }) {
  const [active, setActive] = React.useState<number | null>(null)
  const total = data.reduce((s, r) => s + r.minutes, 0)
  const top = niceMax(Math.max(1, ...data.map((r) => r.minutes)))
  const busiest = data.reduce((a, b) => (b.minutes > a.minutes ? b : a), data[0])
  const labelEvery = Math.max(1, Math.ceil(data.length / 6))
  const hovered = active !== null ? data[active] : null

  return (
    <Card className="h-full gap-5 shadow-none">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1.5">
          <CardTitle>Meeting activity</CardTitle>
          <CardDescription>
            Time in meetings over the last {data.length} days
          </CardDescription>
        </div>
        <CardAction className="hidden text-right @sm/card-header:block">
          <p className="text-lg leading-tight font-medium tracking-tight tabular-nums">{minutesLabel(total)}</p>
          <p className="mt-1 text-xs text-muted-foreground">Total meeting time</p>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">
        <div className="flex flex-1 gap-3">
          {/* y axis: clean round values only */}
          <div
            className="flex shrink-0 flex-col-reverse justify-between pb-6 text-right text-xs text-muted-foreground tabular-nums"
            aria-hidden
          >
            <span>0</span>
            <span>{minutesLabel(top / 2)}</span>
            <span>{minutesLabel(top)}</span>
          </div>
          <div className="relative flex min-w-0 flex-1 flex-col">
            <div
              role="group"
              aria-label="Minutes in meetings per day"
              className="grid min-h-[196px] flex-1 gap-0.5"
              style={{
                gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))`,
                columnGap: data.length > 60 ? 1 : 3,
              }}
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
                      "flex h-full min-w-0 flex-col-reverse items-center gap-0.5 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                      "transition-opacity duration-200",
                      active !== null && active !== i && "opacity-45",
                    )}
                  >
                    {Array.from({ length: LEVELS }).map((_, level) => (
                      <span
                        key={level}
                        className={cn(
                          "w-full max-w-5 flex-1 rounded-[2px]",
                          level < lit ? (d === busiest ? "bg-brand" : "bg-foreground/30") : "bg-track",
                        )}
                      />
                    ))}
                  </button>
                )
              })}
            </div>
            {/* x axis: a few evenly spaced dates, today emphasised */}
            <div
              className="relative mt-3 h-4 text-xs text-muted-foreground"
              aria-hidden
            >
              {data.map((d, i) => {
                const last = i === data.length - 1
                const show = last || ((data.length - 1 - i) % labelEvery === 0 && data.length - 1 - i >= labelEvery / 2)
                return (
                  show && <span
                    key={d.date}
                    className={cn("absolute whitespace-nowrap", !last && i !== 0 && "-translate-x-1/2", last && "font-medium text-foreground")}
                    style={last ? { right: 0 } : { left: i === 0 ? 0 : `${((i + 0.5) / data.length) * 100}%` }}
                  >
                    {last ? "Today" : shortDate(d.date)}
                  </span>
                )
              })}
            </div>
            {hovered && active !== null && (
              <div
                className="pointer-events-none absolute -top-2 z-10 min-w-36 -translate-x-1/2 -translate-y-full rounded-lg bg-neutral-900 px-3 py-2 text-xs text-neutral-300 shadow-lg dark:bg-neutral-800"
                style={{ left: `clamp(4.5rem, ${((active + 0.5) / data.length) * 100}%, calc(100% - 4.5rem))` }}
                role="status"
              >
                <div className="text-xs text-neutral-400">{shortDate(hovered.date)}</div>
                <div className="mt-0.5 text-base font-medium text-white tabular-nums">
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
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
          {busiest?.minutes > 0 ? (
            <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-sm bg-brand" aria-hidden />Busiest day · {shortDate(busiest.date)}</span>
          ) : (
            <span />
          )}
          <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-sm bg-foreground/30" aria-hidden />Other days</span>
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * Speaking time per person as bubbles: area is proportional to time, so a person with twice the
 * minutes has twice the area. Each person keeps the colour they have everywhere else (SpeakerAvatar). Circles are scattered
 * at seeded-random spots and may overlap, but fills are translucent so every circle stays visible; the name, exact time and share open on hover or focus.
 */
export function SpeakersChart({ data }: { data: Dashboard["speakers"] }) {
  const people = data.slice(0, 6)
  const bubbles = scatterBubbles(people.map((d) => d.minutes), people.map((d) => d.name).join("|"))
  const sum = data.reduce((s, d) => s + d.minutes, 0)
  const top = data[0]

  return (
    <Card className="h-full shadow-none">
      <CardHeader>
        <CardTitle>Speaking time</CardTitle>
        <CardDescription>Contributions across your meetings</CardDescription>
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
            <div className="flex flex-1 items-center">
              <ul className="relative w-full" style={{ aspectRatio: "100 / 72" }}>
                {people.map((d, i) => {
                  const b = bubbles[i]
                  const color = colorFor(d.name)
                  const share = sum > 0 ? Math.round((d.minutes / sum) * 100) : 0
                  return (
                    <li
                      key={d.name}
                      className="absolute hover:z-10 focus-within:z-10"
                      style={{
                        left: `${((b.cx - b.d / 2) / 100) * 100}%`,
                        top: `${((b.cy - b.d / 2) / 72) * 100}%`,
                        width: `${b.d}%`,
                        aspectRatio: "1",
                      }}
                    >
                      <Tooltip>
                        <TooltipTrigger
                          aria-label={`${d.name}, ${minutesLabel(d.minutes)}`}
                          className="grid size-full cursor-default place-items-center rounded-full border-0 text-sm font-medium tabular-nums transition-[filter] outline-none hover:brightness-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                          style={{
                            color,
                            backgroundColor: `color-mix(in oklch, ${color} 22%, transparent)`,
                            boxShadow: `inset 0 0 0 1.5px color-mix(in oklch, ${color} 55%, transparent)`,
                          }}
                        >
                          {initials(d.name)}
                        </TooltipTrigger>
                        <TooltipContent>
                          <span className="block font-medium">{d.name}</span>
                          <span className="block whitespace-nowrap tabular-nums">
                            {`${minutesLabel(d.minutes)} · ${share}% · ${d.meetings} meeting${d.meetings === 1 ? "" : "s"}`}
                          </span>
                        </TooltipContent>
                      </Tooltip>
                    </li>
                  )
                })}
              </ul>
            </div>
            {top && sum > 0 && (
              <div className="mt-auto border-t pt-3 text-xs leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">{top.name}</span> contributed {Math.round((top.minutes / sum) * 100)}% of speaking time across {top.meetings} meeting{top.meetings === 1 ? "" : "s"}.
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
      title="Your next conversation starts here"
      description="Record a meeting or upload audio to see your activity, notes, and action items in one place."
      className="min-h-72 bg-card"
    />
  )
}
