"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { AlertTriangle } from "lucide-react"
import { toast } from "sonner"

import { PageHeader } from "@/components/common"
import { useInfo } from "@/components/providers"
import { MeetingForm } from "@/components/record/meeting-form"
import { ProcessingView, RecordingView, ReviewView } from "@/components/record/session-views"
import { Button } from "@/components/ui/button"
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { api, type LiveSegment, type Session } from "@/lib/api"

const HEADINGS: Record<string, [string, string]> = {
  new: ["Recording", "Connecting to the microphone…"],
  recording: ["Recording", "Speak naturally; press Stop when the meeting ends."],
  processing: ["Processing", "Separating speakers and transcribing."],
  review: ["Who said what?", "Confirm each voice. Recognised people are filled in already."],
  summarizing: ["Writing notes", "Almost there."],
}

function SessionFlow({ id }: { id: string }) {
  const router = useRouter()
  const { reload: reloadInfo } = useInfo()
  const [session, setSession] = React.useState<Session>()
  const [live, setLive] = React.useState<LiveSegment[]>([])
  const [error, setError] = React.useState<string>()
  const since = React.useRef(0)

  React.useEffect(() => {
    let timer: number | undefined
    let stopped = false
    since.current = 0
    const poll = async () => {
      try {
        const s = await api<Session>(`/api/sessions/${id}?live_rev=${since.current}`)
        if (stopped) return
        since.current = s.live_rev
        if (s.live.length) {
          // a segment comes back with the same id as it improves (interim → final → labelled)
          setLive((prev) => {
            const byId = new Map(prev.map((seg) => [seg.id, seg]))
            for (const seg of s.live) byId.set(seg.id, seg)
            return [...byId.values()].filter((seg) => seg.text).sort((a, b) => a.id - b.id)
          })
        }
        setSession(s)
        if (s.state === "done" && s.meeting_id) {
          toast.success("Your notes are ready", { description: s.title })
          reloadInfo()
          router.replace(`/meetings/view/?id=${encodeURIComponent(s.meeting_id)}`)
          return
        }
        if (s.state === "cancelled") {
          router.replace("/record/")
          return
        }
        if (s.state !== "error") {
          // while recording, ask often: words should appear as they are spoken
          const wait = { new: 250, recording: 250, review: 2500 }[s.state as string] ?? 900
          timer = window.setTimeout(poll, wait)
        }
      } catch (e) {
        if (stopped) return
        setError(
          (e as { status?: number }).status === 404
            ? "This session no longer exists (the server was restarted). Finished meetings are under Meetings."
            : (e as Error).message,
        )
      }
    }
    void poll()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [id, router, reloadInfo])

  if (error || session?.state === "error") {
    return (
      <Card className="mx-auto w-full max-w-xl border-destructive/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="size-5 text-destructive" />
            Something went wrong
          </CardTitle>
          <CardDescription className="whitespace-pre-wrap break-words">
            {error ?? session?.error}
          </CardDescription>
        </CardHeader>
        <CardFooter className="gap-2">
          <Button asChild>
            <Link href="/record/">Back to start</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/settings/">Check system status</Link>
          </Button>
        </CardFooter>
      </Card>
    )
  }
  if (!session) return <Skeleton className="h-64 rounded-xl" />

  const [title, description] = HEADINGS[session.state] ?? ["Recording", ""]
  return (
    <>
      <PageHeader title={title} description={description} />
      {(session.state === "new" || session.state === "recording") && (
        <RecordingView session={session} live={live} />
      )}
      {(session.state === "processing" || session.state === "summarizing") && (
        <ProcessingView session={session} />
      )}
      {session.state === "review" && <ReviewView key={session.id} session={session} />}
    </>
  )
}

function RecordPageInner() {
  const session = useSearchParams().get("session")

  return session ? <SessionFlow id={session} /> : <NewMeeting />
}

function NewMeeting() {
  const params = useSearchParams()
  const router = useRouter()

  // load the speech models now, while the form is filled in, so the first words of the
  // recording are transcribed at once instead of waiting for a model to load
  React.useEffect(() => {
    api("/api/warmup", { method: "POST" }).catch(() => {})
  }, [])

  return (
    <>
      <PageHeader
        title="New meeting"
        description="Record live in the room, or upload a recording you already have."
      />
      <MeetingForm
        key={params.get("project") ?? "no-project"}
        initialProject={params.get("project") ?? ""}
        focusUpload={params.get("upload") === "1"}
        onSession={(id) => router.replace(`/record/?session=${encodeURIComponent(id)}`)}
      />
    </>
  )
}

export default function RecordPage() {
  return (
    <div className="@container/main flex flex-col gap-6">
      <React.Suspense fallback={<Skeleton className="h-96 rounded-xl" />}>
        <RecordPageInner />
      </React.Suspense>
    </div>
  )
}
