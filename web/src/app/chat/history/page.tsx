"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowUpRight, MessageSquare, Pin, Search } from "lucide-react"

import { useChatHistory } from "@/components/chat/provider"
import { EmptyState, PageHeader } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ChatActions } from "@/components/chat/actions"
import { useInfo } from "@/components/providers"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { relative } from "@/lib/format"

function ConversationsList() {
  const router = useRouter()
  const params = useSearchParams()
  const selectedProject = params.get("project")
  const project =
    selectedProject !== null
      ? `project:${selectedProject}`
      : params.has("unassigned")
        ? "none"
        : "all"
  const { projects } = useInfo()
  const { chats, loading, error, reload } = useChatHistory()
  const [query, setQuery] = React.useState("")
  const filtered = chats.filter(
    (chat) =>
      chat.title.toLowerCase().includes(query.trim().toLowerCase()) &&
      (project === "all" ||
        (project === "none" ? !chat.project : chat.project === selectedProject)),
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Conversations"
        description="Reopen a conversation or manage your chat history."
      />
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
          <Input
            aria-label="Search conversations"
            placeholder="Search conversations…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-9"
          />
        </div>
        <Select
          value={project}
          onValueChange={(value) =>
            router.replace(
              value === "all"
                ? "/chat/history/"
                : value === "none"
                  ? "/chat/history/?unassigned=1"
                  : `/chat/history/?project=${encodeURIComponent(value.slice(8))}`,
            )
          }
        >
          <SelectTrigger aria-label="Filter conversations by project">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All projects</SelectItem>
            <SelectItem value="none">No project</SelectItem>
            {projects?.map((item) => (
              <SelectItem key={item.name} value={`project:${item.name}`}>
                {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {loading ? (
        <Skeleton className="h-44 w-full" />
      ) : error ? (
        <EmptyState
          icon={MessageSquare}
          title="Could not load conversations"
          description={error.message}
        >
          <Button variant="outline" onClick={reload}>
            Retry
          </Button>
        </EmptyState>
      ) : !chats.length ? (
        <EmptyState
          icon={MessageSquare}
          title="No conversations yet"
          description="Start a chat from the sidebar. Your saved conversations will appear here."
        />
      ) : !filtered.length ? (
        <p className="py-10 text-center text-[13px] text-muted-foreground">
          No conversations match your search.
        </p>
      ) : (
        <Card className="gap-0 overflow-hidden py-0">
          {filtered.map((chat) => (
            <div
              key={chat.id}
              className="flex items-center gap-2 border-b px-4 last:border-b-0 hover:bg-muted/40 sm:px-5"
            >
              <Link
                href={`/chat/?id=${encodeURIComponent(chat.id)}`}
                className="flex min-w-0 flex-1 items-center gap-3 py-4"
              >
                {chat.pinned ? (
                  <Pin className="size-4 shrink-0 text-brand" aria-label="Pinned conversation" />
                ) : (
                  <MessageSquare className="size-4 shrink-0 text-muted-foreground" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium">{chat.title}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {relative(chat.updated_at)}
                    {chat.project && <> · {chat.project}</>} ·{" "}
                    {chat.meeting_ids.length
                      ? `${chat.meeting_ids.length} selected meeting${chat.meeting_ids.length === 1 ? "" : "s"}`
                      : "All meeting notes"}
                  </span>
                </span>
                <ArrowUpRight className="size-4 shrink-0 text-muted-foreground" />
              </Link>
              <ChatActions chat={chat} />
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}

export default function ConversationsPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-44 w-full" />}>
      <ConversationsList />
    </React.Suspense>
  )
}
