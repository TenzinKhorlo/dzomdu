"use client"

import { TrendingDown, TrendingUp } from "lucide-react"

import { CountingNumber } from "@/components/animate-ui/primitives/texts/counting-number"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { Dashboard } from "@/lib/api"

function Trend({ delta }: { delta: number | null }) {
  if (delta === null) return null
  const up = delta >= 0
  return (
    <Badge variant="outline" className="gap-1">
      {up ? <TrendingUp /> : <TrendingDown />}
      {up ? "+" : ""}
      {Math.round(delta)}%
    </Badge>
  )
}

function Kpi({
  label,
  value,
  decimals = 0,
  suffix,
  trend,
  footer,
  hint,
}: {
  label: string
  value: number
  decimals?: number
  suffix?: string
  trend?: React.ReactNode
  footer: React.ReactNode
  hint: string
}) {
  return (
    <Card className="@container/card bg-gradient-to-t from-primary/5 to-card shadow-xs dark:bg-card">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          <CountingNumber number={value} decimalPlaces={decimals} />
          {suffix && <span className="ml-1 text-base font-medium text-muted-foreground">{suffix}</span>}
        </CardTitle>
        {trend && <CardAction>{trend}</CardAction>}
      </CardHeader>
      <CardFooter className="flex-col items-start gap-1 text-sm">
        <div className="line-clamp-1 flex gap-2 font-medium">{footer}</div>
        <div className="text-muted-foreground">{hint}</div>
      </CardFooter>
    </Card>
  )
}

export function KpiCards({ data }: { data: Dashboard }) {
  const { period, totals } = data
  const hours = period.minutes / 60
  return (
    <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
      <Kpi
        label={`Meetings · last ${period.days} days`}
        value={period.meetings}
        trend={<Trend delta={period.meetings_delta} />}
        footer={`${totals.meetings} meetings recorded in total`}
        hint="Compared with the previous period"
      />
      <Kpi
        label={`Time in meetings · last ${period.days} days`}
        value={hours}
        decimals={1}
        suffix="h"
        trend={<Trend delta={period.minutes_delta} />}
        footer={`${totals.hours} h transcribed overall`}
        hint="Recorded and processed locally"
      />
      <Kpi
        label="Open action items"
        value={totals.open_actions}
        footer={`${totals.done_actions} completed`}
        hint="Synced with the tasks in your notes"
      />
      <Kpi
        label="Voices recognised"
        value={totals.voices}
        footer="Remembered across meetings"
        hint="Voiceprints stay on this computer"
      />
    </div>
  )
}
