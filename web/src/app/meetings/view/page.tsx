"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import {
  ArrowLeft,
  CalendarDays,
  CircleHelp,
  Clock,
  Copy,
  ExternalLink,
  FolderOpen,
  Gavel,
  ListChecks,
  Loader2,
  MessagesSquare,
  Play,
  Search,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react"
import { motion, useReducedMotion } from "motion/react"
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
import { AvatarStack, EmptyState, SpeakerAvatar, StatTile } from "@/components/common"
import { useInfo } from "@/components/providers"
import { useTasks } from "@/components/task-provider"
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
import { api, projectHref, type MeetingDetail, type Session } from "@/lib/api"
import { PlayerBar, PlayerProvider, turnAt, usePlayer } from "@/components/meeting/player"
import { RenameMeetingDialog } from "@/components/meeting/rename-dialog"
import { useConfirm } from "@/components/confirm"
import { clock, colorFor, duration, longDate } from "@/lib/format"
import { cn } from "@/lib/utils"

function RewriteDialog({ meeting, onDone }: { meeting: MeetingDetail; onDone: () => void }) {
  const { info } = useInfo()
  const [open, setOpen] = React.useState(false)
  const [template, setTemplate] = React.useState(info?.default_template ?? "standard")
  const [instructions, setInstructions] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const confirm = useConfirm()

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
        const ok = await confirm({
          title: "Replace your edited note?",
          description:
            "This note was changed after it was written (for example in Obsidian). Rewriting replaces it, and your edits are lost.",
          confirmLabel: "Replace note",
          destructive: true,
        })
        if (ok) {
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
        <Button variant="brand">
          <Sparkles />
          Rewrite with AI
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
  const player = usePlayer()
  const reduce = useReducedMotion()
  const lastUserScroll = React.useRef(0)
  const playingIdx =
    player && (player.playing || player.time > 0) ? turnAt(meeting.turns, player.time) : -1
  const activeId = playingIdx >= 0 ? meeting.turns[playingIdx].id : null

  // the user is in control: if they scroll, stop following playback for a few seconds
  React.useEffect(() => {
    const mark = () => (lastUserScroll.current = Date.now())
    window.addEventListener("wheel", mark, { passive: true })
    window.addEventListener("touchmove", mark, { passive: true })
    return () => {
      window.removeEventListener("wheel", mark)
      window.removeEventListener("touchmove", mark)
    }
  }, [])

  React.useEffect(() => {
    if (!activeId || !player?.playing || q) return
    if (Date.now() - lastUserScroll.current < 4000) return
    document
      .getElementById(`turn-${activeId}`)
      ?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" })
  }, [activeId, player?.playing, q, reduce])

  React.useEffect(() => {
    if (!focus) return
    // wait for the tab transition, then bring the cited turn into view
    const t = window.setTimeout(() => {
      document
        .getElementById(`turn-${focus}`)
        ?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" })
    }, 350)
    return () => window.clearTimeout(t)
  }, [focus, reduce])

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
          aria-label="Search the transcript"
        />
      </div>
      <ul className="space-y-1">
        {turns.map((t) => {
          const active = t.id === activeId
          return (
            <li key={t.id} id={`turn-${t.id}`}>
              <button
                type="button"
                onClick={() => player?.seek(t.start, true)}
                disabled={!player?.available}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "group pressable relative -mx-2 flex w-[calc(100%+1rem)] gap-3 rounded-xl px-2 py-2 text-left transition-colors duration-300",
                  "hover:bg-muted/60 disabled:cursor-default disabled:hover:bg-transparent",
                  (active || focus === t.id) && "bg-brand/[0.06] hover:bg-brand/10",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="active-turn"
                    className="absolute top-2 bottom-2 left-0 w-[3px] rounded-full bg-brand"
                  />
                )}
                <SpeakerAvatar name={t.label} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 text-sm">
                    <span className="font-semibold" style={{ color: colorFor(t.label) }}>
                      {t.label}
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {clock(t.start)}
                    </span>
                    {player?.available && (
                      <Play className="size-3 self-center fill-current text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                    )}
                  </div>
                  <p className="text-sm leading-relaxed">{t.text}</p>
                </div>
              </button>
            </li>
          )
        })}
        {!turns.length && <li className="text-sm text-muted-foreground">No matches.</li>}
      </ul>
    </div>
  )
}

function MeetingView() {
  const id = useSearchParams().get("id")
  const {
    data: m,
    error,
    reload,
  } = useApi<MeetingDetail>(id ? `/api/meetings/${encodeURIComponent(id)}` : null)
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

  return (
    <PlayerProvider key={m.id} meetingId={m.id} fallbackDuration={m.duration}>
      <MeetingBody m={m} reload={reload} />
    </PlayerProvider>
  )
}

function MeetingBody({ m, reload }: { m: MeetingDetail; reload: () => void }) {
  const { reload: reloadTasks } = useTasks()
  const [tab, setTab] = React.useState("notes")
  const [focus, setFocus] = React.useState<string | null>(null)
  const player = usePlayer()
  const router = useRouter()
  const confirm = useConfirm()
  const [deleting, setDeleting] = React.useState(false)

  async function deleteMeeting() {
    const ok = await confirm({
      title: `Delete "${m.title}"?`,
      description:
        "The meeting, its note in your vault and the saved recording are deleted. This can't be undone. Voiceprints and people profiles are kept.",
      confirmLabel: "Delete meeting",
      destructive: true,
    })
    if (!ok) return
    setDeleting(true)
    try {
      await api(`/api/meetings/${encodeURIComponent(m.id)}`, { method: "DELETE" })
      toast.success("Meeting deleted")
      reloadTasks()
      router.push("/meetings/")
    } catch (e) {
      toast.error((e as Error).message)
      setDeleting(false)
    }
  }

  const total = m.speakers.reduce((s, x) => s + x.talk_seconds, 0) || 1
  const openTasks = m.tasks.filter((t) => !t.done).length

  // the transcript has its own tab; citations in the notes jump there
  const notesHtml = m.note?.html.split("<h2>Transcript</h2>")[0] ?? ""

  // a citation (or a decision) takes you to what was actually said, and plays it
  function goToTurn(id: string) {
    setFocus(id)
    setTab("transcript")
    const turn = m.turns.find((t) => t.id === id)
    if (turn && player?.available) player.seek(turn.start, true)
  }
  function onNoteClick(e: React.MouseEvent) {
    const a = (e.target as HTMLElement).closest('a[href^="#t"]')
    if (!a) return
    e.preventDefault()
    goToTurn(a.getAttribute("href")!.slice(1))
  }
  const identified = m.speakers.filter((s) => s.name).length

  return (
    <>
      <div className="flex flex-col gap-3">
        <Link
          href="/meetings/"
          className="inline-flex w-fit items-center gap-1 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          All meetings
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <div className="min-w-0 space-y-2">
            <div className="flex items-center gap-2">
              <h1 className="break-words text-xl font-semibold">{m.title}</h1>
              <RenameMeetingDialog id={m.id} title={m.title} onRenamed={reload} />
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays className="size-3.5" />
                {longDate(m.date)}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="size-3.5" />
                {duration(m.duration)}
              </span>
              {m.project && (
                <Link href={projectHref(m.project)}>
                  <Badge variant="outline" className="gap-1.5 font-normal hover:bg-accent">
                    <span
                      className="size-1.5 rounded-full"
                      style={{ backgroundColor: colorFor(m.project) }}
                      aria-hidden
                    />
                    {m.project}
                  </Badge>
                </Link>
              )}
              {m.people.length > 0 && <AvatarStack names={m.people} max={5} />}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="brand" asChild>
              <Link href={`/chat/?meeting=${encodeURIComponent(m.id)}`}>
                <MessagesSquare />
                Ask about this meeting
              </Link>
            </Button>
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
                  Copy Markdown
                </Button>
              </>
            )}
            <RewriteDialog meeting={m} onDone={reload} />
            <Button variant="outline" onClick={deleteMeeting} disabled={deleting}>
              <Trash2 />
              Delete
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 @4xl/main:grid-cols-4">
        <StatTile
          label="Length"
          icon={Clock}
          value={duration(m.duration)}
          hint={`${m.turns.length} turns`}
        />
        <StatTile
          label="Speakers"
          icon={Users}
          value={m.speakers.length}
          hint={identified === m.speakers.length ? "all identified" : `${identified} identified`}
        />
        <StatTile
          label="Decisions"
          icon={Gavel}
          value={m.decisions.length}
          hint={
            m.topics.length
              ? `${m.topics.length} topic${m.topics.length === 1 ? "" : "s"}`
              : undefined
          }
        />
        <StatTile
          label="Action items"
          icon={ListChecks}
          value={openTasks}
          hint={m.tasks.length ? `open of ${m.tasks.length}` : "none"}
        />
      </div>

      <div className="grid gap-4 @5xl/main:grid-cols-3">
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
            <Card className="mt-2">
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
          <PlayerBar turns={m.turns} className="mt-4" />
        </div>

        <div className="flex flex-col gap-4">
          {m.summary && (
            <Card className="gap-3">
              <CardHeader>
                <CardTitle className="flex items-center gap-1.5">
                  <Sparkles className="size-4 text-brand" aria-hidden />
                  Summary
                </CardTitle>
              </CardHeader>
              <CardContent className="text-[13px] leading-relaxed text-muted-foreground">
                {m.summary}
              </CardContent>
            </Card>
          )}
          <Card className="gap-4">
            <CardHeader>
              <CardTitle>Speakers</CardTitle>
              <CardDescription>Share of speaking time</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-3">
                {m.speakers.map((s) => {
                  const share = s.talk_seconds / total
                  return (
                    <li
                      key={s.cluster}
                      className="grid grid-cols-[minmax(0,1fr)_minmax(3rem,5.5rem)_2.25rem] items-center gap-3 text-[13px]"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <SpeakerAvatar name={s.label} size="sm" className="ring-0" />
                        <span className={cn("truncate", !s.name && "text-muted-foreground")}>
                          {s.label}
                        </span>
                      </span>
                      <span className="h-2 overflow-hidden rounded-full bg-track" aria-hidden>
                        <span
                          className="block h-full rounded-r-[4px] transition-[width] duration-700"
                          style={{ width: `${share * 100}%`, backgroundColor: colorFor(s.label) }}
                        />
                      </span>
                      <span className="text-right text-xs text-muted-foreground tabular-nums">
                        {Math.round(share * 100)}%
                      </span>
                    </li>
                  )
                })}
              </ul>
            </CardContent>
          </Card>
          {m.decisions.length > 0 && (
            <Card className="gap-3">
              <CardHeader>
                <CardTitle>Decisions</CardTitle>
                <CardDescription>Click one to hear where it was decided</CardDescription>
              </CardHeader>
              <CardContent className="px-3">
                <ol className="space-y-0.5">
                  {m.decisions.map((d, i) => {
                    const source = d.source_turns[0]
                    return (
                      <li key={d.decision}>
                        <button
                          type="button"
                          disabled={!source}
                          onClick={() => source && goToTurn(source)}
                          className="pressable flex w-full gap-2.5 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-muted/70 disabled:hover:bg-transparent"
                        >
                          <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-md border bg-muted/60 text-[11px] font-medium text-muted-foreground tabular-nums">
                            {i + 1}
                          </span>
                          <span className="leading-snug">{d.decision}</span>
                        </button>
                      </li>
                    )
                  })}
                </ol>
              </CardContent>
            </Card>
          )}
          {m.open_questions.length > 0 && (
            <Card className="gap-3">
              <CardHeader>
                <CardTitle>Open questions</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-[13px]">
                  {m.open_questions.map((q) => (
                    <li key={q} className="flex gap-2">
                      <CircleHelp className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                      <span className="leading-snug">{q}</span>
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
    <div className="@container/main flex flex-col gap-5">
      <React.Suspense fallback={<Skeleton className="h-[70vh] rounded-xl" />}>
        <MeetingView />
      </React.Suspense>
    </div>
  )
}
