"use client"

import { AudioLines, Bot, CheckCircle2, FolderOpen, TriangleAlert, Users } from "lucide-react"

import { PageHeader } from "@/components/common"
import { useInfo } from "@/components/providers"
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
          {!ok && (
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
        description="Everything runs locally. Run `dzomdu doctor` in a terminal for a full check."
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
              fix="brew services start ollama"
            />
          </div>
          <div className="grid gap-4 @4xl/main:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FolderOpen className="size-4" />
                  Vault
                </CardTitle>
                <CardDescription>Where meeting notes, people and projects are saved</CardDescription>
              </CardHeader>
              <CardContent>
                <code className="block truncate rounded-md bg-muted px-3 py-2 font-mono text-xs">
                  {info.vault}
                </code>
                <p className="mt-3 text-sm text-muted-foreground">
                  Open this folder in Obsidian with <em>Open folder as vault</em>. Change it with{" "}
                  <code className="font-mono text-xs">dzomdu init --vault …</code>.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Minutes formats</CardTitle>
                <CardDescription>
                  Add your own as Markdown files in <code className="font-mono text-xs">Templates/Minutes/</code>
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="divide-y text-sm">
                  {info.templates.map((t) => (
                    <li key={t.key} className="flex items-start justify-between gap-4 py-2.5 first:pt-0 last:pb-0">
                      <div>
                        <p className="font-medium">{t.name}</p>
                        <p className="text-muted-foreground">{t.description}</p>
                      </div>
                      {t.key === info.default_template && <Badge variant="secondary">Default</Badge>}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
