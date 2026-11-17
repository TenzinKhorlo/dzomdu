"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { Banner } from "@astryxdesign/core/Banner"
import { Button } from "@astryxdesign/core/Button"

import { useApi } from "@/hooks/use-api"
import { api } from "@/lib/api"
import { toast } from "@/lib/toast"

type Unprocessed = { name: string; seconds: number; modified: string }

/**
 * Recordings that were saved but never became a meeting: recovered after a crash, or cut short
 * when the connection dropped. Without this they sit on disk where nobody would look for them.
 */
export function RecoveredRecordings() {
  const router = useRouter()
  const { data } = useApi<Unprocessed[]>("/api/recordings/unprocessed")
  const [busy, setBusy] = React.useState<string | null>(null)

  async function process(name: string) {
    setBusy(name)
    try {
      const { id } = await api<{ id: string }>(
        `/api/recordings/unprocessed/${encodeURIComponent(name)}/process`,
        { method: "POST" },
      )
      router.push(`/record/?session=${encodeURIComponent(id)}`)
    } catch (e) {
      toast.error((e as Error).message)
      setBusy(null)
    }
  }

  if (!data?.length) return null
  return (
    <div className="flex flex-col gap-2">
      {data.map((recording) => {
        const when = new Date(recording.modified).toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        })
        const minutes = Math.max(1, Math.round(recording.seconds / 60))
        return (
          <Banner
            key={recording.name}
            status="warning"
            collapsible={false}
            title="Unprocessed recording found"
            description={`A recording from ${when} (${minutes} min) was saved but never turned into a meeting.`}
            endContent={
              <Button
                size="sm"
                label="Process it"
                onClick={() => process(recording.name)}
                isLoading={busy === recording.name}
                isDisabled={busy !== null}
              />
            }
          />
        )
      })}
    </div>
  )
}
