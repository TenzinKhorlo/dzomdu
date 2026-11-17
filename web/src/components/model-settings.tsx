"use client"

import * as React from "react"
import { Check, Download, Loader2, Monitor, Users } from "lucide-react"
import { toast } from "@/lib/toast"

import { useInfo } from "@/components/providers"
import { Badge } from "@/components/badge"
import { Button } from "@/components/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Selector } from "@astryxdesign/core/Selector"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import { api } from "@/lib/api"

type Model = {
  id: string; name: string; kind: "asr" | "diarization" | "alignment"
  description: string; repo: string; size_gb: number; languages: string[]
  speaker_limit: number | null; compatible: boolean; compatibility_detail: string | null
  runtime_installed: boolean; install_command: string; downloaded: boolean; ready: boolean
  state: string; progress: number; detail: string; default: boolean
}
type ModelDefaults = {
  asr_id: string | null; diarization_id: string | null; language: string
  max_speakers: number | null; asr_model: string; diarization_model: string
}
type Library = { models: Model[]; settings: ModelDefaults }

function DefaultsForm({ models, saved, onSaved }: {
  models: Model[]; saved: ModelDefaults; onSaved: () => void
}) {
  const [asr, setAsr] = React.useState(saved.asr_id ?? "")
  const [diar, setDiar] = React.useState(saved.diarization_id ?? "")
  const [language, setLanguage] = React.useState(saved.language)
  const [limit, setLimit] = React.useState(saved.max_speakers?.toString() ?? "")
  const [busy, setBusy] = React.useState(false)
  const speech = models.find((m) => m.id === asr)
  const speakers = models.find((m) => m.id === diar)
  const limited = speakers?.speaker_limit != null
  const invalidLimit = limit !== "" && (!Number.isInteger(Number(limit)) || Number(limit) < 1 ||
    Number(limit) > (speakers?.speaker_limit ?? 100))
  const changed = asr !== saved.asr_id || diar !== saved.diarization_id ||
    language !== saved.language || limit !== (saved.max_speakers?.toString() ?? "")

  async function save() {
    setBusy(true)
    try {
      await api("/api/settings/models", { method: "PUT", json: {
        asr_id: asr, diarization_id: diar, language,
        max_speakers: limit ? Number(limit) : (speakers?.speaker_limit ?? null),
      } })
      toast.success("Default meeting models saved")
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally { setBusy(false) }
  }

  function chooser(kind: Model["kind"], label: string, value: string, change: (id: string) => void) {
    return (
      <Selector
        label={label}
        placeholder="Choose a downloaded model"
        value={value}
        onChange={(id) => id && change(id)}
        options={models
          .filter((m) => m.kind === kind)
          .map((m) => ({
            value: m.id,
            label: `${m.name}${!m.ready ? ` · ${!m.compatible ? "unavailable here" : !m.runtime_installed ? "setup needed" : "download first"}` : ""}`,
            disabled: !m.ready,
          }))}
      />
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Default meeting models</CardTitle>
        <CardDescription>Try different models, then keep the ones that work best for your meetings.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-1.5">
            {chooser("asr", "Transcription", asr, (id) => {
              setAsr(id)
              const m = models.find((m) => m.id === id)
              if (m && !m.languages.includes(language)) setLanguage("en")
            })}
            {!saved.asr_id && <p className="text-xs text-muted-foreground">Current: {saved.asr_model}</p>}
          </div>
          <div className="grid gap-1.5">
            {chooser("diarization", "Speaker separation", diar, (id) => {
              setDiar(id)
              const maximum = models.find((m) => m.id === id)?.speaker_limit
              if (maximum != null && (!limit || !Number.isInteger(Number(limit)) ||
                Number(limit) < 1 || Number(limit) > maximum)) setLimit(String(maximum))
            })}
            {!saved.diarization_id && <p className="text-xs text-muted-foreground">Current: {saved.diarization_model}</p>}
          </div>
          <div className="grid gap-1.5">
            <Selector
              label="Meeting language"
              value={language}
              onChange={(value) => value && setLanguage(value)}
              options={[
                { value: "en", label: "English" },
                { value: "ne", label: "Nepali", disabled: !speech?.languages.includes("ne") },
                { value: "auto", label: "Detect language automatically", disabled: !speech?.languages.includes("auto") },
              ]}
            />
            <p className="text-xs text-muted-foreground">Use Whisper for Nepali. Test mixed English and Nepali recordings before choosing a default.</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="speaker-limit">Maximum speakers{!limited && " (optional)"}</Label>
            <Input id="speaker-limit" type="number" min={1} max={limited ? speakers.speaker_limit! : 100}
              value={limit} onChange={(e) => setLimit(e.target.value)}
              placeholder={limited ? `Up to ${speakers.speaker_limit} speakers` : "Detect automatically"}
              aria-invalid={invalidLimit} aria-describedby="speaker-limit-help" />
            <p id="speaker-limit-help" className="text-xs text-muted-foreground">
              {limited ? `Leave blank to detect up to ${speakers.speaker_limit} speakers, or set a lower maximum.` :
                "Pyannote supports 15+ speakers through clustering. Leave blank for automatic detection."}
            </p>
            {invalidLimit && <p role="alert" className="text-xs text-destructive">
              Enter a whole number from 1 to {speakers?.speaker_limit ?? 100}.
            </p>}
          </div>
        </div>
        {limited && (
          <p role="status" className="rounded-lg bg-warning-subtle p-3 text-sm text-warning">
            Nemotron supports up to eight speakers. This limit is applied automatically.
            For larger meetings, choose Pyannote.
          </p>
        )}
        <p className="text-xs text-muted-foreground">Changes apply to new meetings. Saved voice profiles are kept when switching speaker models.
          Live preview currently processes utterance chunks; selecting a streaming model does not change that preview method.</p>
        <div><Button onClick={save} disabled={busy || !changed || !speech?.ready || !speakers?.ready || invalidLimit}>
          {busy && <Loader2 className="animate-spin" />}Save defaults
        </Button></div>
      </CardContent>
    </Card>
  )
}

export function ModelSettings() {
  const { data, error, reload } = useApi<Library>("/api/models", { interval: 2000 })
  const { reload: reloadInfo } = useInfo()
  const [requesting, setRequesting] = React.useState<string | null>(null)
  const [downloadError, setDownloadError] = React.useState<string | null>(null)

  async function download(ids: string[], label: string) {
    setRequesting(label)
    setDownloadError(null)
    try {
      await api("/api/models/download", { method: "POST", json: { model_ids: ids } })
      toast.success(ids.length === 1 ? "Model download queued" : "Model downloads queued")
      reload()
    } catch (e) {
      setDownloadError((e as Error).message)
    } finally { setRequesting(null) }
  }

  if (error && !data) return <Card><CardContent className="space-y-3 pt-6">
    <p className="text-sm text-muted-foreground">Could not load the model library: {error.message}</p>
    <Button variant="outline" onClick={reload}>Try again</Button>
  </CardContent></Card>
  if (!data) return <Skeleton className="h-72 rounded-xl" />
  const pending = data.models.filter((m) => m.compatible && !m.downloaded &&
    m.state !== "queued" && m.state !== "downloading" && (!["asr", "diarization"].includes(m.kind) ||
      m.runtime_installed || !(m.id.startsWith("moonshine") || m.id === "whistle" || m.id === "who")))

  return (
    <div className="grid gap-4">
      <DefaultsForm key={JSON.stringify(data.settings)} saved={data.settings} models={data.models}
        onSaved={() => { reload(); reloadInfo() }} />
      <Card>
        <CardHeader className="flex flex-wrap items-start justify-between gap-3 sm:flex-row">
          <div className="space-y-1.5">
            <CardTitle>Model library</CardTitle>
            <CardDescription>Download once, test locally. Downloads keep your current defaults.</CardDescription>
          </div>
          <Button variant="outline" disabled={!!requesting || !pending.length}
            onClick={() => download(pending.map((m) => m.id), "all")}>
            {requesting === "all" ? <Loader2 className="animate-spin" /> : <Download />}
            Download all available
          </Button>
        </CardHeader>
        <CardContent className="grid gap-5">
          <p className="text-xs text-muted-foreground">Sizes are approximate weight storage, not memory requirements.
            Downloads run one at a time and can be resumed after an error. Qwen also needs the shared word aligner.
            Missing runtimes show a setup command below.</p>
          {downloadError && <p role="alert" className="text-sm text-destructive">{downloadError}</p>}
          {(["asr", "diarization", "alignment"] as const).map((kind) => (
            <div key={kind} className="grid gap-2">
              <h3 className="text-[13px] font-medium">{kind === "asr" ? "Transcription" :
                kind === "diarization" ? "Speaker separation" : "Word timestamps"}</h3>
              <div className="grid gap-3 @4xl/main:grid-cols-2">
                {data.models.filter((m) => m.kind === kind).map((m) => {
                  const active = m.state === "queued" || m.state === "downloading"
                  return (
                    <div key={m.id} className="grid content-start gap-3 rounded-lg border p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <p className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
                            {m.name}{m.default && <Badge variant="secondary">Default</Badge>}
                          </p>
                          <p className="text-xs leading-relaxed text-muted-foreground">{m.description}</p>
                        </div>
                        {kind === "diarization" ? <Users className="size-4 shrink-0 text-muted-foreground" /> :
                          <Monitor className="size-4 shrink-0 text-muted-foreground" />}
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs text-muted-foreground">~{m.size_gb} GB</span>
                        {m.downloaded && !active ? <span className="flex items-center gap-1 text-xs text-success">
                          <Check className="size-3.5" />{m.ready ? "Ready" : "Downloaded"}
                        </span> : <Button size="sm" variant="outline" disabled={!!requesting || active || !m.compatible ||
                          ((m.id.startsWith("moonshine") || m.id === "whistle" || m.id === "who") && !m.runtime_installed)}
                          onClick={() => download([m.id], m.id)}>
                          {active ? <Loader2 className="animate-spin" /> : <Download />}
                          {active ? m.state === "queued" ? "Queued" : "Downloading" : m.state === "error" ? "Retry" : "Download"}
                        </Button>}
                      </div>
                      {active && <div role="status" className="space-y-1.5">
                        <progress aria-label={`${m.name} download`} className="h-1.5 w-full accent-primary"
                          max={1} value={m.progress} />
                        <p className="truncate text-xs text-muted-foreground">{m.detail}</p>
                      </div>}
                      {m.state === "error" && <p role="alert" className="break-words text-xs text-destructive">{m.detail}</p>}
                      {!m.compatible ? <p className="text-xs text-muted-foreground">{m.compatibility_detail}</p> :
                        !m.runtime_installed && <div className="space-y-1 text-xs text-muted-foreground">
                          <p>Install the runtime in your Dzomdu environment, then restart the server:</p>
                          <code className="block overflow-x-auto rounded bg-muted p-2">{m.install_command}</code>
                        </div>}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
