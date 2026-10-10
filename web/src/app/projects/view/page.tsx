"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, CheckCheck, Folder, ListChecks, MessageSquare, Mic, Users } from "lucide-react"

import { useChatHistory } from "@/components/chat/provider"
import { EmptyState, PageHeader, SpeakerAvatar } from "@/components/common"
import { MeetingTable } from "@/components/meeting-table"
import { ProjectActions } from "@/components/project-actions"
import { ProjectTeamDialog } from "@/components/project-team-dialog"
import { useTasks } from "@/components/task-provider"
import { TaskRow } from "@/components/task-row"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import { ApiError, projectHref, type ProjectOverview } from "@/lib/api"
import { cn } from "@/lib/utils"

function ProjectView({ name }: { name: string }) {
  const router = useRouter()
  const { data, error, loading, reload } = useApi<ProjectOverview>(
    `/api/projects/${encodeURIComponent(name)}/overview`,
    { interval: 30000 },
  )
  const { reload: reloadTasks } = useTasks()
  const { chats } = useChatHistory()
  const [owner, setOwner] = React.useState("all")
  function changed() {
    reload()
    reloadTasks()
  }

  if (loading)
    return (
      <div className="space-y-5">
        <Skeleton className="h-20 w-full" />
        <div className="grid gap-4 sm:grid-cols-3">
          {[1, 2, 3].map((id) => (
            <Skeleton key={id} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-72 w-full" />
      </div>
    )
  if (error || !data)
    return (
      <EmptyState
        icon={Folder}
        title={
          error instanceof ApiError && error.status === 404
            ? "Project not found"
            : "Could not load project"
        }
        description={error?.message}
      >
        <Button variant="outline" onClick={reload}>
          Retry
        </Button>
        <Button asChild variant="ghost">
          <Link href="/projects/">Back to projects</Link>
        </Button>
      </EmptyState>
    )
  const tasks = data.open_tasks.filter(
    (task) =>
      owner === "all" || (owner === "none" ? !task.owner : `person:${task.owner}` === owner),
  )
  const owners = [
    ...new Set([
      ...data.team.map((person) => person.name),
      ...(owner.startsWith("person:") ? [owner.slice(7)] : []),
    ]),
  ].sort()
  const conversations = chats.filter((chat) => chat.project === data.name)
  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/projects/"
        className="inline-flex w-fit items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Projects
      </Link>
      <PageHeader
        title={data.name}
        description={
          <span className="line-clamp-3 whitespace-pre-line">
            {data.overview || "Your team, meetings, and next steps in one place."}
          </span>
        }
      >
        <Button asChild>
          <Link href={`/record/?project=${encodeURIComponent(data.name)}`}>
            <Mic />
            New meeting
          </Link>
        </Button>
        <ProjectActions
          project={data}
          onChanged={(nextName) => router.replace(nextName ? projectHref(nextName) : "/projects/")}
        />
      </PageHeader>
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          {
            title: "Meetings",
            value: data.meetings,
            detail: `${Math.round(data.minutes)} minutes recorded`,
            icon: MessageSquare,
          },
          {
            title: "Team",
            value: data.team.length,
            detail: `${data.members.length} assigned to this project`,
            icon: Users,
          },
          {
            title: "Remaining tasks",
            value: data.open_tasks.length,
            detail: `${data.completed_tasks} completed · ${data.unassigned_tasks} unassigned`,
            icon: ListChecks,
          },
        ].map((stat) => (
          <Card key={stat.title} className="gap-2 py-4">
            <CardContent>
              <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                <span>{stat.title}</span>
                <stat.icon className="size-4" />
              </div>
              <p className="text-2xl font-semibold tabular-nums">{stat.value}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stat.detail}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card className="min-w-0 gap-3">
          <CardHeader className="gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>Team members</CardTitle>
              <ProjectTeamDialog project={data} onChanged={reload} />
            </div>
            <CardDescription>
              Assigned members and people involved in this project’s meetings and tasks.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!data.team.length ? (
              <p className="py-5 text-[13px] text-muted-foreground">
                No team members yet. Assign your team with Manage team.
              </p>
            ) : (
              <ul className="space-y-1">
                {data.team.map((person) => (
                  <li key={person.name}>
                    <button
                      type="button"
                      disabled={person.open_tasks === 0}
                      aria-label={`Show tasks assigned to ${person.name}`}
                      onClick={() => setOwner(`person:${person.name}`)}
                      className={cn(
                        "flex w-full items-start gap-3 rounded-lg px-2 py-3 text-left enabled:hover:bg-muted/60",
                        owner === `person:${person.name}` && "bg-muted/60",
                      )}
                    >
                      <SpeakerAvatar name={person.name} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">
                          {person.name}
                        </span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {[person.role, person.organisation].filter(Boolean).join(" · ") ||
                            (person.assigned
                              ? "Assigned to project"
                              : person.meetings
                                ? "Meeting participant"
                                : "Task assignee")}
                        </span>
                        <span className="mt-2 block text-[11px] text-muted-foreground">
                          {person.meetings} meetings · {person.open_tasks} open tasks
                        </span>
                        {person.assigned && (person.role || person.organisation) && (
                          <Badge variant="outline" className="mt-2 text-[10px] font-normal">
                            Assigned
                          </Badge>
                        )}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card className="min-w-0 gap-3">
          <CardHeader className="gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <CardTitle>
                Remaining tasks{" "}
                <span className="ml-1 text-muted-foreground tabular-nums">
                  {data.open_tasks.length}
                </span>
              </CardTitle>
              <Select value={owner} onValueChange={setOwner}>
                <SelectTrigger aria-label="Filter tasks by assignee" className="max-w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All assignees</SelectItem>
                  <SelectItem value="none">Unassigned</SelectItem>
                  {owners.map((person) => (
                    <SelectItem key={person} value={`person:${person}`}>
                      {person}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <CardDescription>Each task links to the meeting where it was recorded.</CardDescription>
          </CardHeader>
          <CardContent className="px-4 sm:px-5">
            {tasks.length ? (
              <ul>
                {tasks.map((task) => (
                  <TaskRow
                    key={`${task.id}:${task.done}:${task.reminder_date}`}
                    task={task}
                    onChanged={reload}
                    showProject={false}
                  />
                ))}
              </ul>
            ) : (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <CheckCheck className="size-6 text-muted-foreground" />
                <p className="text-[13px] text-muted-foreground">
                  {data.open_tasks.length
                    ? "No remaining tasks for this assignee."
                    : "No remaining tasks. You’re up to date."}
                </p>
                {owner !== "all" && (
                  <Button variant="ghost" size="sm" onClick={() => setOwner("all")}>
                    Show all tasks
                  </Button>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
      <Card className="gap-4 overflow-hidden pb-0">
        <CardHeader>
          <CardTitle>Meeting history</CardTitle>
          <CardDescription>All meetings in {data.name}, most recent first.</CardDescription>
        </CardHeader>
        {data.meeting_rows.length ? (
          <MeetingTable meetings={data.meeting_rows} compact onDeleted={changed} />
        ) : (
          <div className="px-6 pb-8 text-[13px] text-muted-foreground">
            No meetings yet. Record your first meeting in this project.
          </div>
        )}
      </Card>
      {conversations.length > 0 && (
        <Link
          href={`/chat/history/?project=${encodeURIComponent(data.name)}`}
          className="inline-flex w-fit items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
        >
          <MessageSquare className="size-3.5" />
          {conversations.length} linked conversation{conversations.length === 1 ? "" : "s"}
        </Link>
      )}
    </div>
  )
}

function ProjectRoute() {
  const name = useSearchParams().get("name")
  return name ? (
    <ProjectView key={name} name={name} />
  ) : (
    <EmptyState
      icon={Folder}
      title="Choose a project"
      description="Open a project from the sidebar or the Projects page."
    >
      <Button asChild variant="outline">
        <Link href="/projects/">View projects</Link>
      </Button>
    </EmptyState>
  )
}

export default function ProjectPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-80 w-full" />}>
      <ProjectRoute />
    </React.Suspense>
  )
}
