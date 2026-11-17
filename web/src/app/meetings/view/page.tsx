"use client"

import * as React from "react"
import { ViewTransition } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import {
  CalendarDays,
  Clock,
  Copy,
  ExternalLink,
  FolderOpen,
  ListChecks,
  Loader2,
  MessagesSquare,
  Search,
  PenLine,
  Trash2,
  Users,
} from "lucide-react"
import { Badge as AstryxBadge } from "@astryxdesign/core/Badge"
import { Banner } from "@astryxdesign/core/Banner"
import { Button as AstryxButton } from "@astryxdesign/core/Button"
import { Card as AstryxCard } from "@astryxdesign/core/Card"
import { Heading } from "@astryxdesign/core/Heading"
import { Selector } from "@astryxdesign/core/Selector"
import { TextArea } from "@astryxdesign/core/TextArea"
import { TextInput } from "@astryxdesign/core/TextInput"
import { Icon } from "@astryxdesign/core/Icon"
import { MoreMenu } from "@astryxdesign/core/MoreMenu"
import { Tab, TabList } from "@astryxdesign/core/TabList"
import { Text } from "@astryxdesign/core/Text"
import { Token } from "@astryxdesign/core/Token"
import { useReducedMotion } from "motion/react"
import { toast } from "@/lib/toast"

import { ActionList } from "@/components/action-list"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/dialog"
import { AvatarStack, EmptyState } from "@/components/common"
import { useInfo } from "@/components/providers"
import { TranscriptEditor } from "@/components/transcript-editor"
import { useTasks } from "@/components/task-provider"
import { Button } from "@/components/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import { api, projectHref, type MeetingDetail, type Session } from "@/lib/api"
import { recallMeeting } from "@/lib/meeting-preview"
import { PlayerBar, PlayerProvider, turnAt, usePlayer } from "@/components/meeting/player"
import { RenameMeetingDialog } from "@/components/meeting/rename-dialog"
import { useConfirm } from "@/components/confirm"
import { duration, longDate } from "@/lib/format"
import { type TranscriptEdit } from "@/lib/transcript-edits"

function RewriteDialog({ meeting, open, setOpen, onDone }: {
  meeting: MeetingDetail; open: boolean; setOpen: (open: boolean) => void; onDone: () => void
}) {
  const { info } = useInfo()
  const [template, setTemplate] = React.useState(info?.default_template ?? "standard")
  const [instructions, setInstructions] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [rewriteError, setRewriteError] = React.useState<string | null>(null)
  const [progress, setProgress] = React.useState("")
  const confirm = useConfirm()
  const invalidNotes = rewriteError?.includes("notes schema") ?? false

  async function run(force = false) {
    setBusy(true)
    setRewriteError(null)
    setProgress("Waiting for the AI service…")
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
        setProgress(s.messages.at(-1) ?? "Writing notes…")
        if (s.state === "error" || s.error) throw new Error(s.error ?? "Rewriting failed")
        if (s.state === "done") {
          if (s.warning) throw new Error(s.warning)
          break
        }
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
        setRewriteError(msg)
        toast.error(msg)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Rewrite these notes</DialogTitle>
          <DialogDescription>
            Generate the summary and minutes again from the same transcript, in another format or
            with extra instructions.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          {rewriteError && (
            <div
              role="alert"
              className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"
            >
              <p className="break-words text-destructive">
                {invalidNotes
                  ? "The AI returned notes in an unexpected format. Your transcript and existing notes were kept. Try rewriting again."
                  : rewriteError}
              </p>
              {invalidNotes ? (
                <details>
                  <summary className="cursor-pointer">Error details</summary>
                  <p className="mt-2 break-words text-xs text-muted-foreground">{rewriteError}</p>
                </details>
              ) : (
                <Link href="/settings/" className="underline underline-offset-4">
                  Check AI service settings
                </Link>
              )}
            </div>
          )}
          <Selector
            label="Format"
            value={template}
            onChange={(value) => value && setTemplate(value)}
            options={(info?.templates ?? []).map((t) => ({ value: t.key, label: t.name }))}
          />
          <TextArea
            label="Instructions"
            rows={3}
            value={instructions}
            onChange={setInstructions}
            placeholder="e.g. Shorter, in bullet points for the director"
          />
        </div>
        <DialogFooter>
          {busy && (
            <p role="status" className="mr-auto self-center text-sm text-muted-foreground">
              {progress}
            </p>
          )}
          <Button onClick={() => run()} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <PenLine />}
            {busy ? "Writing…" : "Rewrite notes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Transcript({ meeting, focus, reload, onRewriting, rewriting }: {
  meeting: MeetingDetail; focus: string | null; reload: () => void
  onRewriting: (id: string) => void; rewriting: boolean
}) {
  const { info } = useInfo()
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

  async function saveCorrections(edits: TranscriptEdit[]) {
    const result = await api<{ session_id: string | null; warning?: string }>(
      `/api/meetings/${encodeURIComponent(meeting.id)}/transcript`, {
        method: "PATCH", json: { revision: meeting.transcript_revision, edits },
      },
    )
    reload()
    if (result.session_id) onRewriting(result.session_id)
    if (result.warning) toast.warning(result.warning)
    else toast.success(result.session_id ? "Corrections saved. Updating your notes…" : "Corrections saved")
  }

  return (
    <div className="space-y-4">
      <div className="max-w-sm">
        <TextInput
          label="Search the transcript"
          isLabelHidden
          type="search"
          startIcon={Search}
          placeholder="Search the transcript…"
          hasClear
          value={q}
          onChange={setQ}
        />
      </div>
      <TranscriptEditor rows={meeting.turns} speakers={meeting.speakers.map(speaker => ({ key: speaker.cluster, label: speaker.label }))}
        people={info?.people} query={q.trim().toLowerCase()} activeId={activeId} focusId={focus}
        onSeek={player?.available ? row => player.seek(row.start, true) : undefined}
        onSave={saveCorrections} disabled={rewriting} />
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
  if (!m) {
    // the list passed the title along, so show it while the rest loads
    const title = recallMeeting(id)
    return (
      <>
        {title && (
          <ViewTransition name={`meeting-title-${id}`} share="morph" default="none">
            <Heading level={1}>{title}</Heading>
          </ViewTransition>
        )}
        <Skeleton className="h-[70vh] rounded-xl" />
      </>
    )
  }

  return (
    <PlayerProvider key={m.id} meetingId={m.id} fallbackDuration={m.duration}>
      <MeetingBody m={m} reload={reload} />
    </PlayerProvider>
  )
}

// same hh:mm:ss format as the timestamp chips inside the generated notes
const stamp = (seconds: number) => {
  const s = Math.max(0, Math.round(seconds))
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((n) => String(n).padStart(2, "0")).join(":")
}

/** Splits trailing citation markers like "(t20)" off a generated sentence. */
function splitCitations(text: string) {
  const ids: string[] = []
  const clean = text.replace(/\s*\((t\d+(?:,\s*t\d+)*)\)/g, (_, list: string) => {
    ids.push(...list.split(/,\s*/))
    return ""
  })
  return { clean, ids }
}

// speaking share: the leader takes the accent, everyone else steps down the neutral ramp
const SHARE_SWATCHES = ["bg-primary", "bg-foreground/40", "bg-foreground/28", "bg-foreground/18", "bg-foreground/12"]

function MeetingBody({ m, reload }: { m: MeetingDetail; reload: () => void }) {
  const { reload: reloadTasks } = useTasks()
  const [tab, setTab] = React.useState("notes")
  const [rewriteOpen, setRewriteOpen] = React.useState(false)
  const [focus, setFocus] = React.useState<string | null>(null)
  const player = usePlayer()
  const router = useRouter()
  const confirm = useConfirm()
  const [deleting, setDeleting] = React.useState(false)
  const [rewriteId, setRewriteId] = React.useState<string | null>(null)
  const activeRewrite = rewriteId ?? m.notes_session_id ?? null
  const rewrite = useApi<Session>(activeRewrite ? `/api/sessions/${activeRewrite}` : null, { interval: 1000 })
  const [completedRewrite, setCompletedRewrite] = React.useState<string | null>(null)
  React.useEffect(() => {
    const session = rewrite.data
    if (!activeRewrite || !session || session.id !== activeRewrite || completedRewrite === activeRewrite) return
    if (session.state === "done" || session.state === "error") {
      // reacting to a polled server session finishing: there is no event to hang this on
      /* eslint-disable react-hooks/set-state-in-effect */
      setCompletedRewrite(activeRewrite)
      setRewriteId(null)
      /* eslint-enable react-hooks/set-state-in-effect */
      reload()
      reloadTasks()
      if (session.state === "error") toast.error("Transcript saved; notes could not be updated", { description: session.error })
      else toast.success("Summary and minutes updated")
    }
  }, [activeRewrite, completedRewrite, rewrite.data, reload, reloadTasks])
  const rewriting = !!activeRewrite && completedRewrite !== activeRewrite


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
  const ranked = [...m.speakers].sort((x, y) => y.talk_seconds - x.talk_seconds)
  const timeChip = (turnId: string) => {
    const turn = m.turns.find((t) => t.id === turnId)
    if (!turn) return null
    return (
      <button key={turnId} type="button" className="time-chip" onClick={() => goToTurn(turnId)}>
        {stamp(turn.start)}
      </button>
    )
  }

  const copyMarkdown = () =>
    navigator.clipboard
      .writeText(m.note!.markdown)
      .then(() => toast.success("Markdown copied"))
      .catch(() => toast.error("Copy failed"))

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex items-center gap-2">
            <ViewTransition name={`meeting-title-${m.id}`} share="morph" default="none">
              <Heading level={1}>{m.title}</Heading>
            </ViewTransition>
            <RenameMeetingDialog id={m.id} title={m.title} onRenamed={reload} />
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Text type="supporting" className="inline-flex items-center gap-1.5">
              <Icon icon={CalendarDays} size="sm" />
              {longDate(m.date)}
            </Text>
            <Text type="supporting" className="inline-flex items-center gap-1.5">
              <Icon icon={Clock} size="sm" />
              {duration(m.duration)} · {m.turns.length} turns
            </Text>
            <Text type="supporting" className="inline-flex items-center gap-1.5">
              <Icon icon={Users} size="sm" />
              {m.speakers.length} {m.speakers.length === 1 ? "speaker" : "speakers"}
              {identified < m.speakers.length ? ` (${identified} identified)` : ""}
            </Text>
            {m.project && <Token label={m.project} size="sm" href={projectHref(m.project)} />}
            {m.people.length > 0 && <AvatarStack names={m.people} max={5} />}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <AstryxButton
            variant="primary"
            label="Ask about this meeting"
            icon={<Icon icon={MessagesSquare} />}
            href={`/chat/?meeting=${encodeURIComponent(m.id)}`}
          />
          <AstryxButton
            label="Rewrite with AI"
            icon={<Icon icon={PenLine} />}
            onClick={() => setRewriteOpen(true)}
          />
          <MoreMenu
            alignment="end"
            items={[
              ...(m.note
                ? [
                    { label: "Open in Obsidian", icon: <Icon icon={ExternalLink} />, href: m.note.obsidian_url },
                    { label: "Copy Markdown", icon: <Icon icon={Copy} />, onClick: copyMarkdown },
                    { type: "divider" as const },
                  ]
                : []),
              {
                label: "Delete meeting",
                icon: <Icon icon={Trash2} />,
                variant: "destructive" as const,
                isDisabled: deleting,
                onClick: deleteMeeting,
              },
            ]}
          />
        </div>
      </div>
      <RewriteDialog meeting={m} open={rewriteOpen} setOpen={setRewriteOpen} onDone={reload} />

      {rewriting ? (
        <Banner
          status="info"
          collapsible={false}
          title="Updating the summary and minutes…"
          description="Transcript corrections are saved."
        />
      ) : (
        m.notes_stale && (
          <Banner
            status="warning"
            collapsible={false}
            title="The notes reflect the earlier transcript"
            description="The transcript has been corrected since these notes were written."
            endContent={<AstryxButton size="sm" label="Rewrite with AI" onClick={() => setRewriteOpen(true)} />}
          />
        )
      )}

      <div className="grid gap-4 @5xl/main:grid-cols-3">
        <div className="min-w-0 @5xl/main:col-span-2">
          <TabList role="tablist" value={tab} onChange={setTab} hasDivider>
            <Tab value="notes" label="Notes" panelId="meeting-panel" />
            <Tab value="transcript" label="Transcript" panelId="meeting-panel" />
            <Tab
              value="actions"
              label="Action items"
              panelId="meeting-panel"
              endContent={openTasks > 0 ? <AstryxBadge label={openTasks} variant="neutral" /> : undefined}
            />
          </TabList>
          <AstryxCard padding={4} className="mt-3">
            <div id="meeting-panel" role="tabpanel">
              {tab === "notes" &&
                (m.note ? (
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
                ))}
              {tab === "transcript" && (
                <Transcript meeting={m} focus={focus} reload={reload} onRewriting={setRewriteId} rewriting={rewriting} />
              )}
              {tab === "actions" &&
                (m.tasks.length ? (
                  <ActionList items={m.tasks.map((t) => ({ ...t, meeting_id: m.id }))} onChange={reload} />
                ) : (
                  <EmptyState icon={ListChecks} title="No action items" className="py-8" />
                ))}
            </div>
          </AstryxCard>
          <PlayerBar turns={m.turns} className="mt-4" />
        </div>

        <div className="flex flex-col gap-4">
          <AstryxCard padding={4}>
            <div className="flex flex-col gap-4">
              <div>
                <Heading level={3}>Speakers</Heading>
                <Text type="supporting">Share of speaking time</Text>
              </div>
              <div className="flex h-2 gap-0.5 overflow-hidden rounded-full" role="img" aria-label="Share of speaking time by speaker">
                {ranked.map((s, i) => (
                  <span
                    key={s.cluster}
                    className={SHARE_SWATCHES[Math.min(i, SHARE_SWATCHES.length - 1)]}
                    style={{ width: `${(s.talk_seconds / total) * 100}%` }}
                  />
                ))}
              </div>
              <ul className="flex flex-col gap-2">
                {ranked.map((s, i) => (
                  <li key={s.cluster} className="flex items-center gap-2">
                    <span
                      className={`size-2 shrink-0 rounded-full ${SHARE_SWATCHES[Math.min(i, SHARE_SWATCHES.length - 1)]}`}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <Text color={s.name ? "primary" : "secondary"} maxLines={1}>
                        {s.label}
                      </Text>
                    </span>
                    <Text color={i === 0 ? "accent" : "secondary"} className="tabular-nums">
                      {Math.round((s.talk_seconds / total) * 100)}%
                    </Text>
                  </li>
                ))}
              </ul>
            </div>
          </AstryxCard>
          {m.decisions.length > 0 && (
            <AstryxCard padding={4}>
              <div className="flex flex-col gap-3">
                <div>
                  <Heading level={3}>Decisions</Heading>
                  <Text type="supporting">Select a time to hear where it was decided</Text>
                </div>
                <ul className="flex flex-col gap-2.5 text-[13px] leading-snug">
                  {m.decisions.map((d) => (
                    <li key={d.decision}>
                      {d.decision} {d.source_turns.slice(0, 1).map(timeChip)}
                    </li>
                  ))}
                </ul>
              </div>
            </AstryxCard>
          )}
          {m.open_questions.length > 0 && (
            <AstryxCard padding={4}>
              <div className="flex flex-col gap-3">
                <Heading level={3}>Open questions</Heading>
                <ul className="flex flex-col gap-2.5 text-[13px] leading-snug">
                  {m.open_questions.map((q) => {
                    const { clean, ids } = splitCitations(q)
                    return (
                      <li key={q}>
                        {clean} {ids.map(timeChip)}
                      </li>
                    )
                  })}
                </ul>
              </div>
            </AstryxCard>
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
