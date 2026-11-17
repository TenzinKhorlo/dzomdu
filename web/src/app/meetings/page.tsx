"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@astryxdesign/core/Button"
import { ClickableCard } from "@astryxdesign/core/ClickableCard"
import { Heading } from "@astryxdesign/core/Heading"
import { Icon } from "@astryxdesign/core/Icon"
import { Selector } from "@astryxdesign/core/Selector"
import { Text } from "@astryxdesign/core/Text"
import { TextInput } from "@astryxdesign/core/TextInput"
import { MessageSquareText, Mic, Radio, Search } from "lucide-react"

import { EmptyState } from "@/components/common"
import { MeetingTable } from "@/components/meeting-table"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import type { ActiveSession, MeetingRow } from "@/lib/api"
import { STATE_LABEL } from "@/lib/format"

const ALL = "__all__"

function MeetingsInner() {
  const params = useSearchParams()
  const router = useRouter()
  const { data, reload } = useApi<{ meetings: MeetingRow[]; active: ActiveSession[] }>("/api/meetings", {
    interval: 10000,
  })
  const query = params.get("q") ?? ""
  const project = params.get("project") ?? ALL
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params.toString())
    if (value) next.set(key, value)
    else next.delete(key)
    const qs = next.toString()
    router.replace(qs ? `/meetings/?${qs}` : "/meetings/")
  }

  const projects = React.useMemo(
    () => [...new Set((data?.meetings ?? []).map((m) => m.project).filter(Boolean))] as string[],
    [data],
  )
  const q = query.trim().toLowerCase()
  const rows = (data?.meetings ?? []).filter(
    (m) =>
      (project === ALL || m.project === project) &&
      (!q ||
        [m.title, m.summary, m.project, ...m.people].some((v) => v?.toLowerCase().includes(q))),
  )

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
        <div className="space-y-1.5">
          <Heading level={1}>Meetings</Heading>
          {/* the line is always there, so the page doesn't jump when the count arrives */}
          <Text type="supporting" display="block" className="min-h-5">
            {data ? `${data.meetings.length} meetings in your vault` : "\u00A0"}
          </Text>
        </div>
        <Button variant="primary" label="New recording" icon={<Icon icon={Mic} />} href="/record/" />
      </div>

      {data?.active.map((s) => (
        <ClickableCard key={s.id} label={s.title} href={`/record/?session=${s.id}`} padding={3}>
          <div className="flex items-center gap-3">
            <Icon icon={Radio} color="accent" />
            <Text weight="medium">{s.title}</Text>
            <Text type="supporting">{STATE_LABEL[s.state] ?? s.state}</Text>
          </div>
        </ClickableCard>
      ))}

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full max-w-sm">
          <TextInput
            label="Search"
            isLabelHidden
            type="search"
            startIcon={Search}
            placeholder="Search"
            hasClear
            value={query}
            onChange={(v) => setParam("q", v || null)}
          />
        </div>
        <div className="w-48">
          <Selector
            label="Project"
            isLabelHidden
            hasSearch={projects.length > 6}
            value={project}
            onChange={(v) => setParam("project", !v || v === ALL ? null : v)}
            options={[{ value: ALL, label: "All projects" }, ...projects.map((p) => ({ value: p, label: p }))]}
          />
        </div>
      </div>

      {!data ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : rows.length ? (
        <div className="overflow-hidden rounded-[var(--radius-container)] border bg-card">
          <MeetingTable meetings={rows} onDeleted={reload} />
        </div>
      ) : (
        <EmptyState
          icon={MessageSquareText}
          title={data.meetings.length ? "No meetings match" : "No meetings yet"}
          description={
            data.meetings.length
              ? "Try another search or project."
              : "Record or upload a meeting and its notes appear here."
          }
        />
      )}
    </>
  )
}

export default function MeetingsPage() {
  return (
    <div className="@container/main flex flex-col gap-6">
      <React.Suspense fallback={<Skeleton className="h-96 rounded-xl" />}>
        <MeetingsInner />
      </React.Suspense>
    </div>
  )
}
