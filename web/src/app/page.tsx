"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowRight, ListChecks, Mic, Radio, Upload } from "lucide-react"
import { Button as AstryxButton } from "@astryxdesign/core/Button"
import { ClickableCard } from "@astryxdesign/core/ClickableCard"
import { Heading } from "@astryxdesign/core/Heading"
import { Icon } from "@astryxdesign/core/Icon"
import { Selector } from "@astryxdesign/core/Selector"
import { Text } from "@astryxdesign/core/Text"

import { ActionList } from "@/components/action-list"
import { Fade } from "@/components/animate-ui/primitives/effects/fade"
import { EmptyState } from "@/components/common"
import { ActivityChart, NoActivity, SpeakersChart } from "@/components/dashboard/charts"
import { KpiCards } from "@/components/dashboard/kpi-cards"
import { MeetingTable } from "@/components/meeting-table"
import { RecoveredRecordings } from "@/components/recovered-recordings"
import { Button } from "@/components/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import type { Dashboard } from "@/lib/api"
import { STATE_LABEL } from "@/lib/format"

export default function DashboardPage() {
  const [days, setDays] = React.useState("30")
  const { data, error, reload } = useApi<Dashboard>(`/api/dashboard?days=${days}`, {
    interval: 15000,
  })

  return (
    <div className="@container/main flex flex-col gap-5">
      <Fade className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
        <Heading level={1}>Overview</Heading>
        <div className="flex flex-wrap items-center gap-2">
          <Selector
            label="Period"
            isLabelHidden
            variant="secondary"
            value={days}
            onChange={setDays}
            options={[
              { value: "7", label: "Last 7 days" },
              { value: "30", label: "Last 30 days" },
              { value: "90", label: "Last 90 days" },
            ]}
          />
          <AstryxButton label="Upload audio" icon={<Icon icon={Upload} />} href="/record/?upload=1" />
          <AstryxButton variant="primary" label="New recording" icon={<Icon icon={Mic} />} href="/record/" />
        </div>
      </Fade>

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

      <RecoveredRecordings />

      {data?.active.map((s) => (
        <Fade key={s.id}>
          <ClickableCard label={s.title} href={`/record/?session=${s.id}`} padding={3}>
            <div className="flex items-center gap-3">
              <Icon icon={Radio} color="accent" />
              <Text weight="medium">{s.title}</Text>
              <Text type="supporting">{STATE_LABEL[s.state] ?? s.state}</Text>
              <span className="ml-auto">
                <Icon icon={ArrowRight} color="secondary" />
              </span>
            </div>
          </ClickableCard>
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
                  <CardContent className="border-t px-[11px]">
                    <MeetingTable meetings={data.recent} compact />
                  </CardContent>
                </Card>
                <Card className="gap-0 shadow-none">
                  <CardHeader className="pb-4">
                    <CardTitle>Action items</CardTitle>
                    <CardDescription>
                      {data.totals.open_actions} open · {data.totals.done_actions} completed
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="border-t pb-3">
                    {data.actions.length ? (
                      <ActionList
                        items={data.actions.slice(0, 3)}
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
          <Skeleton key={i} className="h-36 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-3 @5xl/main:grid-cols-3">
        <Skeleton className="h-80 rounded-xl @5xl/main:col-span-2" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </>
  )
}
