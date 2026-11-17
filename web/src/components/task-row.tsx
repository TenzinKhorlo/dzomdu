"use client"

import * as React from "react"
import Link from "next/link"
import { Button } from "@astryxdesign/core/Button"
import { DateInput } from "@astryxdesign/core/DateInput"
import { ArrowUpRight, Loader2 } from "lucide-react"
import { toast } from "@/lib/toast"
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/dialog"
import { localDate, reminderIsDue, useTasks } from "@/components/task-provider"
import { api, projectHref, type OpenTask } from "@/lib/api"
import { shortDate } from "@/lib/format"
import { cn } from "@/lib/utils"

type Patch = { done?: boolean; reminder_date?: string }

function ReminderDialog({
  task,
  update,
}: {
  task: OpenTask
  update: (patch: Patch) => Promise<boolean>
}) {
  const [open, setOpen] = React.useState(false)
  const [date, setDate] = React.useState(task.reminder_date ?? "")
  const [saving, setSaving] = React.useState(false)
  const due = reminderIsDue(task)

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!date || saving) return
    setSaving(true)
    if (await update({ reminder_date: date })) setOpen(false)
    setSaving(false)
  }

  return (
    <>
      {/* a date chip: it looks like what it is, a date you can change */}
      <button
        type="button"
        className={cn("time-chip text-muted-foreground", due && "text-brand")}
        aria-label={`Change reminder for ${task.text}`}
        onClick={() => {
          setDate(task.reminder_date ?? "")
          setOpen(true)
        }}
      >
        {task.reminder_date ? `Remind ${shortDate(task.reminder_date)}` : "Set reminder"}
      </button>
      <Dialog open={open} onOpenChange={(value) => !saving && setOpen(value)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={save} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Task reminder</DialogTitle>
              <DialogDescription>{task.text}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-2">
              <DateInput
                label="Remind me on"
                description="Reminders appear in Dzomdu on this date"
                isRequired
                isDisabled={saving}
                value={(date || undefined) as React.ComponentProps<typeof DateInput>["value"]}
                onChange={(value) => setDate(value ?? "")}
              />
              <div className="w-fit">
                <Button
                  variant="ghost"
                  size="sm"
                  label="In one week"
                  isDisabled={saving}
                  onClick={() => {
                    const next = new Date()
                    next.setDate(next.getDate() + 7)
                    setDate(localDate(next))
                  }}
                />
              </div>
            </div>
            <DialogFooter>
              <Button label="Cancel" isDisabled={saving} onClick={() => setOpen(false)} />
              <Button
                type="submit"
                variant="primary"
                label="Save reminder"
                isLoading={saving}
                isDisabled={!date}
              />
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function TaskRow({
  task,
  onChanged,
  showProject = true,
}: {
  task: OpenTask
  onChanged?: () => void
  showProject?: boolean
}) {
  const { reload } = useTasks()
  const [saving, setSaving] = React.useState(false)
  const [done, setDone] = React.useState(task.done)

  async function update(patch: Patch, undoable = true): Promise<boolean> {
    if (saving || !task.id) return false
    setSaving(true)
    if (patch.done !== undefined) setDone(patch.done)
    try {
      await api(`/api/tasks/${task.id}`, { method: "PATCH", json: patch })
      reload()
      onChanged?.()
      if (patch.done !== undefined && undoable) {
        toast.success(patch.done ? "Task completed" : "Task reopened", {
          description: task.text,
          action: {
            label: "Undo",
            onClick: () => void update({ done: !patch.done }, false),
          },
        })
      } else if (patch.reminder_date) toast.success("Reminder updated")
      return true
    } catch (error) {
      setDone(task.done)
      toast.error("Could not update task", {
        description: (error as Error).message,
      })
      return false
    } finally {
      setSaving(false)
    }
  }

  return (
    <li className="flex items-start gap-3 border-b px-5 py-4 last:border-b-0">
      <CheckboxInput
        label={`Mark ${task.text} as ${done ? "open" : "done"}`}
        isLabelHidden
        value={done}
        isDisabled={saving}
        onChange={(value) => void update({ done: value })}
      />
      <div className="min-w-0 flex-1 space-y-2">
        <p
          className={cn(
            "text-[13px] leading-relaxed",
            done && "text-muted-foreground line-through",
          )}
        >
          {task.text}
        </p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
          {showProject && task.project && (
            <Link href={projectHref(task.project)} className="hover:text-foreground hover:underline">
              {task.project}
            </Link>
          )}
          <Link
            href={`/meetings/view/?id=${encodeURIComponent(task.meeting_id)}${task.turn ? `&turn=${encodeURIComponent(task.turn)}` : ""}`}
            className="inline-flex min-w-0 items-center gap-1 hover:text-foreground hover:underline"
          >
            <span className="max-w-56 truncate">{task.meeting_title}</span>
            <ArrowUpRight className="size-3.5" />
          </Link>
          <span>{task.owner ? `Assigned to ${task.owner}` : "Unassigned"}</span>
          {task.due && (
            <span>
              Due {/^\d{4}-\d{2}-\d{2}$/.test(task.due) ? shortDate(task.due) : task.due}
            </span>
          )}
          <ReminderDialog task={task} update={update} />
          {saving && <Loader2 className="size-3.5 animate-spin" />}
        </div>
      </div>
    </li>
  )
}
