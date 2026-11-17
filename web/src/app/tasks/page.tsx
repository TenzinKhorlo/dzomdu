"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { Heading } from "@astryxdesign/core/Heading"
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl"
import { Selector } from "@astryxdesign/core/Selector"
import { Text } from "@astryxdesign/core/Text"
import { TextInput } from "@astryxdesign/core/TextInput"
import { Bell, CheckCheck, ListChecks, Search } from "lucide-react"
import { EmptyState } from "@/components/common"
import { reminderIsDue, useTasks } from "@/components/task-provider"
import { TaskRow } from "@/components/task-row"
import { Skeleton } from "@/components/ui/skeleton"

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
      <Heading level={1}>Tasks</Heading>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SegmentedControl label="Task status" value={filter} onChange={(value) => setFilter(value as Filter)}>
          <SegmentedControlItem value="open" label={`Open ${counts.open}`} />
          <SegmentedControlItem value="reminders" label={`Reminders ${counts.reminders}`} />
          <SegmentedControlItem value="completed" label={`Completed ${counts.completed}`} />
          <SegmentedControlItem value="all" label={`All ${counts.all}`} />
        </SegmentedControl>
        <div className="flex gap-2">
          <div className="min-w-0 flex-1 sm:w-56">
            <TextInput
              label="Search tasks"
              isLabelHidden
              type="search"
              startIcon={Search}
              placeholder="Search"
              hasClear
              value={query}
              onChange={setQuery}
            />
          </div>
          <div className="w-40">
            <Selector
              label="Filter tasks by project"
              isLabelHidden
              hasSearch={projects.length > 6}
              value={project}
              onChange={(value) => setProject(value ?? "all")}
              options={[
                { value: "all", label: "All projects" },
                { value: "none", label: "No project" },
                ...projects.map((name) => ({ value: `project:${name}`, label: name })),
              ]}
            />
          </div>
        </div>
      </div>
      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : error ? (
        <EmptyState icon={ListChecks} title="Could not load tasks" description={error.message}>
          <Button label="Retry" onClick={reload} />
        </EmptyState>
      ) : !tasks.length ? (
        <EmptyState
          icon={ListChecks}
          title="No tasks yet"
          description="Action items appear here once a meeting's notes are written."
        >
          <Button label="Record a meeting" href="/record/" />
        </EmptyState>
      ) : !filtered.length ? (
        <EmptyState
          icon={filter === "reminders" ? Bell : CheckCheck}
          title={filter === "reminders" ? "No reminders due" : "No matching tasks"}
          description={
            filter === "reminders"
              ? "Upcoming reminders appear here when their date arrives."
              : "Try another status, project or search."
          }
        />
      ) : (
        <div className="overflow-hidden rounded-[var(--radius-container)] border bg-card">
          {filter === "reminders" && (
            <div className="border-b px-5 py-3">
              <Text type="supporting">Due today or overdue</Text>
            </div>
          )}
          <ul>
            {filtered.map((task) => (
              <TaskRow key={`${task.id}:${task.done}:${task.reminder_date}`} task={task} />
            ))}
          </ul>
        </div>
      )}
      {tasks.length > 0 && (
        <Text type="supporting" size="xsm">
          New tasks remind you in one week. Select a reminder date to choose another day.
        </Text>
      )}
    </div>
  )
}
