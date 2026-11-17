"use client"

import { Card } from "@astryxdesign/core/Card"
import { Text } from "@astryxdesign/core/Text"
import * as React from "react"
import { useReducedMotion } from "motion/react"

import { CountingNumber } from "@/components/animate-ui/primitives/texts/counting-number"
import { minutesLabel } from "@/components/dashboard/charts"
import type { Dashboard } from "@/lib/api"

/**
 * Change against the previous period, as plain text. Neutral on purpose: more time in meetings is
 * not good or bad by itself, so it shows direction without judging it.
 */
function change(value: number | null, vs: string) {
  if (value === null) return vs
  return `${value >= 0 ? "+" : "\u2212"}${Math.abs(Math.round(value))}% ${vs}`
}

export function Kpi({
  index,
  label,
  value,
  decimals = 0,
  text,
  footer,
}: {
  /** position in the row, for the staggered entrance */
  index: number
  label: string
  value?: number
  decimals?: number
  /** a ready-made value such as "2 h 21 min", shown instead of a counting number */
  text?: string
  footer: string
}) {
  const reduce = useReducedMotion()
  return (
    <div className="enter-stagger" style={{ "--i": index } as React.CSSProperties}>
      <Card padding={4}>
        <div className="flex flex-col gap-3">
          <Text type="supporting">{label}</Text>
          <div className="text-[30px] leading-none font-medium tracking-[-0.03em] tabular-nums">
            {text ??
              (reduce ? (
                (value ?? 0).toFixed(decimals)
              ) : (
                // critically damped: arrives quickly and settles without a long creeping tail
                <CountingNumber
                  number={value ?? 0}
                  decimalPlaces={decimals}
                  transition={{ bounce: 0, duration: 0.8 }}
                />
              ))}
          </div>
          <Text type="supporting" size="xsm">
            {footer}
          </Text>
        </div>
      </Card>
    </div>
  )
}

export function KpiCards({ data }: { data: Dashboard }) {
  const { period, totals } = data
  // with nothing to compare against, say what the number covers instead of a bare "vs …"
  const vs = (delta: number | null) =>
    delta === null ? `in the last ${period.days} days` : `vs previous ${period.days} days`
  return (
    <div className="grid grid-cols-2 gap-3 @3xl/main:grid-cols-4">
      <Kpi
        index={0}
        label="Meetings"
        value={period.meetings}
        footer={change(period.meetings_delta, vs(period.meetings_delta))}
      />
      <Kpi
        index={1}
        label="Time in meetings"
        text={minutesLabel(period.minutes)}
        footer={change(period.minutes_delta, vs(period.minutes_delta))}
      />
      <Kpi index={2} label="Open action items" value={totals.open_actions} footer={`${totals.done_actions} completed`} />
      <Kpi index={3} label="Voices recognised" value={totals.voices} footer="Saved in your local library" />
    </div>
  )
}
