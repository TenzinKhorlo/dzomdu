"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { Heading } from "@astryxdesign/core/Heading"
import { Icon } from "@astryxdesign/core/Icon"
import { MoreMenu } from "@astryxdesign/core/MoreMenu"
import { Text } from "@astryxdesign/core/Text"
import { TextArea } from "@astryxdesign/core/TextArea"
import { TextInput } from "@astryxdesign/core/TextInput"
import { ChevronDown, ChevronUp, ChevronsUpDown, Pencil, Search, Trash2, Users } from "lucide-react"
import { toast } from "@/lib/toast"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/dialog"
import { EmptyState, SpeakerAvatar } from "@/components/common"
import { useConfirm } from "@/components/confirm"
import { Kpi } from "@/components/dashboard/kpi-cards"
import { useInfo } from "@/components/providers"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useApi } from "@/hooks/use-api"
import { api, type Voice } from "@/lib/api"
import { duration } from "@/lib/format"
import { cn } from "@/lib/utils"

function ProfileForm({
  voice,
  onClose,
  onSaved,
}: {
  voice: Voice
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = React.useState({
    name: voice.name,
    role: voice.role,
    organisation: voice.organisation,
    bio: voice.bio,
  })
  const [busy, setBusy] = React.useState(false)

  async function save() {
    setBusy(true)
    try {
      if (form.name.trim() !== voice.name) {
        await api("/api/speakers/rename", {
          method: "POST",
          json: { old: voice.name, new: form.name.trim() },
        })
      }
      await api("/api/people", {
        method: "POST",
        json: {
          name: form.name.trim(),
          role: form.role,
          organisation: form.organisation,
          bio: form.bio,
        },
      })
      toast.success("Profile saved", { description: "Also updated in People/ in your vault." })
      onSaved()
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <DialogHeader className="flex-row items-center gap-3 space-y-0 text-left">
        <SpeakerAvatar name={voice.name} size="lg" className="ring-0" />
        <div className="space-y-1">
          <DialogTitle>Edit profile</DialogTitle>
          <DialogDescription>
            Names and roles supply participant details in minutes. Summaries use the transcript;
            profile biographies stay separate.
          </DialogDescription>
        </div>
      </DialogHeader>
      <div className="grid gap-4">
        <TextInput label="Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput
            label="Role"
            placeholder="e.g. Project manager"
            value={form.role}
            onChange={(v) => setForm({ ...form, role: v })}
          />
          <TextInput
            label="Organisation"
            placeholder="e.g. Energy Division"
            value={form.organisation}
            onChange={(v) => setForm({ ...form, organisation: v })}
          />
        </div>
        <TextArea
          label="Bio"
          rows={4}
          placeholder="What they work on and are responsible for"
          value={form.bio}
          onChange={(v) => setForm({ ...form, bio: v })}
        />
      </div>
      <DialogFooter>
        <Button label="Cancel" onClick={onClose} />
        <Button
          variant="primary"
          label="Save"
          onClick={save}
          isLoading={busy}
          isDisabled={!form.name.trim()}
        />
      </DialogFooter>
    </>
  )
}

function ProfileDialog({
  voice,
  onClose,
  onSaved,
}: {
  voice: Voice | null
  onClose: () => void
  onSaved: () => void
}) {
  return (
    <Dialog open={voice !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {voice && (
          <ProfileForm key={voice.name} voice={voice} onClose={onClose} onSaved={onSaved} />
        )}
      </DialogContent>
    </Dialog>
  )
}

type SortKey = "name" | "meetings" | "minutes" | "samples"

export default function PeoplePage() {
  const { data, reload } = useApi<Voice[]>("/api/speakers")
  const { reload: reloadInfo } = useInfo()
  const [editing, setEditing] = React.useState<Voice | null>(null)
  const [query, setQuery] = React.useState("")
  const [sort, setSort] = React.useState<{ key: SortKey; desc: boolean }>({
    key: "minutes",
    desc: true,
  })
  const confirm = useConfirm()

  async function forget(v: Voice) {
    const ok = await confirm({
      title: `Forget ${v.name}'s voice?`,
      description:
        "Their voiceprints and clips are deleted, so they won't be recognised next time. Meeting notes and their profile are kept.",
      confirmLabel: "Forget voice",
      destructive: true,
    })
    if (!ok) return
    try {
      await api(`/api/speakers/${encodeURIComponent(v.name)}`, { method: "DELETE" })
      toast.success(`Forgot ${v.name}'s voice`)
      reload()
      reloadInfo()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const q = query.trim().toLowerCase()
  const rows = (data ?? [])
    .filter(
      (v) => !q || [v.name, v.role, v.organisation, v.bio].some((x) => x?.toLowerCase().includes(q)),
    )
    .sort((a, b) => {
      const d =
        sort.key === "name"
          ? a.name.localeCompare(b.name)
          : (a[sort.key] as number) - (b[sort.key] as number)
      return sort.desc ? -d : d
    })
  const maxMinutes = Math.max(1, ...(data ?? []).map((v) => v.minutes))
  const totalMinutes = (data ?? []).reduce((s, v) => s + v.minutes, 0)
  const complete = (data ?? []).filter((v) => v.role && v.bio).length

  function header(key: SortKey, label: string, className?: string) {
    const active = sort.key === key
    const SortIcon = !active ? ChevronsUpDown : sort.desc ? ChevronDown : ChevronUp
    return (
      <TableHead
        className={className}
        aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
      >
        <button
          type="button"
          onClick={() => setSort({ key, desc: active ? !sort.desc : key !== "name" })}
          className={cn(
            "group inline-flex items-center gap-1 rounded hover:text-foreground",
            active && "text-foreground",
          )}
        >
          {label}
          <SortIcon
            className={cn(
              "size-3.5 transition-opacity duration-150",
              !active && "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100",
            )}
          />
        </button>
      </TableHead>
    )
  }

  return (
    <div className="@container/main flex flex-col gap-5">
      <div className="space-y-1.5">
        <Heading level={1}>People</Heading>
        <Text type="supporting" display="block" className="max-w-xl text-pretty">
          Everyone whose voice Dzomdu recognises. Voiceprints are stored only on this computer,
          outside your notes.
        </Text>
      </div>
      {!data ? (
        <>
          <div className="grid grid-cols-2 gap-3 @4xl/main:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[104px] rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-80 rounded-xl" />
        </>
      ) : data.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No voices yet"
          description="After a meeting, name each speaker on the review screen. Their voice is remembered and recognised next time."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 @4xl/main:grid-cols-4">
            <Kpi index={0} label="People" value={data.length} footer="Saved in your local library" />
            <Kpi
              index={1}
              label="Speaking time"
              text={duration(totalMinutes * 60)}
              footer="Across all meetings"
            />
            <Kpi
              index={2}
              label="Voice samples"
              value={data.reduce((s, v) => s + v.samples, 0)}
              footer="More samples, better matches"
            />
            <Kpi
              index={3}
              label="Profiles complete"
              text={`${complete}/${data.length}`}
              footer="Role and bio filled in"
            />
          </div>

          <div className="overflow-hidden rounded-[var(--radius-container)] border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <div>
                <Heading level={3}>All people</Heading>
                <Text type="supporting">Select a person to edit their profile</Text>
              </div>
              <div className="w-full @xl/main:max-w-64">
                <TextInput
                  label="Search people"
                  isLabelHidden
                  size="sm"
                  type="search"
                  startIcon={Search}
                  placeholder="Search"
                  hasClear
                  value={query}
                  onChange={setQuery}
                />
              </div>
            </div>
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  {header("name", "Name", "pl-5")}
                  <TableHead className="hidden @4xl/main:table-cell">About</TableHead>
                  {header("meetings", "Meetings", "hidden text-right @2xl/main:table-cell")}
                  {header("minutes", "Speaking time")}
                  {header("samples", "Samples", "hidden text-right @3xl/main:table-cell")}
                  <TableHead className="hidden @3xl/main:table-cell">Consent</TableHead>
                  <TableHead className="w-12 pr-3">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((v) => {
                  const subtitle = [v.role, v.organisation].filter(Boolean).join(" · ")
                  return (
                    <TableRow
                      key={v.name}
                      tabIndex={0}
                      className="cursor-pointer"
                      onClick={() => setEditing(v)}
                      onKeyDown={(e) => e.key === "Enter" && setEditing(v)}
                    >
                      <TableCell className="max-w-[11rem] pl-5 @xl/main:max-w-none">
                        <div className="flex h-9 items-center gap-3">
                          <SpeakerAvatar name={v.name} className="ring-0" />
                          <div className="min-w-0">
                            <div className="truncate font-medium">{v.name}</div>
                            {subtitle && (
                              <div className="truncate text-xs text-muted-foreground">{subtitle}</div>
                            )}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="hidden max-w-[18rem] @4xl/main:table-cell">
                        {v.bio ? (
                          <span className="block truncate" title={v.bio}>
                            {v.bio}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="hidden text-right tabular-nums @2xl/main:table-cell">
                        {v.meetings}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2.5">
                          <span
                            className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-track @xl/main:block"
                            aria-hidden
                          >
                            <span
                              className={cn(
                                "block h-full rounded-full",
                                v.minutes === maxMinutes ? "bg-brand" : "bg-foreground/30",
                              )}
                              style={{ width: `${(v.minutes / maxMinutes) * 100}%` }}
                            />
                          </span>
                          <span className="font-mono text-xs text-muted-foreground tabular-nums">
                            {duration(v.minutes * 60)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="hidden text-right tabular-nums @3xl/main:table-cell">
                        {v.samples}
                      </TableCell>
                      <TableCell className="hidden @3xl/main:table-cell">
                        {v.consent ? (
                          <span className="inline-flex items-center gap-1.5 text-xs">
                            <span className="size-1.5 rounded-full bg-success" aria-hidden />
                            Given
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">Not recorded</span>
                        )}
                      </TableCell>
                      <TableCell
                        className="pr-3"
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => e.stopPropagation()}
                      >
                        <MoreMenu
                          alignment="end"
                          size="sm"
                          label={`Actions for ${v.name}`}
                          items={[
                            {
                              label: "Edit profile",
                              icon: <Icon icon={Pencil} />,
                              onClick: () => setEditing(v),
                            },
                            { type: "divider" },
                            {
                              label: "Forget voice",
                              icon: <Icon icon={Trash2} />,
                              variant: "destructive",
                              onClick: () => void forget(v),
                            },
                          ]}
                        />
                      </TableCell>
                    </TableRow>
                  )
                })}
                {rows.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                      Nobody matches “{query}”
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </>
      )}
      <ProfileDialog
        voice={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          reload()
          reloadInfo()
        }}
      />
    </div>
  )
}
