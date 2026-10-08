"use client"

import * as React from "react"
import {
  AudioLines,
  Briefcase,
  Building2,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  Clock,
  FileText,
  Loader2,
  MoreHorizontal,
  Pencil,
  Search,
  ShieldCheck,
  Trash2,
  User,
  UserCheck,
  Users,
} from "lucide-react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/animate-ui/components/radix/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/animate-ui/components/radix/dropdown-menu"
import { EmptyState, PageHeader, SpeakerAvatar, StatTile } from "@/components/common"
import { useConfirm } from "@/components/confirm"
import { useInfo } from "@/components/providers"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { useApi } from "@/hooks/use-api"
import { api, type Voice } from "@/lib/api"
import { colorFor, duration } from "@/lib/format"
import { cn } from "@/lib/utils"

function FieldRow({
  icon: Icon,
  label,
  htmlFor,
  top,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  htmlFor: string
  top?: boolean
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-[8.5rem_1fr] gap-3 px-3 py-2.5",
        top ? "items-start" : "items-center",
      )}
    >
      <Label
        htmlFor={htmlFor}
        className={cn("gap-2 text-[13px] font-normal text-muted-foreground", top && "pt-2")}
      >
        <Icon className="size-4" />
        {label}
      </Label>
      {children}
    </div>
  )
}

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
            Role and bio are given to the LLM as context, so summaries know who does what.
          </DialogDescription>
        </div>
      </DialogHeader>
      <div className="divide-y rounded-lg border">
        <FieldRow icon={User} label="Name" htmlFor="p-name">
          <Input
            id="p-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </FieldRow>
        <FieldRow icon={Briefcase} label="Role" htmlFor="p-role">
          <Input
            id="p-role"
            placeholder="e.g. Project manager"
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          />
        </FieldRow>
        <FieldRow icon={Building2} label="Organisation" htmlFor="p-org">
          <Input
            id="p-org"
            placeholder="e.g. Energy Division"
            value={form.organisation}
            onChange={(e) => setForm({ ...form, organisation: e.target.value })}
          />
        </FieldRow>
        <FieldRow icon={FileText} label="Bio" htmlFor="p-bio" top>
          <Textarea
            id="p-bio"
            rows={4}
            placeholder="What they work on and are responsible for"
            value={form.bio}
            onChange={(e) => setForm({ ...form, bio: e.target.value })}
          />
        </FieldRow>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={save} disabled={busy || !form.name.trim()}>
          {busy && <Loader2 className="animate-spin" />}
          Save
        </Button>
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
    const Icon = !active ? ChevronsUpDown : sort.desc ? ChevronDown : ChevronUp
    return (
      <TableHead
        className={className}
        aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
      >
        <button
          type="button"
          onClick={() => setSort({ key, desc: active ? !sort.desc : key !== "name" })}
          className={cn(
            "inline-flex items-center gap-1 rounded hover:text-foreground",
            active && "text-foreground",
          )}
        >
          {label}
          <Icon className="size-3.5" />
        </button>
      </TableHead>
    )
  }

  return (
    <div className="@container/main flex flex-col gap-5">
      <PageHeader
        title="People"
        description="Everyone whose voice Dzomdu recognises. Voiceprints are stored only on this computer, outside your notes."
      />
      {!data ? (
        <>
          <div className="grid grid-cols-2 gap-3 @4xl/main:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[76px] rounded-xl" />
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
            <StatTile label="People" icon={Users} value={data.length} hint="voices recognised" />
            <StatTile
              label="Speaking time"
              icon={Clock}
              value={duration(totalMinutes * 60)}
              hint="across all meetings"
            />
            <StatTile
              label="Voice samples"
              icon={AudioLines}
              value={data.reduce((s, v) => s + v.samples, 0)}
              hint="more samples, better matches"
            />
            <StatTile
              label="Profiles complete"
              icon={UserCheck}
              value={`${complete}/${data.length}`}
              hint="role and bio filled in"
            />
          </div>

          <Card className="gap-0 overflow-hidden py-0">
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <div>
                <h2 className="text-[15px] font-semibold tracking-[-0.01em]">All people</h2>
                <p className="text-[13px] text-muted-foreground">
                  Click a person to edit their profile
                </p>
              </div>
              <div className="relative w-full @xl/main:max-w-64">
                <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search people…"
                  aria-label="Search people"
                  className="h-8 pl-8"
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
                {rows.map((v) => (
                  <TableRow
                    key={v.name}
                    tabIndex={0}
                    className="cursor-pointer"
                    onClick={() => setEditing(v)}
                    onKeyDown={(e) => e.key === "Enter" && setEditing(v)}
                  >
                    <TableCell className="max-w-[11rem] pl-5 @xl/main:max-w-none">
                      <div className="flex items-center gap-3">
                        <SpeakerAvatar name={v.name} className="ring-0" />
                        <div className="min-w-0">
                          <div className="truncate font-medium">{v.name}</div>
                          <div className="truncate text-xs text-muted-foreground">
                            {[v.role, v.organisation].filter(Boolean).join(" · ") || "No role yet"}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="hidden max-w-[18rem] @4xl/main:table-cell">
                      <span
                        className={cn("block truncate", !v.bio && "text-muted-foreground")}
                        title={v.bio || undefined}
                      >
                        {v.bio || "Add a bio"}
                      </span>
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
                            className="block h-full rounded-r-[4px]"
                            style={{
                              width: `${(v.minutes / maxMinutes) * 100}%`,
                              backgroundColor: colorFor(v.name),
                            }}
                          />
                        </span>
                        <span className="text-muted-foreground tabular-nums">
                          {duration(v.minutes * 60)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden text-right tabular-nums @3xl/main:table-cell">
                      {v.samples}
                    </TableCell>
                    <TableCell className="hidden @3xl/main:table-cell">
                      {v.consent ? (
                        <Badge className="gap-1 bg-success/10 text-success">
                          <ShieldCheck />
                          Given
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">Not recorded</span>
                      )}
                    </TableCell>
                    <TableCell className="pr-3" onClick={(e) => e.stopPropagation()}>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Actions for ${v.name}`}
                          >
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => setEditing(v)}>
                            <Pencil />
                            Edit profile
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem variant="destructive" onClick={() => void forget(v)}>
                            <Trash2 />
                            Forget voice
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                      Nobody matches “{query}”.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Card>
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
