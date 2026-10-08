"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { MessageSquareText, Mic, Radio, Search } from "lucide-react"

import { EmptyState, PageHeader } from "@/components/common"
import { MeetingTable } from "@/components/meeting-table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import type { ActiveSession, MeetingRow } from "@/lib/api"

const ALL = "__all__"

function MeetingsInner() {
  const params = useSearchParams()
  const router = useRouter()
  const { data } = useApi<{ meetings: MeetingRow[]; active: ActiveSession[] }>("/api/meetings", {
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
      <PageHeader
        title="Meetings"
        description={data ? `${data.meetings.length} meetings in your vault` : "Loading…"}
      >
        <Button asChild>
          <Link href="/record/">
            <Mic />
            New recording
          </Link>
        </Button>
      </PageHeader>

      {data?.active.map((s) => (
        <Link
          key={s.id}
          href={`/record/?session=${s.id}`}
          className="flex items-center gap-3 rounded-xl border border-brand/25 bg-brand/[0.05] px-4 py-3 text-[13px] hover:bg-brand/10"
        >
          <Radio className="size-4 text-brand" />
          <span className="font-medium">{s.title}</span>
          <Badge variant="secondary">{s.state}</Badge>
        </Link>
      ))}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setParam("q", e.target.value || null)}
            placeholder="Search titles, summaries, people…"
            className="pl-9"
          />
        </div>
        <Select
          value={project}
          onValueChange={(v) => setParam("project", v === ALL ? null : v)}
        >
          <SelectTrigger className="w-48">
            <SelectValue placeholder="All projects" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All projects</SelectItem>
            {projects.map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {!data ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : rows.length ? (
        <Card className="overflow-hidden py-0">
          <CardContent className="px-0">
            <MeetingTable meetings={rows} />
          </CardContent>
        </Card>
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
