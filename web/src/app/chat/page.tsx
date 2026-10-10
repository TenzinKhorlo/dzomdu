"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowRight, ArrowUp, BookOpen, Gavel, ListChecks, Loader2, Sparkles } from "lucide-react"

import { Message } from "@/components/chat/message"
import { useChatHistory } from "@/components/chat/provider"
import { SourcesPicker } from "@/components/chat/sources-picker"
import { useInfo } from "@/components/providers"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useApi } from "@/hooks/use-api"
import { api, streamChatAnswer, type Chat, type MeetingRow } from "@/lib/api"

const SUGGESTIONS = [
  {
    title: "Catch me up",
    description: "A quick recap of recent discussions",
    icon: BookOpen,
    question: "Summarize the main topics from the most recent meetings in these notes.",
  },
  {
    title: "Find the decisions",
    description: "What we agreed on, and why",
    icon: Gavel,
    question: "What decisions were made in these meetings? Include their context.",
  },
  {
    title: "What's next?",
    description: "Action items, owners and deadlines",
    icon: ListChecks,
    question:
      "What are the outstanding action items in these notes? Include owners and deadlines where recorded.",
  },
]

function ChatWorkspace({ id, meeting }: { id: string | null; meeting: string | null }) {
  const router = useRouter()
  const { info } = useInfo()
  const { reload: reloadHistory } = useChatHistory()
  const library = useApi<{ meetings: MeetingRow[] }>("/api/meetings")
  const meetings = library.data?.meetings ?? []
  const [chat, setChat] = React.useState<Chat>()
  const [selected, setSelected] = React.useState<string[]>(meeting ? [meeting] : [])
  const [draft, setDraft] = React.useState("")
  const [pending, setPending] = React.useState("")
  const [streaming, setStreaming] = React.useState<{ content: string; html: string }>()
  const [loading, setLoading] = React.useState(!!id)
  const [error, setError] = React.useState("")
  const textarea = React.useRef<HTMLTextAreaElement>(null)
  const end = React.useRef<HTMLDivElement>(null)
  const following = React.useRef(true)
  const request = React.useRef<AbortController | null>(null)
  const busy = !!pending
  const messages = chat?.messages ?? []
  const started = messages.length > 0 || busy
  const scope = chat?.meeting_ids ?? selected

  React.useEffect(() => {
    if (!id) return
    const controller = new AbortController()
    api<Chat>(`/api/chats/${encodeURIComponent(id)}`, { signal: controller.signal })
      .then((data) => {
        setChat(data)
        setLoading(false)
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) {
          setError(err.message)
          setLoading(false)
        }
      })
    return () => controller.abort()
  }, [id])
  React.useEffect(() => () => request.current?.abort(), [])
  React.useEffect(() => {
    const track = () => {
      following.current =
        document.documentElement.scrollHeight - window.scrollY - window.innerHeight < 220
    }
    window.addEventListener("scroll", track, { passive: true })
    return () => window.removeEventListener("scroll", track)
  }, [])
  React.useEffect(() => {
    if (streaming && following.current) end.current?.scrollIntoView({ block: "end" })
  }, [streaming])
  React.useEffect(() => {
    if (started) end.current?.scrollIntoView({ block: "end" })
    if (started && !busy) textarea.current?.focus()
  }, [messages.length, busy, started])

  async function send(question = draft) {
    question = question.trim()
    if (!question || request.current || busy || loading || question.length > 4000) return
    const controller = new AbortController()
    request.current = controller
    following.current = true
    setPending(question)
    setStreaming(undefined)
    setDraft("")
    if (textarea.current) textarea.current.style.height = "auto"
    setError("")
    try {
      const current =
        chat ??
        (await api<Chat>("/api/chats", {
          method: "POST",
          json: { meeting_ids: selected },
          signal: controller.signal,
        }))
      setChat(current)
      const updated = await streamChatAnswer(current.id, question, controller.signal, setStreaming)
      setChat(updated)
      reloadHistory()
      if (id !== current.id) router.replace(`/chat/?id=${current.id}`)
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "Could not get an answer. Please try again.")
        setDraft(question)
      }
    } finally {
      request.current = null
      if (!controller.signal.aborted) {
        setPending("")
        setStreaming(undefined)
        textarea.current?.focus()
      }
    }
  }

  const composer = (
    <div className="space-y-2">
      {error && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2.5 text-[13px] text-destructive"
        >
          {error}
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
        className="rounded-xl border bg-card p-3 shadow-[0_2px_8px_rgb(0_0_0/0.025)] transition-shadow focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/10 sm:p-4"
      >
        <label htmlFor="chat-question" className="sr-only">
          Ask a question about your meeting notes
        </label>
        <textarea
          id="chat-question"
          ref={textarea}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
            e.target.style.height = "auto"
            e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void send()
            }
          }}
          disabled={busy || loading || (!!id && !chat)}
          maxLength={4000}
          rows={2}
          placeholder={started ? "Ask a follow-up question…" : "Ask anything about your meetings…"}
          className="block max-h-44 min-h-16 w-full resize-none bg-transparent px-1 py-1 text-[14px] leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-60"
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <SourcesPicker
            meetings={meetings}
            selected={scope}
            onChange={setSelected}
            locked={!!chat}
            disabled={busy || loading || library.loading || !!library.error}
          />
          <div className="flex shrink-0 items-center gap-3">
            <span
              className="hidden max-w-40 truncate text-[11px] text-muted-foreground sm:block"
              title={info?.models.llm}
            >
              {info?.models.llm ?? "Configured model"}
            </span>
            <Button
              type="submit"
              size="icon"
              className="size-8"
              aria-label="Send question"
              disabled={!draft.trim() || busy || loading || (!!id && !chat)}
            >
              {busy ? <Loader2 className="animate-spin" /> : <ArrowUp />}
            </Button>
          </div>
        </div>
      </form>
      <p className="text-center text-[11px] leading-5 text-muted-foreground">
        Answers use your meeting notes. Check the sources for details.
      </p>
    </div>
  )

  return (
    <div className="flex min-h-[calc(100svh-104px)] flex-col gap-6">
      <div className="flex min-h-0 flex-1">
        <section className="mx-auto flex min-w-0 flex-1 flex-col" aria-label="Meeting notes chat">
          {loading ? (
            <div className="mx-auto w-full max-w-3xl space-y-5 py-10">
              <Skeleton className="ml-auto h-16 w-2/3" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : started ? (
            <>
              <div
                role="log"
                aria-label="Conversation"
                aria-live="polite"
                aria-busy={busy}
                className="mx-auto w-full max-w-3xl space-y-8 pb-8 pt-2"
              >
                {messages.map((message) => (
                  <Message key={message.id} message={message} />
                ))}
                {busy && (
                  <>
                    <div className="flex justify-end">
                      <div className="max-w-[90%] rounded-xl border bg-muted/65 px-4 py-3 text-[14px] leading-6 whitespace-pre-wrap">
                        <span className="sr-only">You: </span>
                        {pending}
                      </div>
                    </div>
                    {streaming ? (
                      <Message
                        streaming
                        message={{
                          id: "streaming",
                          role: "assistant",
                          ...streaming,
                          sources: [],
                          coverage: {},
                          created_at: "",
                        }}
                      />
                    ) : (
                      <div
                        role="status"
                        className="flex items-center gap-2.5 text-[13px] text-muted-foreground"
                      >
                        <Sparkles className="size-4 text-brand" />
                        <Loader2 className="size-3.5 animate-spin" />
                        Reading your meeting notes…
                      </div>
                    )}
                  </>
                )}
              </div>
              <div className="sticky bottom-0 mx-auto mt-auto w-full max-w-3xl bg-background pb-3 pt-4">
                {composer}
              </div>
              <div ref={end} />
            </>
          ) : (
            <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center pb-12 pt-8 sm:pb-24">
              <div className="mb-7 space-y-4 text-center">
                <span className="mx-auto flex size-11 items-center justify-center rounded-xl border border-brand/15 bg-brand/8 text-brand">
                  <Sparkles className="size-5" />
                </span>
                <div className="space-y-2">
                  <h2 className="text-[25px] leading-tight font-semibold tracking-[-0.025em] sm:text-[30px]">
                    Your meetings,
                    <br className="sm:hidden" /> a conversation away.
                  </h2>
                  <p className="mx-auto max-w-md text-[13px] leading-6 text-muted-foreground">
                    Start with a question. We’ll find the notes.
                  </p>
                </div>
              </div>
              {composer}
              <div className="mt-6 grid gap-2.5 sm:grid-cols-3">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion.title}
                    type="button"
                    disabled={busy || loading || (!!id && !chat) || !meetings.length}
                    onClick={() => void send(suggestion.question)}
                    className="group flex items-start gap-3 rounded-xl border bg-card px-4 py-3.5 text-left transition-colors hover:border-brand/35 hover:bg-brand/[0.025] disabled:opacity-50 sm:block sm:py-4"
                  >
                    <suggestion.icon className="mt-0.5 size-4 shrink-0 text-brand/80 sm:mt-0 sm:mb-3" />
                    <span className="block flex-1">
                      <span className="flex items-center justify-between text-[13px] font-medium">
                        {suggestion.title}
                        <ArrowRight className="size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                      </span>
                      <span className="mt-1.5 block text-xs leading-5 text-muted-foreground">
                        {suggestion.description}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
              {library.error ? (
                <p role="alert" className="mt-5 text-center text-xs text-destructive">
                  Could not load meeting notes.{" "}
                  <button className="underline" onClick={library.reload}>
                    Retry
                  </button>
                </p>
              ) : !library.loading && !meetings.length ? (
                <p className="mt-5 text-center text-xs text-muted-foreground">
                  Your library is empty.{" "}
                  <Link href="/record/" className="text-brand underline underline-offset-4">
                    Record or upload a meeting
                  </Link>{" "}
                  to get started.
                </p>
              ) : null}
              {info && !info.status.llm.ok && (
                <p className="mt-4 text-center text-xs text-muted-foreground">
                  Your model is unavailable.{" "}
                  <Link href="/settings/" className="text-brand underline underline-offset-4">
                    Check model settings
                  </Link>{" "}
                  before asking.
                </p>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function ChatRoute() {
  const params = useSearchParams()
  const id = params.get("id")
  const meeting = params.get("meeting")
  const { newChatRevision } = useChatHistory()
  return (
    <ChatWorkspace
      key={`${id ?? "new"}:${meeting ?? "all"}:${newChatRevision}`}
      id={id}
      meeting={meeting}
    />
  )
}

export default function ChatPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <ChatRoute />
    </React.Suspense>
  )
}
