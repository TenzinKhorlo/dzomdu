"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowRight, CalendarDays, ListChecks, Mic, Radio, Upload } from "lucide-react"

import { ActionList } from "@/components/action-list"
import { Fade } from "@/components/animate-ui/primitives/effects/fade"
import { EmptyState, PageHeader } from "@/components/common"
import { ActivityChart, NoActivity, SpeakersChart } from "@/components/dashboard/charts"
import { KpiCards } from "@/components/dashboard/kpi-cards"
import { MeetingTable } from "@/components/meeting-table"
import { Badge } from "@/components/ui/badge"
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import type { Dashboard } from "@/lib/api"

const STATE_LABEL: Record<string, string> = {
  recording: "Recording",
  processing: "Processing",
  review: "Waiting for speaker review",
  summarizing: "Writing notes",
}

export default function DashboardPage() {
  const [days, setDays] = React.useState("30")
  const { data, error, reload } = useApi<Dashboard>(`/api/dashboard?days=${days}`, {
    interval: 15000,
  })

  return (
    <div className="@container/main flex flex-col gap-5">
      <PageHeader
        title="Overview"
        description="Your meetings, conversations, and next steps at a glance."
        actionsClassName="grid w-full grid-cols-2 sm:flex sm:w-auto"
      >
        <Select value={days} onValueChange={setDays}>
          <SelectTrigger aria-label="Period" className="col-span-2 w-full gap-1.5 sm:w-auto">
            <CalendarDays className="text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            <SelectItem value="7">Last 7 days</SelectItem>
            <SelectItem value="30">Last 30 days</SelectItem>
            <SelectItem value="90">Last 90 days</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" asChild>
          <Link href="/record/?upload=1">
            <Upload />
            Upload audio
          </Link>
        </Button>
        <Button asChild>
          <Link href="/record/">
            <Mic />
            New recording
          </Link>
        </Button>
      </PageHeader>

      {error && (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>Cannot reach the Dzomdu backend</CardTitle>
            <CardDescription>
              Start it with <code className="font-mono">dzomdu ui</code>. ({error.message})
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {data?.active.map((s) => (
        <Fade key={s.id}>
          <Link
            href={`/record/?session=${s.id}`}
            className="flex items-center gap-3 rounded-xl border border-brand/25 bg-brand/[0.05] px-4 py-3 text-[13px] transition-colors hover:bg-brand/10"
          >
            <Radio className="size-4 text-brand" />
            <span className="font-medium">{s.title}</span>
            <Badge variant="secondary">{STATE_LABEL[s.state] ?? s.state}</Badge>
            <ArrowRight className="ml-auto size-4 text-muted-foreground" />
          </Link>
        </Fade>
      ))}

      {!data && !error ? (
        <DashboardSkeleton />
      ) : data ? (
        <>
          <KpiCards data={data} />
          {data.totals.meetings === 0 ? (
            <NoActivity />
          ) : (
            <>
              <div className="grid gap-3 @5xl/main:grid-cols-3">
                <div className="@5xl/main:col-span-2">
                  <ActivityChart data={data.activity} />
                </div>
                <SpeakersChart data={data.speakers} />
              </div>
              <div className="grid gap-3 @5xl/main:grid-cols-3">
                <Card className="gap-0 overflow-hidden pb-0 shadow-none @5xl/main:col-span-2">
                  <CardHeader className="pb-4">
                    <CardTitle>Recent meetings</CardTitle>
                    <CardDescription>Your latest conversations and meeting notes</CardDescription>
                    <CardAction>
                      <Button variant="ghost" size="sm" asChild>
                        <Link href="/meetings/">
                          View all
                          <ArrowRight />
                        </Link>
                      </Button>
                    </CardAction>
                  </CardHeader>
                  <CardContent className="border-t px-0">
                    <MeetingTable meetings={data.recent} compact />
                  </CardContent>
                </Card>
                <Card className="shadow-none">
                  <CardHeader>
                    <CardTitle>Action items</CardTitle>
                    <CardDescription>
                      {data.totals.open_actions} open · {data.totals.done_actions} completed
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {data.actions.length ? (
                      <ActionList
                        items={data.actions.slice(0, 4)}
                        showMeeting
                        onChange={reload}
                      />
                    ) : (
                      <EmptyState
                        icon={ListChecks}
                        title="All clear"
                        description="No open action items."
                        className="py-8"
                      />
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </>
      ) : null}
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 @3xl/main:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[142px] rounded-xl" />
        ))}
      </div>
      <div className="grid gap-3 @5xl/main:grid-cols-3">
        <Skeleton className="h-80 rounded-xl @5xl/main:col-span-2" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </>
  )
}
