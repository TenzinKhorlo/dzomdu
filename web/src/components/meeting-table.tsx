"use client"

import * as React from "react"
import { ViewTransition } from "react"
import Link from "next/link"
import { MoreMenu } from "@astryxdesign/core/MoreMenu"
import { Icon } from "@astryxdesign/core/Icon"
import { Table, pixel, proportional } from "@astryxdesign/core/Table"
import { Token } from "@astryxdesign/core/Token"
import { Trash2 } from "lucide-react"
import { toast } from "@/lib/toast"

import { AvatarStack } from "@/components/common"
import { useConfirm } from "@/components/confirm"
import { api, type MeetingRow } from "@/lib/api"
import { rememberMeeting } from "@/lib/meeting-preview"
import { duration, relative } from "@/lib/format"

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
  const confirm = useConfirm()
  // a deleted meeting leaves the list at once; it comes back only if the server refuses
  const [removed, setRemoved] = React.useState<ReadonlySet<string>>(new Set())
  const visible = meetings.filter((m) => !removed.has(m.id))

  async function remove(m: MeetingRow) {
    const ok = await confirm({
      title: `Delete "${m.title}"?`,
      description:
        "The meeting, its note in your vault and the saved recording are deleted. This can't be undone. Voiceprints and people profiles are kept.",
      confirmLabel: "Delete meeting",
      destructive: true,
    })
    if (!ok) return
    setRemoved((ids) => new Set(ids).add(m.id))
    try {
      await api(`/api/meetings/${encodeURIComponent(m.id)}`, { method: "DELETE" })
      toast.success("Meeting deleted")
      onDeleted?.()
    } catch (e) {
      setRemoved((ids) => {
        const next = new Set(ids)
        next.delete(m.id)
        return next
      })
      toast.error((e as Error).message)
    }
  }
  // a column of dashes says nothing, so the Project column only appears once a meeting has one
  const showProject = !compact && visible.some((m) => m.project)

  type Row = MeetingRow & Record<string, unknown>
  const dash = <span className="text-muted-foreground">—</span>
  const columns = [
    {
      key: "title",
      header: "Meeting",
      // the text-heavy column takes the spare room; the rest are sized to their content
      width: proportional(3, { minWidth: compact ? 170 : 260 }),
      renderCell: (m: Row) => (
        <div className="min-w-0">
          <ViewTransition name={`meeting-title-${m.id}`} share="morph" default="none">
            <Link
              href={`/meetings/view/?id=${encodeURIComponent(m.id)}`}
              onClick={() => rememberMeeting(m.id, m.title)}
              className="block truncate font-medium hover:underline"
            >
              {m.title}
            </Link>
          </ViewTransition>
          <div className="truncate text-xs text-muted-foreground">
            {relative(m.date)}
            {m.summary ? ` · ${m.summary}` : ""}
          </div>
        </div>
      ),
    },
    ...(showProject
      ? [{ key: "project", header: "Project", width: pixel(120), renderCell: (m: Row) => (m.project ? <Token label={m.project} size="sm" /> : dash) }]
      : []),
    {
      key: "people",
      header: "People",
      width: proportional(1, { minWidth: compact ? 100 : 140 }),
      renderCell: (m: Row) =>
        m.people.length || m.unidentified ? <AvatarStack names={m.people} unknown={m.unidentified} /> : dash,
    },
    {
      key: "duration",
      header: "Length",
      width: pixel(compact ? 76 : 90),
      align: "end" as const,
      renderCell: (m: Row) => (
        <span className="font-mono text-xs tabular-nums text-muted-foreground">{duration(m.duration)}</span>
      ),
    },
    {
      key: "open_actions",
      header: "Open items",
      width: pixel(compact ? 92 : 100),
      align: "end" as const,
      renderCell: (m: Row) =>
        m.open_actions > 0 ? (
          <span className="font-mono text-xs font-medium text-brand tabular-nums">{m.open_actions}</span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    ...(onDeleted
      ? [
          {
            key: "actions",
            width: pixel(56),
            header: <span className="sr-only">Actions</span>,
            align: "end" as const,
            renderCell: (m: Row) => (
              <MoreMenu
                alignment="end"
                size="sm"
                label={`Actions for ${m.title}`}
                items={[
                  {
                    label: "Delete meeting",
                    icon: <Icon icon={Trash2} />,
                    variant: "destructive",
                    onClick: () => remove(m),
                  },
                ]}
              />
            ),
          },
        ]
      : []),
  ]

  return <Table data={visible as Row[]} columns={columns} idKey="id" hasHover density={compact ? "compact" : "balanced"} />
}
