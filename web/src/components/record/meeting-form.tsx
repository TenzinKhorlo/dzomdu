"use client"

import * as React from "react"
import { FileAudio, FolderPlus, Loader2, Mic, Upload, Video, X } from "lucide-react"
import { toast } from "sonner"

import { NewProjectDialog } from "@/components/new-project-dialog"
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
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import { recorder, type RecordingSource } from "@/lib/recorder"
import { cn } from "@/lib/utils"

type Meta = {
  title: string
  project: string
  attendees: string[]
  template: string
  num_speakers: string
  live: boolean
  summarize: boolean
  instructions: string
}

function AttendeeInput({
  value,
  onChange,
  suggestions,
}: {
  value: string[]
  onChange: (v: string[]) => void
  suggestions: string[]
}) {
  const [draft, setDraft] = React.useState("")
  const add = (raw: string) => {
    const name = raw.trim().replace(/,$/, "").trim()
    if (name && !value.some((v) => v.toLowerCase() === name.toLowerCase())) {
      onChange([...value, name])
    }
    setDraft("")
  }
  return (
    <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border bg-transparent px-2 py-1.5 shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 dark:bg-input/30">
      {value.map((name) => (
        <Badge key={name} variant="secondary" className="gap-1 pr-1">
          {name}
          <button
            type="button"
            className="rounded-full p-0.5 hover:bg-foreground/10"
            onClick={() => onChange(value.filter((v) => v !== name))}
            aria-label={`Remove ${name}`}
          >
            <X className="size-3" />
          </button>
        </Badge>
      ))}
      <input
        id="attendees"
        list="people-suggestions"
        value={draft}
        onChange={(e) => {
          const v = e.target.value
          if (suggestions.includes(v)) add(v)
          else setDraft(v)
        }}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === ",") && draft.trim()) {
            e.preventDefault()
            add(draft)
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1))
          } else if (e.key === "Enter") e.preventDefault()
        }}
        onBlur={() => draft.trim() && add(draft)}
        placeholder={value.length ? "" : "Type a name and press Enter"}
        className="min-w-40 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
      />
      <datalist id="people-suggestions">
        {suggestions.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
    </div>
  )
}

const NO_PROJECT = "__none__"

export function MeetingForm({
  onSession,
  focusUpload = false,
}: {
  onSession: (id: string) => void
  focusUpload?: boolean
}) {
  const { info } = useInfo()
  const [meta, setMeta] = React.useState<Meta>({
    title: "",
    project: "",
    attendees: [],
    template: "",
    num_speakers: "",
    live: true,
    summarize: true,
    instructions: "",
  })
  const [busy, setBusy] = React.useState<"record" | "upload" | null>(null)
  const [dragging, setDragging] = React.useState(false)
  const fileRef = React.useRef<HTMLInputElement>(null)
  const set = <K extends keyof Meta>(k: K, v: Meta[K]) => setMeta((m) => ({ ...m, [k]: v }))
  const template = meta.template || info?.default_template || "standard"

  const payload = () => ({
    ...meta,
    template,
    num_speakers: meta.num_speakers ? Number(meta.num_speakers) : null,
  })

  async function startRecording(source: RecordingSource = "room") {
    setBusy("record")
    let id: string | null = null
    try {
      id = (await api<{ id: string }>("/api/sessions", { method: "POST", json: payload() })).id
      await recorder.start(id, source)
      onSession(id)
    } catch (e) {
      recorder.release() // drop any microphone or shared-tab stream that was already open
      if (id) await api(`/api/sessions/${id}/cancel`, { method: "POST" }).catch(() => {})
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function upload(file: File) {
    setBusy("upload")
    const form = new FormData()
    form.append("file", file)
    form.append("meta", JSON.stringify(payload()))
    try {
      const { id } = await api<{ id: string }>("/api/upload", { method: "POST", body: form })
      toast.success(`Uploaded ${file.name}`)
      onSession(id)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="grid gap-6 @5xl/main:grid-cols-5">
      <Card className="@5xl/main:col-span-3">
        <CardHeader>
          <CardTitle>Meeting details</CardTitle>
          <CardDescription>
            All optional. Attendees narrow voice matching to those people, which makes recognition
            more accurate.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 sm:grid-cols-2">
          <div className="grid gap-2 sm:col-span-2">
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              placeholder="Leave empty and the AI suggests one"
              value={meta.title}
              onChange={(e) => set("title", e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label>Project</Label>
            <div className="flex gap-2">
              <Select
                value={meta.project || NO_PROJECT}
                onValueChange={(v) => set("project", v === NO_PROJECT ? "" : v)}
              >
                <SelectTrigger className="w-full min-w-0 flex-1" aria-label="Project">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PROJECT}>No project</SelectItem>
                  {[...new Set([...(info?.projects ?? []), ...(meta.project ? [meta.project] : [])])].map(
                    (p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ),
                  )}
                </SelectContent>
              </Select>
              <NewProjectDialog onCreated={(name) => set("project", name)}>
                <Button type="button" variant="outline" size="icon" aria-label="New project" title="New project">
                  <FolderPlus />
                </Button>
              </NewProjectDialog>
            </div>
          </div>
          <div className="grid gap-2">
            <Label>Minutes format</Label>
            <Select value={template} onValueChange={(v) => set("template", v)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {info?.templates.map((t) => (
                  <SelectItem key={t.key} value={t.key}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2 sm:col-span-2">
            <Label htmlFor="attendees">Attendees</Label>
            <AttendeeInput
              value={meta.attendees}
              onChange={(v) => set("attendees", v)}
              suggestions={info?.people ?? []}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="speakers">Number of speakers</Label>
            <Input
              id="speakers"
              type="number"
              min={1}
              max={30}
              placeholder="Detect automatically"
              value={meta.num_speakers}
              onChange={(e) => set("num_speakers", e.target.value)}
            />
          </div>
          <div className="grid content-end gap-3">
            <label className="flex items-center justify-between gap-3 text-sm">
              Live transcript
              <Switch checked={meta.live} onCheckedChange={(v) => set("live", v)} />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm">
              Write summary &amp; minutes
              <Switch checked={meta.summarize} onCheckedChange={(v) => set("summarize", v)} />
            </label>
          </div>
          <div className="grid gap-2 sm:col-span-2">
            <Label htmlFor="instructions">Extra instructions for the summary</Label>
            <Textarea
              id="instructions"
              rows={2}
              placeholder="e.g. Keep it short, bullet points for the director"
              value={meta.instructions}
              onChange={(e) => set("instructions", e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-6 @5xl/main:col-span-2">
        <Card className="items-center gap-5 py-10 text-center">
          <button
            type="button"
            onClick={() => startRecording("room")}
            disabled={busy !== null}
            className="group relative flex size-28 items-center justify-center rounded-full bg-recording text-white shadow-lg shadow-recording/30 transition-transform hover:scale-105 disabled:opacity-60"
            aria-label="Start recording"
          >
            <span className="absolute -inset-3 animate-pulse rounded-full bg-recording/15 [animation-duration:2.4s]" />
            {busy === "record" ? <Loader2 className="size-9 animate-spin" /> : <Mic className="size-10" />}
          </button>
          <div className="space-y-1 px-6">
            <p className="text-lg font-semibold">Start recording</p>
            <p className="text-sm text-muted-foreground">
              Place the laptop or speakerphone in the middle of the table. Audio never leaves this
              computer.
            </p>
          </div>
        </Card>

        <Card className="gap-3 py-6">
          <CardContent className="flex items-start gap-4">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-muted">
              <Video className="size-5 text-muted-foreground" />
            </div>
            <div className="min-w-0 flex-1 space-y-2">
              <div>
                <p className="font-medium">Record an online meeting</p>
                <p className="text-sm text-muted-foreground">
                  Zoom, Google Meet, Teams and others. Join the call as usual, then share its
                  browser tab with audio. Your microphone is added so your voice is included.
                  Nothing joins the call, and audio stays on this computer.
                </p>
              </div>
              <Button
                variant="outline"
                onClick={() => startRecording("meeting")}
                disabled={busy !== null}
              >
                <Video />
                Choose the meeting to record
              </Button>
              <p className="text-xs text-muted-foreground">
                Works in Chrome and Edge. Tell the other participants that you are recording.
              </p>
            </div>
          </CardContent>
        </Card>

        <Card
          className={cn(
            "cursor-pointer border-dashed py-8 text-center transition-colors",
            dragging && "border-brand bg-brand/5",
            focusUpload && "ring-2 ring-primary/40",
          )}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files[0]
            if (file) void upload(file)
          }}
        >
          <CardContent className="flex flex-col items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-full bg-muted">
              {busy === "upload" ? (
                <Loader2 className="size-5 animate-spin" />
              ) : dragging ? (
                <FileAudio className="size-5 text-brand" />
              ) : (
                <Upload className="size-5 text-muted-foreground" />
              )}
            </div>
            <div>
              <p className="font-medium">Upload a recording</p>
              <p className="text-sm text-muted-foreground">
                Drop an audio or video file here, or click to choose
              </p>
            </div>
            <input
              ref={fileRef}
              type="file"
              hidden
              accept="audio/*,video/*,.m4a,.wav,.mp3,.mp4"
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ""
                if (file) void upload(file)
              }}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
