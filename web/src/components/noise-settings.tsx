"use client"

import * as React from "react"
import { Loader2, Volume2 } from "lucide-react"
import { toast } from "@/lib/toast"

import { Badge } from "@/components/badge"
import { Button } from "@/components/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/card"
import { Selector } from "@astryxdesign/core/Selector"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@astryxdesign/core/Switch"
import { useApi } from "@/hooks/use-api"
import { api } from "@/lib/api"

type NoiseSettings = {
  enabled: boolean
  strength: number
  runtime_installed: boolean
  install_command: string
}

function NoiseForm({ saved, onSaved }: { saved: NoiseSettings; onSaved: () => void }) {
  const [enabled, setEnabled] = React.useState(saved.enabled)
  const [strength, setStrength] = React.useState(saved.strength.toString())
  const [busy, setBusy] = React.useState(false)
  const changed = enabled !== saved.enabled || Number(strength) !== saved.strength

  async function save() {
    setBusy(true)
    try {
      await api("/api/settings/noise", {
        method: "PUT", json: { enabled, strength: Number(strength) },
      })
      toast.success("Audio processing settings saved")
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <CardContent className="grid gap-4">
      <Switch
        label="Reduce background noise"
        description="Apply to live transcripts and uploaded recordings."
        value={enabled}
        onChange={setEnabled}
        isDisabled={!saved.runtime_installed && !enabled}
      />
      <div className="max-w-sm">
        <Selector
          label="Suppression level"
          value={strength}
          onChange={(value) => value && setStrength(value)}
          isDisabled={!enabled}
          options={[
            ...([0.5, 0.75].includes(saved.strength)
              ? []
              : [{ value: saved.strength.toString(), label: `Custom · ${Math.round(saved.strength * 100)}%` }]),
            { value: "0.5", label: "Light · recommended for meetings" },
            { value: "0.75", label: "Balanced · more noise reduction" },
          ]}
        />
      </div>
      <p className="text-sm text-muted-foreground">
        Reduces background noise and may reduce music. No speaker is selected or intentionally muted.
        Quiet and overlapping voices can still be affected, so the original recording is kept for
        speaker detection and recognition.
      </p>
      <p className="text-xs text-muted-foreground">
        Runs locally with RNNoise. BSD-3-Clause model and Apache-2.0 wrapper permit commercial use.
        Expected extra live delay: tens of milliseconds; actual performance depends on your computer.
      </p>
      {!saved.runtime_installed && (
        <div className="rounded-lg border bg-muted/40 p-3 text-sm">
          <p className="mb-2">Install the noise suppression package, then restart Dzomdu. The model is included.</p>
          <code className="break-all text-xs">{saved.install_command}</code>
        </div>
      )}
      <div className="flex justify-end">
        <Button onClick={save} disabled={busy || !changed || (enabled && !saved.runtime_installed)}>
          {busy && <Loader2 className="animate-spin" />}Save audio settings
        </Button>
      </div>
    </CardContent>
  )
}

export function NoiseSettingsCard() {
  const { data, error, reload } = useApi<NoiseSettings>("/api/settings/noise")
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Volume2 className="size-4 text-muted-foreground" />
          <CardTitle>Audio processing</CardTitle>
          {data && <Badge variant="secondary">{data.enabled ? "Enabled" : "Off"}</Badge>}
        </div>
        <CardDescription>Clearer speech, with every participant in mind.</CardDescription>
      </CardHeader>
      {error ? (
        <CardContent className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">Could not load audio settings. Restart the backend after updating.</p>
          <Button variant="outline" onClick={reload}>Retry</Button>
        </CardContent>
      ) : data ? (
        <NoiseForm key={`${data.enabled}-${data.strength}`} saved={data} onSaved={reload} />
      ) : <CardContent><Skeleton className="h-36" /></CardContent>}
    </Card>
  )
}
