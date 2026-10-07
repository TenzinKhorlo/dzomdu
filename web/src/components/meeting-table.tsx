"use client"

import { useRouter } from "next/navigation"
import { CircleDot } from "lucide-react"

import { AvatarStack } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { MeetingRow } from "@/lib/api"
import { duration, relative } from "@/lib/format"

export function MeetingTable({
  meetings,
  compact = false,
}: {
  meetings: MeetingRow[]
  compact?: boolean
}) {
  const router = useRouter()
  const open = (id: string) => router.push(`/meetings/view/?id=${encodeURIComponent(id)}`)

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-4">Meeting</TableHead>
          {!compact && <TableHead>Project</TableHead>}
          <TableHead>People</TableHead>
          <TableHead className="text-right">Length</TableHead>
          <TableHead className="pr-4 text-right">Actions</TableHead>
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
                  <Badge variant="secondary" className="font-normal">
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
            <TableCell className="pr-4 text-right">
              {m.open_actions > 0 ? (
                <Badge variant="outline" className="gap-1 tabular-nums">
                  <CircleDot className="text-warning" />
                  {m.open_actions} open
                </Badge>
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
