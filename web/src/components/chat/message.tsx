"use client"

import Link from "next/link"
import { ArrowUpRight, BookOpen, Copy, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import type { ChatMessage } from "@/lib/api"
import { shortDate } from "@/lib/format"

export function Message({
  message,
  streaming = false,
}: {
  message: ChatMessage
  streaming?: boolean
}) {
  if (message.role === "user")
    return (
      <div className="flex justify-end">
        <div className="max-w-[90%] rounded-xl border bg-muted/65 px-4 py-3 text-[14px] leading-6 whitespace-pre-wrap sm:max-w-[80%]">
          <span className="sr-only">You: </span>
          {message.content}
        </div>
      </div>
    )
  return (
    <article className="space-y-4">
      <div className="flex items-center gap-2 text-xs font-medium">
        <span className="flex size-6 items-center justify-center rounded-lg bg-brand/10 text-brand">
          <Sparkles className="size-3.5" />
        </span>
        Dzomdu
      </div>
      <div
        className="chat-answer text-[14px] leading-7"
        dangerouslySetInnerHTML={{ __html: message.html ?? "" }}
      />
      {message.sources.length > 0 && (
        <div className="space-y-2.5">
          <p className="text-[11px] font-medium text-muted-foreground">
            Sources · {message.sources.length}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {message.sources.map((source) => (
              <Link
                key={source.number}
                href={`/meetings/view/?id=${encodeURIComponent(source.meeting_id)}`}
                className="group min-w-0 rounded-xl border bg-card px-3.5 py-3 transition-colors hover:border-brand/40 hover:bg-brand/[0.025]"
                aria-label={`Source ${source.number}: ${source.title}. Open meeting notes.`}
              >
                <div className="mb-2 flex items-center gap-2 text-[11px] text-muted-foreground">
                  <BookOpen className="size-3.5" />
                  <span>{shortDate(source.date)}</span>
                  <span className="ml-auto font-mono">[{source.number}]</span>
                </div>
                <div className="flex items-start gap-2">
                  <p className="line-clamp-1 flex-1 text-[13px] font-medium">{source.title}</p>
                  <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground group-hover:text-brand" />
                </div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                  {source.excerpt.replace(/[#*\[\]]/g, "")}
                </p>
              </Link>
            ))}
          </div>
        </div>
      )}
      {streaming ? (
        <p role="status" className="text-xs text-muted-foreground">
          Writing…
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label="Copy answer"
            onClick={() =>
              navigator.clipboard
                .writeText(message.content)
                .then(() => toast.success("Answer copied"))
                .catch(() => toast.error("Copy failed"))
            }
          >
            <Copy className="size-3.5" />
          </Button>
          {!!message.coverage.included_meetings && (
            <span>
              Read excerpts from {message.coverage.included_meetings} meeting
              {message.coverage.included_meetings === 1 ? "" : "s"}
              {message.coverage.partial ? " · selected excerpts" : ""}
            </span>
          )}
        </div>
      )}
    </article>
  )
}
