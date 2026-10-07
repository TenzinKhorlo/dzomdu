"use client"

import Link from "next/link"
import { ArrowRight, ListChecks, Mic, Radio, Upload } from "lucide-react"

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
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import { useMounted } from "@/hooks/use-mounted"
import type { Dashboard } from "@/lib/api"
import { greeting } from "@/lib/format"

const STATE_LABEL: Record<string, string> = {
  recording: "Recording",
  processing: "Processing",
  review: "Waiting for speaker review",
  summarizing: "Writing notes",
}

export default function DashboardPage() {
  const { data, error, reload } = useApi<Dashboard>("/api/dashboard", { interval: 15000 })
  const mounted = useMounted()

  return (
    <div className="@container/main flex flex-col gap-6">
      <PageHeader
        title={mounted ? greeting() : "Welcome back"}
        description="Your meetings, decisions and action items, all processed on this computer."
      >
        <Button variant="outline" asChild>
          <Link href="/record/?upload=1">
            <Upload />
            Upload recording
          </Link>
        </Button>
        <Button asChild>
          <Link href="/record/">
            <Mic />
            Start recording
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
            className="flex items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm transition-colors hover:bg-primary/10"
          >
            <Radio className="size-4 text-primary" />
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
              <div className="grid gap-4 @5xl/main:grid-cols-3">
                <div className="@5xl/main:col-span-2">
                  <ActivityChart data={data.activity} />
                </div>
                <SpeakersChart data={data.speakers} />
              </div>
              <div className="grid gap-4 @5xl/main:grid-cols-3">
                <Card className="gap-0 overflow-hidden pb-0 @5xl/main:col-span-2">
                  <CardHeader className="pb-4">
                    <CardTitle>Recent meetings</CardTitle>
                    <CardDescription>Click a meeting to read its notes</CardDescription>
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
                <Card>
                  <CardHeader>
                    <CardTitle>Open action items</CardTitle>
                    <CardDescription>
                      {data.totals.open_actions} open · {data.totals.done_actions} done
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {data.actions.length ? (
                      <ActionList
                        items={data.actions.slice(0, 6)}
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
      <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-36 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 @5xl/main:grid-cols-3">
        <Skeleton className="h-80 rounded-xl @5xl/main:col-span-2" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </>
  )
}
