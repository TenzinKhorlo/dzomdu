"use client"

import * as React from "react"
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { EmptyState } from "@/components/common"
import type { Dashboard } from "@/lib/api"
import { colorFor, shortDate } from "@/lib/format"
import { BarChart3, Users } from "lucide-react"

const activityConfig = {
  minutes: { label: "Minutes", color: "var(--chart-1)" },
  meetings: { label: "Meetings", color: "var(--chart-2)" },
} satisfies ChartConfig

export function ActivityChart({ data }: { data: Dashboard["activity"] }) {
  const [range, setRange] = React.useState<7 | 30>(30)
  const rows = data.slice(-range)
  const total = rows.reduce((s, r) => s + r.minutes, 0)

  return (
    <Card className="@container/card">
      <CardHeader>
        <CardTitle>Time in meetings</CardTitle>
        <CardDescription>
          {Math.round(total)} minutes over the last {range} days
        </CardDescription>
        <CardAction>
          <div className="flex rounded-lg border p-0.5">
            {([7, 30] as const).map((r) => (
              <Button
                key={r}
                size="sm"
                variant={range === r ? "secondary" : "ghost"}
                className="h-7 px-2.5 text-xs"
                onClick={() => setRange(r)}
              >
                {r} days
              </Button>
            ))}
          </div>
        </CardAction>
      </CardHeader>
      <CardContent className="px-2 pt-2 sm:px-6">
        <ChartContainer config={activityConfig} className="aspect-auto h-[240px] w-full">
          <BarChart data={rows} margin={{ left: 0, right: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={28}
              tickFormatter={(v) => shortDate(v)}
            />
            <YAxis hide />
            <ChartTooltip
              cursor={{ fill: "var(--muted)", opacity: 0.6 }}
              content={
                <ChartTooltipContent
                  indicator="dot"
                  labelFormatter={(_, p) => shortDate(p?.[0]?.payload?.date)}
                />
              }
            />
            <Bar
              dataKey="minutes"
              fill="var(--color-minutes)"
              radius={[5, 5, 2, 2]}
              maxBarSize={range === 7 ? 44 : 18}
            />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

export function SpeakersChart({ data }: { data: Dashboard["speakers"] }) {
  const config = { minutes: { label: "Minutes speaking" } } satisfies ChartConfig
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <CardTitle>Who talks most</CardTitle>
        <CardDescription>Speaking time across all meetings</CardDescription>
      </CardHeader>
      <CardContent className="flex-1">
        {data.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No voices yet"
            description="Confirm speakers after a meeting to see who contributes."
            className="h-full py-8"
          />
        ) : (
          <ChartContainer config={config} className="aspect-auto h-[240px] w-full">
            <BarChart data={data} layout="vertical" margin={{ left: 0, right: 16 }}>
              <XAxis type="number" hide />
              <YAxis
                dataKey="name"
                type="category"
                tickLine={false}
                axisLine={false}
                width={118}
                tick={({ x, y, payload }) => (
                  <text x={x} y={y} dy={4} textAnchor="end" className="fill-foreground text-xs">
                    {payload.value.length > 17 ? payload.value.slice(0, 16) + "…" : payload.value}
                  </text>
                )}
              />
              <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel={false} />} />
              <Bar dataKey="minutes" radius={6} barSize={18}>
                {data.map((d) => (
                  <Cell key={d.name} fill={colorFor(d.name)} />
                ))}
              </Bar>
            </BarChart>
          </ChartContainer>
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
