"use client"

import * as React from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import {
  ArrowLeft,
  CalendarDays,
  Clock,
  Copy,
  ExternalLink,
  FolderOpen,
  ListChecks,
  Loader2,
  Search,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"

import { ActionList } from "@/components/action-list"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/animate-ui/components/radix/dialog"
import {
  Tabs,
  TabsContent,
  TabsContents,
  TabsList,
  TabsTrigger,
} from "@/components/animate-ui/components/animate/tabs"
import { EmptyState, SpeakerAvatar } from "@/components/common"
import { useInfo } from "@/components/providers"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useApi } from "@/hooks/use-api"
import { api, type MeetingDetail, type Session } from "@/lib/api"
import { clock, colorFor, duration, longDate } from "@/lib/format"
import { cn } from "@/lib/utils"

function RewriteDialog({ meeting, onDone }: { meeting: MeetingDetail; onDone: () => void }) {
  const { info } = useInfo()
  const [open, setOpen] = React.useState(false)
  const [template, setTemplate] = React.useState(info?.default_template ?? "standard")
  const [instructions, setInstructions] = React.useState("")
  const [busy, setBusy] = React.useState(false)

  async function run(force = false) {
    setBusy(true)
    try {
      const { id } = await api<{ id: string }>(`/api/meetings/${meeting.id}/open`, {
        method: "POST",
      })
      await api(`/api/sessions/${id}/regenerate`, {
        method: "POST",
        json: { template, instructions, force },
      })
      // wait for the LLM to finish
      for (;;) {
        await new Promise((r) => setTimeout(r, 1200))
        const s = await api<Session>(`/api/sessions/${id}`)
        if (s.state === "done") break
        if (s.state === "error") throw new Error(s.error ?? "Rewriting failed")
      }
      toast.success("Notes rewritten")
      setOpen(false)
      setInstructions("")
      onDone()
    } catch (e) {
      const msg = (e as Error).message
      if (msg.startsWith("edited:") && !force) {
        if (confirm("This note was edited after it was generated (e.g. in Obsidian). Replace it and lose those edits?")) {
          setBusy(false)
          return run(true)
        }
      } else {
        toast.error(msg)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Sparkles />
          Rewrite
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Rewrite these notes</DialogTitle>
          <DialogDescription>
            Generate the summary and minutes again from the same transcript, in another format or
            with extra instructions.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>Format</Label>
            <Select value={template} onValueChange={setTemplate}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {info?.templates.map((t) => (
                  <SelectItem key={t.key} value={t.key}>
                    <span>{t.name}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="instr">Instructions</Label>
            <Textarea
              id="instr"
              rows={3}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="e.g. Shorter, in bullet points for the director"
            />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => run()} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Sparkles />}
            {busy ? "Writing…" : "Rewrite notes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Transcript({ meeting, focus }: { meeting: MeetingDetail; focus: string | null }) {
  const [q, setQ] = React.useState("")
  React.useEffect(() => {
    if (!focus) return
    // wait for the tab transition, then bring the cited turn into view
    const t = window.setTimeout(() => {
      document
        .getElementById(`turn-${focus}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" })
    }, 350)
    return () => window.clearTimeout(t)
  }, [focus])
  const query = q.trim().toLowerCase()
  const turns = query
    ? meeting.turns.filter((t) => (t.text + " " + t.label).toLowerCase().includes(query))
    : meeting.turns
  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search the transcript…"
          className="pl-9"
        />
      </div>
      <ul className="space-y-5">
        {turns.map((t) => (
          <li
            key={t.id}
            id={`turn-${t.id}`}
            className={cn(
              "-mx-2 flex gap-3 rounded-lg px-2 py-1 transition-colors duration-700",
              focus === t.id && "bg-primary/10",
            )}
          >
            <SpeakerAvatar name={t.label} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2 text-sm">
                <span className="font-semibold" style={{ color: colorFor(t.label) }}>
                  {t.label}
                </span>
                <span className="font-mono text-xs text-muted-foreground">{clock(t.start)}</span>
              </div>
              <p className="text-sm leading-relaxed">{t.text}</p>
            </div>
          </li>
        ))}
        {!turns.length && <li className="text-sm text-muted-foreground">No matches.</li>}
      </ul>
    </div>
  )
}

function MeetingView() {
  const id = useSearchParams().get("id")
  const { data: m, error, reload } = useApi<MeetingDetail>(
    id ? `/api/meetings/${encodeURIComponent(id)}` : null,
  )
  const [tab, setTab] = React.useState("notes")
  const [focus, setFocus] = React.useState<string | null>(null)

  if (!id || error) {
    return (
      <EmptyState
        icon={FolderOpen}
        title="Meeting not found"
        description={error?.message ?? "No meeting selected."}
      >
        <Button variant="outline" asChild>
          <Link href="/meetings/">All meetings</Link>
        </Button>
      </EmptyState>
    )
  }
  if (!m) return <Skeleton className="h-[70vh] rounded-xl" />

  const total = m.speakers.reduce((s, x) => s + x.talk_seconds, 0) || 1
  const openTasks = m.tasks.filter((t) => !t.done).length

  // the transcript has its own tab; citations in the notes jump there
  const notesHtml = m.note?.html.split("<h2>Transcript</h2>")[0] ?? ""

  function onNoteClick(e: React.MouseEvent) {
    const a = (e.target as HTMLElement).closest('a[href^="#t"]')
    if (!a) return
    e.preventDefault()
    setFocus(a.getAttribute("href")!.slice(1))
    setTab("transcript")
  }

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" asChild>
            <Link href="/meetings/">
              <ArrowLeft />
              Meetings
            </Link>
          </Button>
          <h1 className="text-2xl font-semibold tracking-tight">{m.title}</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="size-4" />
              {longDate(m.date)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock className="size-4" />
              {duration(m.duration)}
            </span>
            {m.project && (
              <Link href={`/meetings/?project=${encodeURIComponent(m.project)}`}>
                <Badge variant="secondary">{m.project}</Badge>
              </Link>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {m.note && (
            <>
              <Button variant="outline" asChild>
                <a href={m.note.obsidian_url}>
                  <ExternalLink />
                  Open in Obsidian
                </a>
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  navigator.clipboard
                    .writeText(m.note!.markdown)
                    .then(() => toast.success("Markdown copied"))
                    .catch(() => toast.error("Copy failed"))
                }
              >
                <Copy />
                Copy
              </Button>
            </>
          )}
          <RewriteDialog meeting={m} onDone={reload} />
        </div>
      </div>

      <div className="grid gap-6 @5xl/main:grid-cols-3">
        <div className="min-w-0 @5xl/main:col-span-2">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="notes">Notes</TabsTrigger>
              <TabsTrigger value="transcript">Transcript</TabsTrigger>
              <TabsTrigger value="actions">
                Action items
                {openTasks > 0 && (
                  <Badge variant="secondary" className="ml-1 h-5 min-w-5 px-1 tabular-nums">
                    {openTasks}
                  </Badge>
                )}
              </TabsTrigger>
            </TabsList>
            <Card className="mt-3">
              <CardContent>
                <TabsContents>
                  <TabsContent value="notes">
                    {m.note ? (
                      <div
                        onClick={onNoteClick}
                        className="note-prose"
                        dangerouslySetInnerHTML={{ __html: notesHtml }}
                      />
                    ) : (
                      <EmptyState
                        icon={FolderOpen}
                        title="No note file"
                        description="The note was moved or deleted from the vault."
                      />
                    )}
                  </TabsContent>
                  <TabsContent value="transcript">
                    <Transcript meeting={m} focus={focus} />
                  </TabsContent>
                  <TabsContent value="actions">
                    {m.tasks.length ? (
                      <ActionList
                        items={m.tasks.map((t) => ({ ...t, meeting_id: m.id }))}
                        onChange={reload}
                      />
                    ) : (
                      <EmptyState icon={ListChecks} title="No action items" className="py-8" />
                    )}
                  </TabsContent>
                </TabsContents>
              </CardContent>
            </Card>
          </Tabs>
        </div>

        <div className="flex flex-col gap-6">
          {m.summary && (
            <Card>
              <CardHeader>
                <CardTitle>Summary</CardTitle>
              </CardHeader>
              <CardContent className="text-sm leading-relaxed text-muted-foreground">
                {m.summary}
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle>Speakers</CardTitle>
              <CardDescription>Share of speaking time</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {m.speakers.map((s) => (
                <div key={s.cluster} className="space-y-1.5">
                  <div className="flex items-center gap-2 text-sm">
                    <SpeakerAvatar name={s.label} size="sm" />
                    <span className="flex-1 truncate font-medium">{s.label}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {Math.round((s.talk_seconds / total) * 100)}%
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{
                        width: `${(s.talk_seconds / total) * 100}%`,
                        backgroundColor: colorFor(s.label),
                      }}
                    />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
          {m.decisions.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Decisions</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {m.decisions.map((d) => (
                    <li key={d.decision} className="flex gap-2">
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
                      {d.decision}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}

export default function MeetingPage() {
  return (
    <div className="@container/main flex flex-col gap-6">
      <React.Suspense fallback={<Skeleton className="h-[70vh] rounded-xl" />}>
        <MeetingView />
      </React.Suspense>
    </div>
  )
}
