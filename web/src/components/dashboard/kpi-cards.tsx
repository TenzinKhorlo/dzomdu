"use client"

import { ArrowDownRight, ArrowUpRight, AudioLines, CalendarDays, Clock, ListChecks } from "lucide-react"
import { useReducedMotion } from "motion/react"

import { CountingNumber } from "@/components/animate-ui/primitives/texts/counting-number"
import { Card } from "@/components/ui/card"
import type { Dashboard } from "@/lib/api"
import { cn } from "@/lib/utils"

/**
 * Change against the previous period. Neutral grey on purpose: more time in meetings is not
 * good or bad by itself, so the chip shows direction without judging it.
 */
function Delta({ value }: { value: number | null }) {
  if (value === null) return null
  const up = value >= 0
  const Icon = up ? ArrowUpRight : ArrowDownRight
  return (
    <span className="inline-flex items-center gap-0.5 rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium tabular-nums">
      <Icon className="size-3" aria-hidden />
      {up ? "+" : "−"}
      {Math.abs(Math.round(value))}%
      <span className="sr-only">{up ? "up" : "down"} on the previous period</span>
    </span>
  )
}

function Kpi({
  icon: Icon,
  tint,
  label,
  value,
  decimals = 0,
  suffix,
  delta,
  footer,
}: {
  icon: React.ComponentType<{ className?: string }>
  tint: string
  label: string
  value: number
  decimals?: number
  suffix?: string
  delta?: number | null
  footer: React.ReactNode
}) {
  const reduce = useReducedMotion()
  return (
    <Card className="gap-3 py-4">
      <div className="flex items-center gap-2 px-4">
        <span
          className="flex size-5 items-center justify-center rounded-md text-white"
          style={{ backgroundColor: tint }}
          aria-hidden
        >
          <Icon className="size-3" />
        </span>
        <span className="truncate text-[13px] font-medium">{label}</span>
      </div>
      <div className="px-4">
        <div className="text-2xl font-semibold tracking-[-0.02em] tabular-nums">
          {reduce ? (
            value.toFixed(decimals)
          ) : (
            // critically damped: arrives quickly and settles without a long creeping tail
            <CountingNumber
              number={value}
              decimalPlaces={decimals}
              transition={{ bounce: 0, duration: 0.8 }}
            />
          )}
          {suffix && (
            <span className="ml-0.5 text-sm font-medium text-muted-foreground">{suffix}</span>
          )}
        </div>
        <div
          className={cn(
            "mt-1.5 flex min-h-5 items-center gap-2 text-xs text-muted-foreground",
            delta != null && "justify-between",
          )}
        >
          {delta !== undefined && <Delta value={delta} />}
          <span className="truncate">{footer}</span>
        </div>
      </div>
    </Card>
  )
}

export function KpiCards({ data }: { data: Dashboard }) {
  const { period, totals } = data
  // with nothing to compare against, say what the number covers instead of a bare "vs …"
  const vs = (delta: number | null) =>
    delta === null ? `in the last ${period.days} days` : `vs previous ${period.days} days`
  return (
    <div className="grid grid-cols-2 gap-3 @5xl/main:grid-cols-4">
      <Kpi
        icon={CalendarDays}
        tint="var(--chart-2)"
        label="Meetings"
        value={period.meetings}
        delta={period.meetings_delta}
        footer={vs(period.meetings_delta)}
      />
      <Kpi
        icon={Clock}
        tint="var(--chart-3)"
        label="Time in meetings"
        value={period.minutes / 60}
        decimals={1}
        suffix="h"
        delta={period.minutes_delta}
        footer={vs(period.minutes_delta)}
      />
      <Kpi
        icon={ListChecks}
        tint="var(--brand)"
        label="Open action items"
        value={totals.open_actions}
        footer={`${totals.done_actions} completed · synced with your notes`}
      />
      <Kpi
        icon={AudioLines}
        tint="var(--chart-1)"
        label="Voices recognised"
        value={totals.voices}
        footer="Voiceprints stay on this computer"
      />
    </div>
  )
}
