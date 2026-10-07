"use client"

import * as React from "react"
import { Check, Loader2, Pause, Play, Square, Trash2 } from "lucide-react"
import { motion } from "motion/react"
import { toast } from "sonner"

import { Progress } from "@/components/animate-ui/components/radix/progress"
import { ShimmeringText } from "@/components/animate-ui/primitives/texts/shimmering"
import { SpeakerAvatar } from "@/components/common"
import { useInfo } from "@/components/providers"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api, apiUrl, type LiveSegment, type Session } from "@/lib/api"
import { clock, colorFor, duration } from "@/lib/format"
import { recorder, useRecorder } from "@/lib/recorder"
import { cn } from "@/lib/utils"

// -- recording ---------------------------------------------------------------------------------

function Waveform({ levels }: { levels: number[] }) {
  return (
    <div className="flex h-16 flex-1 items-center gap-[3px]" aria-hidden>
      {levels.map((l, i) => (
        <motion.span
          key={i}
          className="w-full rounded-full bg-primary"
          animate={{ height: `${Math.max(6, l * 100)}%`, opacity: 0.35 + l * 0.65 }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
        />
      ))}
    </div>
  )
}

export function RecordingView({ session, live }: { session: Session; live: LiveSegment[] }) {
  const rec = useRecorder()
  const local = rec.sessionId === session.id
  const [now, setNow] = React.useState(() => Date.now())
  const [stopping, setStopping] = React.useState(false)
  const box = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(t)
  }, [])
  React.useEffect(() => {
    const el = box.current
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 120) el.scrollTop = el.scrollHeight
  }, [live.length])

  const elapsed = local ? (now - rec.startedAt) / 1000 : session.elapsed

  // merge consecutive segments from the same speaker into one paragraph
  const turns = live.reduce<{ speaker: string | null; start: number; text: string }[]>(
    (acc, seg) => {
      const last = acc[acc.length - 1]
      if (last && seg.speaker && last.speaker === seg.speaker) last.text += " " + seg.text
      else acc.push({ speaker: seg.speaker, start: seg.start, text: seg.text })
      return acc
    },
    [],
  )

  async function stop() {
    setStopping(true)
    await recorder.stop()
  }
  async function discard() {
    if (!confirm("Discard this recording? The audio will be deleted.")) return
    await api(`/api/sessions/${session.id}/cancel`, { method: "POST" }).catch(() => {})
    recorder.release()
  }

  return (
    <div className="flex flex-col gap-6">
      <Card className="py-5">
        <CardContent className="flex flex-wrap items-center gap-5">
          <div className="flex items-center gap-3">
            <span className="relative flex size-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-recording opacity-60" />
              <span className="relative inline-flex size-3 rounded-full bg-recording" />
            </span>
            <span className="font-mono text-3xl font-semibold tabular-nums">{clock(elapsed)}</span>
          </div>
          {local ? (
            <Waveform levels={rec.levels} />
          ) : (
            <p className="flex-1 text-sm text-muted-foreground">
              Recording in another browser tab or window.
            </p>
          )}
          <div className="flex items-center gap-2">
            {local && (
              <Button variant="ghost" onClick={discard} disabled={stopping}>
                <Trash2 />
                Discard
              </Button>
            )}
            <Button
              onClick={stop}
              disabled={!local || stopping}
              className="bg-foreground text-background hover:bg-foreground/90"
            >
              {stopping ? <Loader2 className="animate-spin" /> : <Square className="fill-current" />}
              Stop &amp; process
            </Button>
          </div>
        </CardContent>
      </Card>

      {session.warning && (
        <p className="rounded-lg bg-warning/10 px-4 py-2 text-sm text-warning">{session.warning}</p>
      )}

      <Card className="gap-0">
        <CardHeader className="border-b pb-4">
          <CardTitle>{session.meta.title || "Live transcript"}</CardTitle>
          <CardDescription>
            A live preview. When you stop, the whole recording is processed again and you confirm
            each speaker.
          </CardDescription>
        </CardHeader>
        <CardContent ref={box} className="max-h-[52vh] overflow-y-auto pt-4">
          {!session.meta.live ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Live transcript is off for this meeting.
            </p>
          ) : turns.length === 0 ? (
            <div className="py-8 text-center">
              <ShimmeringText
                text="Listening… the transcript appears after the first pause"
                className="text-sm"
              />
            </div>
          ) : (
            <ul className="space-y-4">
              {turns.map((t, i) => (
                <motion.li
                  key={`${t.start}-${i}`}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex gap-3"
                >
                  <SpeakerAvatar name={t.speaker ?? "…"} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 text-sm">
                      <span className="font-semibold" style={{ color: colorFor(t.speaker) }}>
                        {t.speaker ?? "Speaker"}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {clock(t.start)}
                      </span>
                    </div>
                    <p className="text-sm leading-relaxed">{t.text}</p>
                  </div>
                </motion.li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
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
    <Card className="mx-auto w-full max-w-xl">
      <CardHeader className="text-center">
        <CardTitle className="text-xl">
          <ShimmeringText text={notes ? "Writing your notes" : "Processing the recording"} />
        </CardTitle>
        <CardDescription>
          {notes
            ? `The local LLM (${info?.models.llm ?? "LLM"}) is reading the transcript.`
            : "Everything runs on this computer. A one-hour meeting takes a few minutes."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <Progress value={((current + 0.5) / steps.length) * 100} />
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
      </CardContent>
    </Card>
  )
}

// -- speaker review ----------------------------------------------------------------------------

export function ReviewView({ session }: { session: Session }) {
  const { info } = useInfo()
  const speakers = session.speakers ?? []
  const [names, setNames] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(speakers.map((s) => [s.cluster, s.name ?? s.suggestion ?? ""])),
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

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 @3xl/main:grid-cols-2">
        {speakers.map((s, i) => {
          const name = names[s.cluster] ?? ""
          return (
            <motion.div
              key={s.cluster}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
            >
              <Card className="h-full">
                <CardHeader className="flex flex-row items-center gap-3">
                  <SpeakerAvatar name={name || s.unknown_label} size="lg" />
                  <div className="min-w-0 flex-1">
                    <CardTitle className="truncate">{name || s.unknown_label}</CardTitle>
                    <CardDescription>
                      {duration(s.talk_seconds)} · {s.turns} turn{s.turns === 1 ? "" : "s"}
                    </CardDescription>
                  </div>
                  {s.status === "auto" ? (
                    <Badge className="bg-success/15 text-success">
                      Recognised · {s.score?.toFixed(2)}
                    </Badge>
                  ) : s.status === "suggested" ? (
                    <Badge className="bg-warning/15 text-warning">
                      Maybe {s.suggestion} · {s.score?.toFixed(2)}
                    </Badge>
                  ) : (
                    <Badge variant="secondary">New voice</Badge>
                  )}
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    {s.quotes.map((q) => (
                      <blockquote
                        key={q.start}
                        className="border-l-2 pl-3 text-sm text-muted-foreground"
                        style={{ borderColor: colorFor(name || s.unknown_label) }}
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
                      placeholder={`Name, or leave empty for “${s.unknown_label}”`}
                      onChange={(e) => setNames((n) => ({ ...n, [s.cluster]: e.target.value }))}
                      aria-label={`Name of speaker ${i + 1}`}
                    />
                    <Button
                      variant="outline"
                      onClick={() => play(s.cluster)}
                      disabled={!s.has_clip}
                    >
                      {playing === s.cluster ? <Pause /> : <Play />}
                      Voice
                    </Button>
                  </div>
                </CardContent>
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
          Confirmed voices are remembered for future meetings.
        </p>
        <Button size="lg" onClick={submit} disabled={busy}>
          {busy && <Loader2 className="animate-spin" />}
          Confirm &amp; write notes
        </Button>
      </div>
    </div>
  )
}
