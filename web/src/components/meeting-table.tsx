"use client"

import { useRouter } from "next/navigation"
import { CircleDot, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { AvatarStack } from "@/components/common"
import { useConfirm } from "@/components/confirm"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { api, type MeetingRow } from "@/lib/api"
import { colorFor, duration, relative } from "@/lib/format"

export function MeetingTable({
  meetings,
  compact = false,
  onDeleted,
}: {
  meetings: MeetingRow[]
  compact?: boolean
  /** When given, each row gets a delete button; called after a meeting is deleted. */
  onDeleted?: () => void
}) {
  const router = useRouter()
  const confirm = useConfirm()

  async function remove(m: MeetingRow) {
    const ok = await confirm({
      title: `Delete "${m.title}"?`,
      description:
        "The meeting, its note in your vault and the saved recording are deleted. This can't be undone. Voiceprints and people profiles are kept.",
      confirmLabel: "Delete meeting",
      destructive: true,
    })
    if (!ok) return
    try {
      await api(`/api/meetings/${encodeURIComponent(m.id)}`, { method: "DELETE" })
      toast.success("Meeting deleted")
      onDeleted?.()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }
  const open = (id: string) => router.push(`/meetings/view/?id=${encodeURIComponent(id)}`)

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">Meeting</TableHead>
          {!compact && <TableHead>Project</TableHead>}
          <TableHead>People</TableHead>
          <TableHead className="text-right">Length</TableHead>
          <TableHead className={onDeleted ? "text-right" : "pr-4 text-right"}>Actions</TableHead>
          {onDeleted && <TableHead className="w-12 pr-4" />}
        </TableRow>
      </TableHeader>
      <TableBody>
        {meetings.map((m) => (
          <TableRow
            key={m.id}
            tabIndex={0}
            className="cursor-pointer"
            onClick={() => open(m.id)}
            onKeyDown={(e) => e.key === "Enter" && open(m.id)}
          >
            <TableCell className="max-w-[22rem] pl-4">
              <div className="truncate font-medium">{m.title}</div>
              <div className="truncate text-xs text-muted-foreground">
                {relative(m.date)}
                {m.summary ? ` · ${m.summary}` : ""}
              </div>
            </TableCell>
            {!compact && (
              <TableCell>
                {m.project ? (
                  <Badge variant="outline" className="gap-1.5 font-normal">
                    <span
                      className="size-1.5 rounded-full"
                      style={{ backgroundColor: colorFor(m.project) }}
                      aria-hidden
                    />
                    {m.project}
                  </Badge>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
            )}
            <TableCell>
              <div className="flex items-center gap-2">
                <AvatarStack names={m.people} />
                {m.unidentified > 0 && (
                  <span className="text-xs text-muted-foreground">+{m.unidentified} unknown</span>
                )}
              </div>
            </TableCell>
            <TableCell className="text-right tabular-nums text-muted-foreground">
              {duration(m.duration)}
            </TableCell>
            <TableCell className={onDeleted ? "text-right" : "pr-4 text-right"}>
              {m.open_actions > 0 ? (
                <Badge className="gap-1 bg-brand/10 text-brand tabular-nums dark:bg-brand/15">
                  <CircleDot />
                  {m.open_actions} open
                </Badge>
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              )}
            </TableCell>
            {onDeleted && (
              <TableCell className="pr-4 text-right">
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete ${m.title}`}
                  className="text-muted-foreground hover:text-destructive"
                  onClick={(e) => {
                    e.stopPropagation()
                    remove(m)
                  }}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <Trash2 />
                </Button>
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
