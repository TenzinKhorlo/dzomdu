"use client"

import * as React from "react"
import Link from "next/link"
import { CalendarClock } from "lucide-react"
import { toast } from "sonner"

import { Checkbox } from "@/components/animate-ui/components/radix/checkbox"
import { SpeakerAvatar } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { api, type Task } from "@/lib/api"
import { shortDate } from "@/lib/format"
import { cn } from "@/lib/utils"

type Item = Task & { meeting_id: string; meeting_title?: string }

function dueBadge(due: string | null) {
  if (!due) return null
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(due)
  const overdue = iso && new Date(due + "T23:59") < new Date()
  return (
    <Badge
      variant="outline"
      className={cn("gap-1 font-normal", overdue && "border-destructive/40 text-destructive")}
    >
      <CalendarClock />
      {iso ? shortDate(due) : due}
    </Badge>
  )
}

/** Action items with animated checkboxes; ticking one updates the Markdown note. */
export function ActionList({
  items,
  showMeeting = false,
  onChange,
}: {
  items: Item[]
  showMeeting?: boolean
  onChange?: () => void
}) {
  const [done, setDone] = React.useState<Record<string, boolean>>({})

  async function toggle(item: Item, value: boolean) {
    const key = `${item.meeting_id}:${item.line}`
    setDone((d) => ({ ...d, [key]: value }))
    try {
      await api(`/api/meetings/${item.meeting_id}/tasks/${item.line}`, {
        method: "POST",
        json: { done: value },
      })
      toast.success(value ? "Marked as done" : "Marked as open", {
        description: "The meeting note was updated too.",
      })
      onChange?.()
    } catch (e) {
      setDone((d) => ({ ...d, [key]: !value }))
      toast.error((e as Error).message)
    }
  }

  return (
    <ul className="divide-y">
      {items.map((item) => {
        const key = `${item.meeting_id}:${item.line}:${item.text}`
        const checked = done[`${item.meeting_id}:${item.line}`] ?? item.done
        return (
          <li key={key} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
            <Checkbox
              className="mt-0.5"
              checked={checked}
              disabled={!item.editable}
              onCheckedChange={(v) => toggle(item, v === true)}
              aria-label={`Mark "${item.text}" as done`}
            />
            <div className="min-w-0 flex-1 space-y-1.5">
              <p
                className={cn(
                  "text-sm leading-snug transition-colors",
                  checked && "text-muted-foreground line-through",
                )}
              >
                {item.text}
              </p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                {item.owner && (
                  <span className="inline-flex items-center gap-1.5">
                    <SpeakerAvatar name={item.owner} size="sm" className="ring-0" />
                    {item.owner}
                  </span>
                )}
                {dueBadge(item.due)}
                {showMeeting && item.meeting_title && (
                  <Link
                    href={`/meetings/view/?id=${item.meeting_id}`}
                    className="truncate hover:text-foreground hover:underline"
                  >
                    {item.meeting_title}
                  </Link>
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
