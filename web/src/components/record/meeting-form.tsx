"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { Collapsible } from "@astryxdesign/core/Collapsible"
import { Heading } from "@astryxdesign/core/Heading"
import { Icon } from "@astryxdesign/core/Icon"
import { IconButton } from "@astryxdesign/core/IconButton"
import { NumberInput } from "@astryxdesign/core/NumberInput"
import { Selector } from "@astryxdesign/core/Selector"
import { Switch } from "@astryxdesign/core/Switch"
import { Text } from "@astryxdesign/core/Text"
import { TextArea } from "@astryxdesign/core/TextArea"
import { TextInput } from "@astryxdesign/core/TextInput"
import { Tokenizer } from "@astryxdesign/core/Tokenizer"
import { createStaticSource } from "@astryxdesign/core/Typeahead"
import { FileAudio, FolderPlus, Loader2, Mic, Upload, Video } from "lucide-react"
import { toast } from "@/lib/toast"

import { NewProjectDialog } from "@/components/new-project-dialog"
import { useInfo } from "@/components/providers"
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

const NO_PROJECT = "__none__"

export function MeetingForm({
  initialProject = "",
  onSession,
  focusUpload = false,
}: {
  initialProject?: string
  onSession: (id: string) => void
  focusUpload?: boolean
}) {
  const { info } = useInfo()
  const [meta, setMeta] = React.useState<Meta>({
    title: "",
    project: initialProject,
    attendees: [],
    template: "",
    num_speakers: "",
    live: true,
    summarize: true,
    instructions: "",
  })
  const [busy, setBusy] = React.useState<"record" | "upload" | null>(null)
  const [dragging, setDragging] = React.useState(false)
  const [includeMicrophone, setIncludeMicrophone] = React.useState(false)
  const [reduceBackgroundNoise, setReduceBackgroundNoise] = React.useState(true)
  const fileRef = React.useRef<HTMLInputElement>(null)
  const set = <K extends keyof Meta>(k: K, v: Meta[K]) => setMeta((m) => ({ ...m, [k]: v }))
  const template = meta.template || info?.default_template || "standard"

  const payload = () => ({
    ...meta,
    title: meta.title.slice(0, 120),
    template,
    num_speakers: meta.num_speakers ? Number(meta.num_speakers) : null,
  })

  async function startRecording(source: RecordingSource = "room") {
    setBusy("record")
    let id: string | null = null
    try {
      id = (await api<{ id: string }>("/api/sessions", { method: "POST", json: payload() })).id
      await recorder.start(id, source, { includeMicrophone, reduceBackgroundNoise })
      onSession(id)
    } catch (e) {
      // recorder.start releases whatever it opened when it fails. Releasing here as well would
      // end a recording already running in this tab when the server answers "already in progress".
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

  // attendees: type to filter the people Dzomdu already knows, or add a new name
  const peopleSource = React.useMemo(
    () => createStaticSource((info?.people ?? []).map((name) => ({ id: name, label: name }))),
    [info?.people],
  )
  const projects = [...new Set([...(info?.projects ?? []), ...(meta.project ? [meta.project] : [])])]

  return (
    <div className="grid gap-6 @5xl/main:grid-cols-5">
      {/* self-start: the form is as tall as its fields, not stretched to the column beside it */}
      <div className="self-start rounded-[var(--radius-container)] border bg-card p-5 @5xl/main:col-span-3">
        <div className="mb-5">
          <Heading level={3}>Meeting details</Heading>
          <Text type="supporting">
            All optional. Attendees narrow voice matching to those people, which makes recognition
            more accurate.
          </Text>
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <TextInput
              label="Title"
              placeholder="Suggested from the notes if left empty"
              value={meta.title}
              onChange={(v) => set("title", v)}
            />
          </div>
          <div className="flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <Selector
                label="Project"
                hasSearch={projects.length > 6}
                value={meta.project || NO_PROJECT}
                onChange={(v) => set("project", !v || v === NO_PROJECT ? "" : v)}
                options={[{ value: NO_PROJECT, label: "No project" }, ...projects.map((p) => ({ value: p, label: p }))]}
              />
            </div>
            <NewProjectDialog onCreated={(name) => set("project", name)}>
              <IconButton label="New project" tooltip="New project" icon={<Icon icon={FolderPlus} />} />
            </NewProjectDialog>
          </div>
          <Selector
            label="Minutes format"
            value={template}
            onChange={(v) => v && set("template", v)}
            options={(info?.templates ?? []).map((t) => ({ value: t.key, label: t.name }))}
          />
          <div className="sm:col-span-2">
            <Tokenizer
              label="Attendees"
              placeholder="Type a name and press Enter"
              hasCreate
              hasEntriesOnFocus
              searchSource={peopleSource}
              value={meta.attendees.map((name) => ({ id: name, label: name }))}
              onChange={(items) => set("attendees", items.map((item) => item.label))}
            />
          </div>
          <div className="sm:col-span-2">
            <Collapsible
              defaultIsOpen={false}
              trigger={<Text type="label">More options</Text>}
            >
              <div className="grid gap-5 pt-4 sm:grid-cols-2">
            <NumberInput
              label="Number of speakers"
              placeholder="Detect automatically"
              min={1}
              max={100}
              value={meta.num_speakers ? Number(meta.num_speakers) : null}
              onChange={(v) => set("num_speakers", Number.isFinite(v) ? String(v) : "")}
            />
            <div className="flex flex-wrap gap-x-8 gap-y-3 sm:col-span-2">
              <Switch label="Live transcript" value={meta.live} onChange={(v) => set("live", v)} />
              <Switch label="Write summary & minutes" value={meta.summarize} onChange={(v) => set("summarize", v)} />
            </div>
            <div className="sm:col-span-2">
              <TextArea
                label="Extra instructions for the summary"
                rows={2}
                placeholder="e.g. Keep it short, bullet points for the director"
                value={meta.instructions}
                onChange={(v) => set("instructions", v)}
              />
            </div>
              </div>
            </Collapsible>
          </div>
        </div>
      </div>

      {/* stacked (narrow screens): the way to start comes first, the optional details after it */}
      <div className="order-first flex flex-col gap-6 @5xl/main:order-none @5xl/main:col-span-2">
        <div className="flex flex-col items-center gap-5 rounded-[var(--radius-container)] border bg-card p-5 text-center">
          <button
            type="button"
            onClick={() => startRecording("room")}
            disabled={busy !== null}
            className="flex size-28 items-center justify-center rounded-full bg-recording text-white ring-1 ring-black/10 transition-[transform,opacity] duration-150 ease-out active:scale-95 disabled:opacity-60"
            aria-label="Start recording"
          >
            {busy === "record" ? <Loader2 className="size-9 animate-spin" /> : <Mic className="size-10" />}
          </button>
          <div className="space-y-1">
            <Heading level={3}>Start recording</Heading>
            <Text type="supporting">
              Place the laptop or speakerphone in the middle of the table. Audio never leaves this
              computer.
            </Text>
          </div>
        </div>

        <div className="flex flex-col gap-4 rounded-[var(--radius-container)] border bg-card p-5">
          <div className="space-y-1">
            <Heading level={3}>Record an online meeting</Heading>
            <Text type="supporting">
              Join the call as usual, then share its browser tab with audio. Nothing joins the call.
            </Text>
          </div>
          <Switch
            label="Include my microphone"
            description={
              includeMicrophone
                ? "Adds your voice and nearby sounds to the meeting audio."
                : "Records only shared meeting audio. Your own voice may be missing."
            }
            value={includeMicrophone}
            onChange={setIncludeMicrophone}
            isDisabled={busy !== null}
          />
          {includeMicrophone && (
            <Switch
              label="Reduce microphone background noise"
              description={
                reduceBackgroundNoise
                  ? "Uses browser noise reduction to keep speech clearer. Some nearby sounds may remain."
                  : "Keeps nearby sounds picked up by your microphone."
              }
              value={reduceBackgroundNoise}
              onChange={setReduceBackgroundNoise}
              isDisabled={busy !== null}
            />
          )}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Button
              label="Choose the meeting to record"
              icon={<Icon icon={Video} />}
              onClick={() => startRecording("meeting")}
              isDisabled={busy !== null}
            />
            <Text type="supporting" size="xsm">
              Works in Chrome and Edge
            </Text>
          </div>
        </div>

        <div
          role="button"
          tabIndex={0}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-3 rounded-[var(--radius-container)] border border-dashed bg-card p-5 text-center transition-colors hover:bg-muted/50",
            dragging && "border-brand bg-brand/5",
            focusUpload && "ring-2 ring-primary/40",
          )}
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault()
              fileRef.current?.click()
            }
          }}
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
          <Icon
            icon={busy === "upload" ? Loader2 : dragging ? FileAudio : Upload}
            size="lg"
            color="secondary"
            className={cn(busy === "upload" && "animate-spin")}
          />
          <div>
            <Text weight="medium" display="block">
              Upload a recording
            </Text>
            <Text type="supporting">Drop an audio or video file here, or click to choose</Text>
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
        </div>
      </div>
    </div>
  )
}
