"use client"

import * as React from "react"
import { Tab, TabList } from "@astryxdesign/core/TabList"
import { AudioLines, Bot, Users } from "lucide-react"

import { PageHeader } from "@/components/common"
import { useInfo } from "@/components/providers"
import { FormatsCard, SummaryDefaultsCard } from "@/components/format-settings"
import { SettingsForms } from "@/components/settings-forms"
import { ModelSettings } from "@/components/model-settings"
import { NoiseSettingsCard } from "@/components/noise-settings"
import { Button } from "@/components/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/card"
import { Skeleton } from "@/components/ui/skeleton"

function StatusCard({
  icon: Icon,
  title,
  model,
  ok,
  detail,
  fix,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  model: string
  ok: boolean
  detail?: string
  fix: string
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
          <Icon className="size-4" />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <CardTitle>{title}</CardTitle>
          <CardDescription className="truncate font-mono text-xs">{model}</CardDescription>
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
          <span className={ok ? "size-1.5 rounded-full bg-success" : "size-1.5 rounded-full bg-warning"} aria-hidden />
          {ok ? "Ready" : "Needs attention"}
        </span>
      </CardHeader>
      {/* a healthy model needs no extra line; the detail only explains a problem */}
      {!ok && (
        <CardContent className="text-sm text-muted-foreground">
          {detail && <p>{detail}</p>}
          {!ok && fix && (
            <p className="mt-2">
              Fix: <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{fix}</code>
            </p>
          )}
        </CardContent>
      )}
    </Card>
  )
}

type Section = "status" | "models" | "summaries"

/** Settings follows the Astryx settings template: section tabs swap the pane instead of one long scroll. */
export default function SettingsPage() {
  const { info, reload } = useInfo()
  const [section, setSection] = React.useState<Section>("status")
  const attention = info
    ? [info.status.asr, info.status.diarization, info.status.llm].filter((s) => !s.ok).length
    : 0
  return (
    <div className="@container/main flex flex-col gap-6">
      <PageHeader
        title="Settings & status"
        description="Choose your meeting models, where notes are saved, and how summaries are written."
      >
        <Button variant="outline" onClick={reload}>
          Check again
        </Button>
      </PageHeader>
      {!info ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : (
        <>
          <TabList role="tablist" value={section} onChange={(value) => setSection(value as Section)} hasDivider>
            <Tab value="status" label="Status" panelId="settings-panel" endContent={attention ? <span className="size-1.5 rounded-full bg-warning" aria-label={`${attention} need attention`} /> : undefined} />
            <Tab value="models" label="Models & audio" panelId="settings-panel" />
            <Tab value="summaries" label="Summaries" panelId="settings-panel" />
          </TabList>
          <div id="settings-panel" role="tabpanel" className="flex flex-col gap-6">
            {section === "status" && (
              <div className="grid gap-4 @4xl/main:grid-cols-3">
                <StatusCard
                  icon={AudioLines}
                  title="Speech to text"
                  model={info.models.asr}
                  ok={info.status.asr.ok}
                  fix="pip install -e '.[mac]'"
                />
                <StatusCard
                  icon={Users}
                  title="Speaker recognition"
                  model={info.models.diarization}
                  ok={info.status.diarization.ok}
                  fix="pip install -e '.[diarize]'"
                />
                <StatusCard
                  icon={Bot}
                  title="Summaries (LLM)"
                  model={info.models.llm}
                  ok={info.status.llm.ok}
                  detail={info.status.llm.detail}
                  fix=""
                />
              </div>
            )}
            {section === "models" && (
              <>
                <ModelSettings />
                <NoiseSettingsCard />
              </>
            )}
            {section === "summaries" && (
              <>
                <SettingsForms>
                  <SummaryDefaultsCard />
                </SettingsForms>
                <FormatsCard />
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
