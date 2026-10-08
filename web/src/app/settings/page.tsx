"use client"

import { AudioLines, Bot, CheckCircle2, TriangleAlert, Users } from "lucide-react"

import { PageHeader } from "@/components/common"
import { useInfo } from "@/components/providers"
import { FormatsCard, SummaryDefaultsCard } from "@/components/format-settings"
import { SettingsForms } from "@/components/settings-forms"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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
        {ok ? (
          <Badge className="gap-1 bg-success/15 text-success">
            <CheckCircle2 />
            Ready
          </Badge>
        ) : (
          <Badge className="gap-1 bg-warning/15 text-warning">
            <TriangleAlert />
            Needs attention
          </Badge>
        )}
      </CardHeader>
      {(!ok || detail) && (
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

export default function SettingsPage() {
  const { info, reload } = useInfo()
  return (
    <div className="@container/main flex flex-col gap-6">
      <PageHeader
        title="Settings & status"
        description="Choose where the language model runs, where notes are saved, and how summaries are written."
      >
        <Button variant="outline" onClick={reload}>
          Check again
        </Button>
      </PageHeader>
      {!info ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : (
        <>
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
          <SettingsForms>
            <SummaryDefaultsCard />
          </SettingsForms>
          <FormatsCard />
        </>
      )}
    </div>
  )
}
