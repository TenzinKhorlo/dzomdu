"use client"

import * as React from "react"
import Link from "next/link"
import { CalendarClock } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { Checkbox } from "@/components/animate-ui/components/radix/checkbox"
import { SpeakerAvatar } from "@/components/common"
import { SwipeToComplete } from "@/components/swipe-to-complete"
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
      {overdue ? `Overdue · ${shortDate(due)}` : iso ? shortDate(due) : due}
    </Badge>
  )
}

const key = (i: Item) => `${i.meeting_id}:${i.line}`

/**
 * Action items. Complete one with the checkbox or by swiping right; either way the Obsidian
 * note is updated, and Undo is offered instead of asking "are you sure?".
 */
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

  async function setTask(item: Item, value: boolean, undoable = true) {
    setDone((d) => ({ ...d, [key(item)]: value }))
    try {
      await api(`/api/meetings/${item.meeting_id}/tasks/${item.line}`, {
        method: "POST",
        json: { done: value },
      })
      if (undoable) {
        toast.success(value ? "Marked as done" : "Reopened", {
          description: item.text,
          action: { label: "Undo", onClick: () => void setTask(item, !value, false) },
        })
      }
      onChange?.()
    } catch (e) {
      setDone((d) => ({ ...d, [key(item)]: !value }))
      toast.error("Couldn't update the note", { description: (e as Error).message })
    }
  }

  return (
    <ul className="-mx-2 flex flex-col">
      <AnimatePresence initial={false}>
        {items.map((item) => {
          const checked = done[key(item)] ?? item.done
          return (
            <motion.li
              key={`${key(item)}:${item.text}`}
              layout="position"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <SwipeToComplete
                done={checked}
                disabled={!item.editable}
                onCommit={() => void setTask(item, !checked)}
              >
                <div className="flex items-start gap-3 px-2 py-2.5">
                  <Checkbox
                    className="mt-0.5"
                    checked={checked}
                    disabled={!item.editable}
                    onCheckedChange={(v) => void setTask(item, v === true)}
                    aria-label={`Mark "${item.text}" as ${checked ? "open" : "done"}`}
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <p
                      className={cn(
                        "text-sm leading-snug transition-colors duration-300",
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
                </div>
              </SwipeToComplete>
            </motion.li>
          )
        })}
      </AnimatePresence>
    </ul>
  )
}
