"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { Card } from "@astryxdesign/core/Card"
import { Heading } from "@astryxdesign/core/Heading"
import { Icon } from "@astryxdesign/core/Icon"
import { Text } from "@astryxdesign/core/Text"
import { AlertTriangle, Check, Loader2, Merge, Pause, Play, Square, Trash2 } from "lucide-react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { toast } from "@/lib/toast"

import { SpeakerAvatar } from "@/components/common"
import { useConfirm } from "@/components/confirm"
import { useInfo } from "@/components/providers"
import { TranscriptEditor } from "@/components/transcript-editor"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { api, apiUrl, type LiveSegment, type Session } from "@/lib/api"
import { clock, duration } from "@/lib/format"
import { springSnappy } from "@/lib/motion"
import { recorder, useRecorder } from "@/lib/recorder"
import { cn } from "@/lib/utils"
import { type TranscriptEdit } from "@/lib/transcript-edits"

// -- recording ---------------------------------------------------------------------------------

// A notepad for the person running the meeting. What they type is saved to the session as they
// go, the summariser is told to cover it, and it is kept word for word in the finished note.
function SessionNotes({ session }: { session: Session }) {
  const [text, setText] = React.useState(session.meta.user_notes ?? "")
  const [status, setStatus] = React.useState<"saved" | "saving" | "failed">("saved")
  const pending = React.useRef<string | null>(null)
  const timer = React.useRef<number | undefined>(undefined)

  const save = React.useCallback(async () => {
    window.clearTimeout(timer.current)
    const notes = pending.current
    if (notes === null) return
    pending.current = null
    try {
      await api(`/api/sessions/${session.id}/notes`, { method: "PUT", json: { notes } })
      if (pending.current === null) setStatus("saved")
    } catch {
      // keep it queued; the next keystroke or leaving the page tries again
      if (pending.current === null) pending.current = notes
      setStatus("failed")
    }
  }, [session.id])

  // leaving the page, or the recording ending, must not drop the last few words typed
  React.useEffect(() => () => void save(), [save])

  function change(value: string) {
    setText(value)
    setStatus("saving")
    pending.current = value
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(save, 600)
  }

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-container)] border bg-card p-5 @4xl/main:sticky @4xl/main:top-4 @4xl/main:order-last @4xl/main:self-start">
      <div className="flex items-baseline justify-between gap-3">
        <Heading level={3}>My notes</Heading>
        <Text type="supporting" size="xsm" aria-live="polite">
          {status === "failed" ? "Not saved yet" : status === "saving" ? "Saving…" : text ? "Saved" : ""}
        </Text>
      </div>
      <Textarea
        value={text}
        onChange={(e) => change(e.target.value)}
        maxLength={20000}
        placeholder="Jot down what matters as you go"
        aria-label="My notes"
        className="min-h-40 @4xl/main:max-h-[60vh] @4xl/main:overflow-y-auto"
      />
      <Text type="supporting" size="xsm">
        The minutes are written to cover these points, and your notes are kept with them
      </Text>
    </div>
  )
}

function Waveform({ levels }: { levels: number[] }) {
  return (
    <div className="flex h-10 min-w-24 flex-1 items-center gap-0.5" aria-hidden>
      {levels.map((l, i) => (
        <motion.span
          key={i}
          className="h-full w-full origin-center rounded-full bg-primary"
          animate={{ scaleY: Math.max(0.06, l), opacity: 0.35 + l * 0.65 }}
          transition={springSnappy}
        />
      ))}
    </div>
  )
}

export function RecordingView({ session, live, onCorrected }: {
  session: Session; live: LiveSegment[]; onCorrected: (session: Session) => void
}) {
  const { info } = useInfo()
  const [editingSpeakers, setEditingSpeakers] = React.useState(false)
  const rec = useRecorder()
  const local = rec.sessionId === session.id
  const [now, setNow] = React.useState(() => Date.now())
  const [stopping, setStopping] = React.useState(false)
  const confirm = useConfirm()
  const reduce = useReducedMotion()

  React.useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(t)
  }, [])
  // follow the newest words, but only while the reader is already at the end of the page
  const lastRev = live.reduce((m, seg) => Math.max(m, seg.rev ?? 0), 0)
  React.useEffect(() => {
    if (editingSpeakers) return
    const doc = document.scrollingElement
    if (!doc || doc.scrollHeight - doc.scrollTop - doc.clientHeight > 160) return
    window.scrollTo({ top: doc.scrollHeight, behavior: reduce ? "auto" : "smooth" })
  }, [lastRev, reduce, editingSpeakers])

  const elapsed = local ? (now - rec.startedAt) / 1000 : session.elapsed

  // Merge consecutive segments from the same speaker into one paragraph. Interim words that
  // haven't been matched to a voice yet most likely continue the current speaker, so they join
  // the paragraph above until their own label arrives.
  type Part = { id: number; text: string; partial: boolean }
  type Turn = { key: number; speaker: string | null; start: number; parts: Part[] }
  const turns = live.reduce<Turn[]>(
    (acc, seg) => {
      const last = acc[acc.length - 1]
      const part = { id: seg.id, text: seg.text, partial: seg.partial }
      const same = last && seg.speaker && last.speaker === seg.speaker
      if (last && (same || (seg.partial && !seg.speaker))) last.parts.push(part)
      else acc.push({ key: seg.id, speaker: seg.speaker, start: seg.start, parts: [part] })
      return acc
    },
    [],
  )

  const rows = live.map(seg => ({
    ...seg, id: String(seg.id), speaker: seg.speaker ? `live:${seg.speaker}` : null,
    label: seg.speaker ?? "Speaker",
  }))
  const speakers = [...new Set(live.flatMap(seg => seg.speaker ? [seg.speaker] : []))]
    .map(label => ({ key: `live:${label}`, label }))

  async function correctSpeaker(edit: TranscriptEdit) {
    const selected = edit.rename_speaker
      ? rows.filter(row => row.speaker === edit.speaker && !row.partial).slice(0, 1)
      : rows.filter(row => edit.turn_ids.includes(row.id))
    const name = edit.name ?? speakers.find(speaker => speaker.key === edit.speaker)?.label
    if (!selected.length || !name) throw new Error("This speaker is still being identified")
    const result = await api<Session>(`/api/sessions/${session.id}/live-speakers`, {
      method: "PATCH", json: {
        segment_ids: selected.map(row => Number(row.id)), name,
        rename_speaker: !!edit.rename_speaker,
        revisions: Object.fromEntries(selected.map(row => [row.id, row.rev])),
      },
    })
    onCorrected(result)
  }

  async function stop() {
    setStopping(true)
    await recorder.stop()
  }
  async function discard() {
    const ok = await confirm({
      title: "Discard this recording?",
      description: "The audio and live transcript are deleted. This can't be undone.",
      confirmLabel: "Discard",
      destructive: true,
    })
    if (!ok) return
    await api(`/api/sessions/${session.id}/cancel`, { method: "POST" }).catch(() => {})
    recorder.release()
  }

  // Controls float on a raised bar at the bottom; the transcript scrolls underneath.
  const controls = (
    <div className="sticky bottom-[max(1rem,env(safe-area-inset-bottom))] z-20">
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className="mx-auto flex max-w-3xl flex-wrap items-center gap-4 rounded-xl border bg-card p-3 pl-5 shadow-[var(--shadow-card)] sm:flex-nowrap"
      >
        <div className="flex items-center gap-3">
          <span className="relative flex size-3">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-recording opacity-60" />
            <span className="relative inline-flex size-3 rounded-full bg-recording" />
          </span>
          <span className="font-mono text-2xl font-medium tabular-nums" aria-label="Elapsed">
            {clock(elapsed)}
          </span>
        </div>
        {local ? (
          <Waveform levels={rec.levels} />
        ) : (
          <p className="flex-1 text-sm text-muted-foreground">
            Recording in another browser tab or window.
          </p>
        )}
        <div className="ml-auto flex items-center gap-2">
          {local && (
            <Button
              variant="ghost"
              label="Discard"
              icon={<Icon icon={Trash2} />}
              onClick={discard}
              isDisabled={stopping}
            />
          )}
          <Button
            variant="primary"
            label="Stop & process"
            icon={<Icon icon={Square} className="fill-current" />}
            onClick={stop}
            isLoading={stopping}
            isDisabled={!local}
          />
        </div>
      </motion.div>
    </div>
  )

  return (
    <div className="flex flex-col gap-6">
      {session.warning && (
        <p role="status" className="flex items-start gap-2 rounded-lg bg-warning-subtle px-4 py-2 text-sm text-warning">
          <Icon icon={AlertTriangle} className="mt-0.5 shrink-0" />
          {session.warning}
        </p>
      )}

      <div className="grid gap-6 @4xl/main:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
      <SessionNotes session={session} />
      <div className="min-w-0 rounded-[var(--radius-container)] border bg-card">
        <div className="flex flex-col gap-1 border-b p-5">
          <Heading level={3}>{session.meta.title || "Live transcript"}</Heading>
          {local && rec.source === "meeting" && (
            <Text type="supporting" size="xsm">
              {!rec.includesMeetingAudio
                ? rec.includesMicrophone ? "Microphone only" : "Saving recording"
                : rec.includesMicrophone ? "Meeting audio + microphone" : "Meeting audio only"}
            </Text>
          )}
        </div>
        <div className="min-h-[40vh] p-5">
          {!session.meta.live ? (
            <Text type="supporting" display="block" className="py-8 text-center">
              Live transcript is off for this meeting
            </Text>
          ) : turns.length === 0 ? (
            <Text type="supporting" display="block" className="py-8 text-center">
              <span className="mr-2 inline-block size-1.5 rounded-full bg-recording align-middle" aria-hidden />
              Listening, words appear as people speak
            </Text>
          ) : (
            <TranscriptEditor rows={rows} speakers={speakers} people={info?.people}
              live onEdit={correctSpeaker} onEditingChange={setEditingSpeakers} disabled={stopping}>
            <ul className="space-y-4">
              {turns.map((t) => (
                <motion.li
                  key={t.key}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex gap-3"
                >
                  <SpeakerAvatar name={t.speaker ?? "…"} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 text-sm">
                      <span className="font-medium">{t.speaker ?? "Speaker"}</span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {clock(t.start)}
                      </span>
                    </div>
                    <p className="text-sm leading-relaxed">
                      {t.parts.map((p, j) => (
                        <span
                          key={p.id}
                          // interim words are lighter until the pause confirms them
                          className={cn(
                            "transition-colors duration-300",
                            p.partial && "text-muted-foreground",
                          )}
                        >
                          {j > 0 && " "}
                          {p.text}
                        </span>
                      ))}
                      {t.parts[t.parts.length - 1].partial && (
                        <span
                          aria-hidden
                          className="ml-1 inline-block size-1.5 animate-pulse rounded-full bg-primary align-middle"
                        />
                      )}
                    </p>
                  </div>
                </motion.li>
              ))}
            </ul>
            </TranscriptEditor>
          )}
        </div>
      </div>
      </div>
      {controls}
    </div>
  )
}

// -- processing --------------------------------------------------------------------------------

const ANALYSIS_STEPS = [
  { label: "Saving the recording", match: /saving|waiting|reading/i },
  { label: "Separating speakers", match: /diariz/i },
  { label: "Transcribing speech", match: /transcrib/i },
  { label: "Matching words to speakers", match: /align/i },
  { label: "Recognising voices", match: /recognis/i },
]
const NOTES_STEPS = [
  { label: "Remembering confirmed voices", match: /remember|waiting/i },
  { label: "Writing summary & minutes", match: /writing|llm/i },
  { label: "Saving the note to your vault", match: /^$/ },
]

export function ProcessingView({ session }: { session: Session }) {
  const { info } = useInfo()
  const notes = session.state === "summarizing"
  const steps = notes ? NOTES_STEPS : ANALYSIS_STEPS
  let current = 0
  session.messages.forEach((m) => {
    const i = steps.findIndex((s) => s.match.test(m))
    if (i > current) current = i
  })
  const latest = session.messages[session.messages.length - 1] ?? steps[0].label

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-6 rounded-[var(--radius-container)] border bg-card p-5">
      <Text type="supporting" display="block" className="text-center">
        {notes
          ? `The local LLM (${info?.models.llm ?? "LLM"}) is reading the transcript`
          : "Everything runs on this computer. A one-hour meeting takes a few minutes."}
      </Text>
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.label} className="flex items-center gap-3 text-sm">
            <span
              className={cn(
                "flex size-6 items-center justify-center rounded-full border",
                i < current && "border-primary bg-primary text-primary-foreground",
                i === current && "border-primary text-primary",
              )}
            >
              {i < current ? (
                <Check className="size-3.5" />
              ) : i === current ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <span className="size-1.5 rounded-full bg-muted-foreground/40" />
              )}
            </span>
            <span className={cn(i > current && "text-muted-foreground", i === current && "font-medium")}>
              {s.label}
            </span>
          </li>
        ))}
      </ol>
      <p className="truncate text-center font-mono text-xs text-muted-foreground">{latest}</p>
    </div>
  )
}

// -- speaker review ----------------------------------------------------------------------------

/** Recognition status as a dot and plain words; the match score stays available as a tooltip. */
function SpeakerStatus({ speaker }: { speaker: NonNullable<Session["speakers"]>[number] }) {
  const [dot, label] = speaker.live_assigned
    ? ["bg-brand", "Assigned live"]
    : speaker.status === "auto"
      ? ["bg-success", "Recognised"]
      : speaker.status === "suggested"
        ? ["bg-warning", `Likely ${speaker.suggestion}`]
        : ["bg-foreground/30", "New voice"]
  const match =
    !speaker.live_assigned && speaker.score != null && speaker.status !== "unknown"
      ? `${Math.round(speaker.score * 100)}% voice match`
      : undefined
  return (
    <span title={match} className="inline-flex">
      <Text type="supporting" className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <span className={cn("size-1.5 rounded-full", dot)} aria-hidden />
        {label}
      </Text>
    </span>
  )
}

export function ReviewView({ session }: { session: Session }) {
  const { info } = useInfo()
  const speakers = session.speakers ?? []
  const [names, setNames] = React.useState<Record<string, string>>(() =>
    // only voices the system is sure about start filled in; a suggestion has to be accepted,
    // because a confirmed name teaches the voiceprint
    Object.fromEntries(speakers.map((s) => [s.cluster, s.name ?? ""])),
  )
  const [playing, setPlaying] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const audio = React.useRef<HTMLAudioElement | null>(null)

  function play(cluster: string) {
    audio.current?.pause()
    if (playing === cluster) {
      setPlaying(null)
      return
    }
    const el = new Audio(apiUrl(`/api/sessions/${session.id}/clips/${encodeURIComponent(cluster)}`))
    el.onended = () => setPlaying(null)
    el.play().catch((e) => toast.error(`Cannot play clip: ${e.message}`))
    audio.current = el
    setPlaying(cluster)
  }

  async function submit() {
    setBusy(true)
    audio.current?.pause()
    try {
      await api(`/api/sessions/${session.id}/review`, {
        method: "POST",
        json: {
          names: Object.fromEntries(
            speakers.map((s) => [s.cluster, names[s.cluster]?.trim() || null]),
          ),
        },
      })
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(false)
    }
  }

  // the same name on two cards means one person was split into two voices; say so as they type
  const counts = new Map<string, number>()
  for (const s of speakers) {
    const n = names[s.cluster]?.trim()
    if (n) counts.set(n, (counts.get(n) ?? 0) + 1)
  }

  const pending = speakers.filter(
    (s) => s.status === "suggested" && s.suggestion && !names[s.cluster]?.trim(),
  ).length

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 @3xl/main:grid-cols-2">
        {speakers.map((s, i) => {
          const name = names[s.cluster] ?? ""
          const shared = (counts.get(name.trim()) ?? 0) > 1
          return (
            <motion.div
              key={s.cluster}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i, 5) * 0.05 }}
            >
              <Card padding={5}>
                <div className="flex flex-col gap-4">
                  <div className="flex items-center gap-3">
                    <SpeakerAvatar name={name || s.unknown_label} />
                    <div className="min-w-0 flex-1">
                      <Text weight="medium" display="block" maxLines={1}>
                        {name || s.unknown_label}
                      </Text>
                      <Text type="supporting">
                        {duration(s.talk_seconds)} · {s.turns} turn{s.turns === 1 ? "" : "s"}
                      </Text>
                    </div>
                    <SpeakerStatus speaker={s} />
                  </div>
                  <div className="space-y-2">
                    {s.quotes.map((q) => (
                      <blockquote
                        key={q.start}
                        className="border-l-2 border-border pl-3 text-sm text-muted-foreground"
                      >
                        <span className="mr-2 font-mono text-xs">{clock(q.start)}</span>“
                        {q.text.length > 200 ? q.text.slice(0, 197) + "…" : q.text}”
                      </blockquote>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      list="review-people"
                      value={name}
                      placeholder="Name"
                      onChange={(e) => setNames((n) => ({ ...n, [s.cluster]: e.target.value }))}
                      aria-label={`Name of speaker ${i + 1}`}
                    />
                    <span className="shrink-0">
                      <Button
                        label="Voice"
                        icon={<Icon icon={playing === s.cluster ? Pause : Play} />}
                        onClick={() => play(s.cluster)}
                        isDisabled={!s.has_clip}
                      />
                    </span>
                  </div>
                  {s.status === "suggested" && s.suggestion && !name.trim() && (
                    <div>
                      <Button
                        size="sm"
                        variant="secondary"
                        label={`Use ${s.suggestion}`}
                        onClick={() => setNames((n) => ({ ...n, [s.cluster]: s.suggestion ?? "" }))}
                      />
                    </div>
                  )}
                  <AnimatePresence initial={false}>
                    {shared && (
                      <motion.p
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="flex items-center gap-1.5 text-xs text-muted-foreground"
                      >
                        <Merge className="size-3.5 shrink-0" />
                        Another voice is also named {name.trim()}. They&apos;ll be merged into one
                        person.
                      </motion.p>
                    )}
                  </AnimatePresence>
                </div>
              </Card>
            </motion.div>
          )
        })}
      </div>
      <datalist id="review-people">
        {info?.people.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
      <div className="flex items-center justify-end gap-3">
        <p className="text-sm text-muted-foreground">
          {pending > 0
            ? `${pending} suggested ${pending === 1 ? "voice isn't" : "voices aren't"} named yet`
            : "Confirmed voices are remembered for future meetings."}
        </p>
        <Button variant="primary" size="lg" label="Confirm & write notes" onClick={submit} isLoading={busy} />
      </div>
    </div>
  )
}
