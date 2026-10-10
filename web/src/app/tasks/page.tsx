"use client"

import * as React from "react"
import Link from "next/link"
import { Bell, CheckCheck, ListChecks, Search } from "lucide-react"
import { EmptyState, PageHeader } from "@/components/common"
import { reminderIsDue, useTasks } from "@/components/task-provider"
import { TaskRow } from "@/components/task-row"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type Filter = "open" | "reminders" | "completed" | "all"

export default function TasksPage() {
  const { tasks, loading, error, reload } = useTasks()
  React.useEffect(() => reload(), [reload])
  const [filter, setFilter] = React.useState<Filter>("open")
  const [query, setQuery] = React.useState("")
  const [project, setProject] = React.useState("all")
  const projects = [
    ...new Set(tasks.map((task) => task.project).filter((name): name is string => !!name)),
  ].sort()
  const counts = {
    open: tasks.filter((task) => !task.done).length,
    reminders: tasks.filter(reminderIsDue).length,
    completed: tasks.filter((task) => task.done).length,
    all: tasks.length,
  }
  const filtered = tasks.filter(
    (task) =>
      (filter === "all" ||
        (filter === "open" && !task.done) ||
        (filter === "completed" && task.done) ||
        (filter === "reminders" && reminderIsDue(task))) &&
      (project === "all" ||
        (project === "none" ? !task.project : `project:${task.project}` === project)) &&
      [task.text, task.owner, task.meeting_title, task.project].some((text) =>
        text?.toLowerCase().includes(query.trim().toLowerCase()),
      ),
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Tasks"
        description="Action items from your meetings, with reminders to keep things moving."
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="flex flex-wrap items-center gap-1 rounded-lg bg-muted/60 p-1"
          aria-label="Task status"
        >
          {(
            [
              ["open", "Open", ListChecks],
              ["reminders", "Reminders", Bell],
              ["completed", "Completed", CheckCheck],
              ["all", "All", null],
            ] as const
          ).map(([value, label, Icon]) => (
            <Button
              key={value}
              variant="ghost"
              size="sm"
              aria-pressed={filter === value}
              className={cn(
                "gap-1.5 text-xs text-muted-foreground",
                filter === value && "bg-card text-foreground shadow-xs",
              )}
              onClick={() => setFilter(value)}
            >
              {Icon && <Icon className="size-3.5" />}
              {label}
              <span className="text-muted-foreground tabular-nums">{counts[value]}</span>
            </Button>
          ))}
        </div>
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1 sm:w-56">
            <Search className="absolute top-2.5 left-2.5 size-3.5 text-muted-foreground" />
            <Input
              className="pl-8"
              placeholder="Search tasks…"
              aria-label="Search tasks"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <Select value={project} onValueChange={setProject}>
            <SelectTrigger className="w-40" aria-label="Filter tasks by project">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All projects</SelectItem>
              <SelectItem value="none">No project</SelectItem>
              {projects.map((name) => (
                <SelectItem key={name} value={`project:${name}`}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : error ? (
        <EmptyState icon={ListChecks} title="Could not load tasks" description={error.message}>
          <Button variant="outline" onClick={reload}>
            Retry
          </Button>
        </EmptyState>
      ) : !tasks.length ? (
        <EmptyState
          icon={ListChecks}
          title="No tasks yet"
          description="Action items will appear here when you generate meeting notes. Each new task starts with a reminder in one week."
        >
          <Button asChild variant="outline">
            <Link href="/record/">Record a meeting</Link>
          </Button>
        </EmptyState>
      ) : !filtered.length ? (
        <EmptyState
          icon={filter === "reminders" ? Bell : CheckCheck}
          title={filter === "reminders" ? "No reminders due" : "No matching tasks"}
          description={
            filter === "reminders"
              ? "Your upcoming reminders will appear here when their date arrives."
              : "Try another status, project or search."
          }
        />
      ) : (
        <Card className="gap-0 overflow-hidden py-0">
          {filter === "reminders" && (
            <div className="flex items-center gap-2 border-b bg-brand/5 px-5 py-3 text-xs text-brand">
              <Bell className="size-3.5" />
              Today and overdue
            </div>
          )}
          <ul>
            {filtered.map((task) => (
              <TaskRow key={`${task.id}:${task.done}:${task.reminder_date}`} task={task} />
            ))}
          </ul>
        </Card>
      )}
      <p className="text-xs text-muted-foreground">
        New tasks are set to remind you in one week. Click a reminder date to choose another day.
      </p>
    </div>
  )
}
