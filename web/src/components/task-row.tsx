"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowUpRight, CalendarClock, Folder, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { Checkbox } from "@/components/animate-ui/components/radix/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/animate-ui/components/radix/dialog"
import { localDate, reminderIsDue, useTasks } from "@/components/task-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
  const fieldId = React.useId()
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
      <Button
        variant="ghost"
        size="sm"
        className={cn(
          "shrink-0 text-xs font-normal text-muted-foreground",
          due && "bg-brand/5 text-brand",
        )}
        aria-label={`Change reminder for ${task.text}`}
        onClick={() => {
          setDate(task.reminder_date ?? "")
          setOpen(true)
        }}
      >
        <CalendarClock className="size-3.5" />
        {due ? "Reminder due" : "Remind"} ·{" "}
        {task.reminder_date ? shortDate(task.reminder_date) : "Choose date"}
      </Button>
      <Dialog open={open} onOpenChange={(value) => !saving && setOpen(value)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={save} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Task reminder</DialogTitle>
              <DialogDescription>{task.text}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-2">
              <Label htmlFor={fieldId}>Remind me on</Label>
              <Input
                id={fieldId}
                type="date"
                required
                value={date}
                disabled={saving}
                onChange={(event) => setDate(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Reminders appear in Dzomdu on this date.
              </p>
              <Button
                type="button"
                variant="link"
                className="w-fit px-0 text-xs"
                disabled={saving}
                onClick={() => {
                  const next = new Date()
                  next.setDate(next.getDate() + 7)
                  setDate(localDate(next))
                }}
              >
                In one week
              </Button>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={saving}
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={!date || saving}>
                {saving && <Loader2 className="animate-spin" />}Save reminder
              </Button>
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
    <li className="flex flex-col gap-3 border-b p-4 last:border-b-0 sm:flex-row sm:items-center sm:gap-4 sm:px-5">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Checkbox
          className="mt-0.5"
          checked={done}
          disabled={saving}
          aria-label={`Mark ${task.text} as ${done ? "open" : "done"}`}
          onCheckedChange={(value) => void update({ done: value === true })}
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
            {showProject &&
              (task.project ? (
                <Link
                  href={projectHref(task.project)}
                  className="inline-flex items-center gap-1.5 hover:text-foreground"
                >
                  <Folder className="size-3.5" />
                  {task.project}
                </Link>
              ) : (
                <span>No project</span>
              ))}
            <Link
              href={`/meetings/view/?id=${encodeURIComponent(task.meeting_id)}${task.turn ? `&turn=${encodeURIComponent(task.turn)}` : ""}`}
              className="inline-flex min-w-0 items-center gap-1 hover:text-foreground hover:underline"
            >
              <span className="max-w-56 truncate">{task.meeting_title}</span>
              <ArrowUpRight className="size-3" />
            </Link>
            <span>{task.owner ? `Assigned to ${task.owner}` : "Unassigned"}</span>
            {task.due && (
              <Badge variant="outline" className="font-normal">
                Due {/^\d{4}-\d{2}-\d{2}$/.test(task.due) ? shortDate(task.due) : task.due}
              </Badge>
            )}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1 pl-7 sm:pl-0">
        {saving && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
        <ReminderDialog task={task} update={update} />
      </div>
    </li>
  )
}
