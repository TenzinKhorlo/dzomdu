"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import {
  ChevronRight,
  Folder,
  ListChecks,
  MessageSquare,
  MessagesSquare,
  Mic,
  MoreHorizontal,
  Pin,
  Plus,
  ShieldCheck,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuAction,
  SidebarMenuItem,
  SidebarMenuBadge,
  SidebarRail,
  useSidebar,
} from "@/components/animate-ui/components/radix/sidebar"
import { AnimateIcon } from "@/components/animate-ui/icons/icon"
import { AudioLines } from "@/components/animate-ui/icons/audio-lines"
import { Layers } from "@/components/animate-ui/icons/layers"
import { LayoutDashboard } from "@/components/animate-ui/icons/layout-dashboard"
import { MessageSquareText } from "@/components/animate-ui/icons/message-square-text"
import { Settings } from "@/components/animate-ui/icons/settings"
import { Users } from "@/components/animate-ui/icons/users"
import { useInfo } from "@/components/providers"
import { useChatHistory } from "@/components/chat/provider"
import { ChatActions } from "@/components/chat/actions"
import { reminderIsDue, useTasks } from "@/components/task-provider"
import { projectHref } from "@/lib/api"
import { colorFor } from "@/lib/format"
import { cn } from "@/lib/utils"

const NAV = [
  { title: "Overview", href: "/", icon: LayoutDashboard },
  { title: "Record", href: "/record/", icon: AudioLines },
  { title: "Meetings", href: "/meetings/", icon: MessageSquareText },
  { title: "Tasks", href: "/tasks/", icon: ListChecks },
  { title: "Chat", href: "/chat/", icon: MessagesSquare },
  { title: "People", href: "/people/", icon: Users },
  { title: "Projects", href: "/projects/", icon: Layers },
]

// A quiet filled selection keeps navigation separate from the content cards.
const ITEM =
  "h-9 rounded-lg px-3 text-[13px] text-sidebar-foreground [&>svg]:size-4 [&>svg]:text-muted-foreground data-[active=true]:font-medium data-[active=true]:[&>svg]:text-sidebar-accent-foreground"
const LABEL = "px-3 text-[11px] font-medium tracking-normal text-muted-foreground"

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href.replace(/\/$/, ""))
}

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()
  const { info, projects: projectRows } = useInfo()
  const projects = projectRows?.map((project) => project.name) ?? info?.projects ?? []

  return (
    <Sidebar collapsible="icon" variant="sidebar" {...props}>
      <SidebarHeader className="h-14 justify-center border-b px-3 py-2">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild className="h-10 hover:bg-transparent!">
              <Link href="/">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <Mic className="size-4" />
                </div>
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate text-sm font-semibold tracking-[-0.01em] text-foreground">
                    Dzomdu
                  </span>
                  <span className="truncate text-xs text-muted-foreground">Meeting notes</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="gap-4 px-2 pt-3">
        <SidebarGroup className="p-0">
          <SidebarGroupLabel className={LABEL}>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <React.Suspense>
              <WorkspaceLinks pathname={pathname} />
            </React.Suspense>
          </SidebarGroupContent>
        </SidebarGroup>

        {projects.length > 0 && (
          <SidebarGroup className="p-0 group-data-[collapsible=icon]:hidden">
            <SidebarGroupLabel className={LABEL}>Projects</SidebarGroupLabel>
            <SidebarGroupAction asChild title="New meeting in a project">
              <Link href="/record/">
                <Plus />
                <span className="sr-only">New meeting</span>
              </Link>
            </SidebarGroupAction>
            <SidebarGroupContent>
              <React.Suspense>
                <ProjectLinks projects={projects} />
              </React.Suspense>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
        <SidebarGroup className="p-0 group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel className={LABEL}>Recent conversations</SidebarGroupLabel>
          <SidebarGroupContent>
            <React.Suspense>
              <ConversationLinks />
            </React.Suspense>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="gap-3 p-3">
        <ModelStatus />
        <SidebarMenu>
          <SidebarMenuItem>
            <AnimateIcon animateOnHover asChild>
              <SidebarMenuButton
                asChild
                isActive={isActive(pathname, "/settings/")}
                tooltip="Settings & status"
                className={ITEM}
              >
                <Link href="/settings/">
                  <Settings />
                  <span>Settings</span>
                </Link>
              </SidebarMenuButton>
            </AnimateIcon>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

function WorkspaceLinks({ pathname }: { pathname: string }) {
  const params = useSearchParams()
  const { startNewChat } = useChatHistory()
  const { setOpenMobile } = useSidebar()
  const { tasks } = useTasks()
  const reminders = tasks.filter(reminderIsDue).length
  return (
    <SidebarMenu className="gap-1">
      {NAV.map((item) => {
        const isChat = item.href === "/chat/"
        return (
          <SidebarMenuItem key={item.href}>
            <AnimateIcon animateOnHover asChild>
              <SidebarMenuButton
                asChild
                isActive={
                  isActive(pathname, item.href) &&
                  (!isChat || (pathname.replace(/\/$/, "") === "/chat" && !params.get("id")))
                }
                tooltip={isChat ? "New Chat" : item.title}
                className={cn(ITEM, isChat && "group/new-chat")}
              >
                <Link
                  href={item.href}
                  aria-label={isChat ? "New Chat" : undefined}
                  onClick={(event) => {
                    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                    if (isChat) startNewChat()
                    setOpenMobile(false)
                  }}
                >
                  <item.icon />
                  {isChat ? (
                    <span aria-hidden>
                      <span className="group-hover/new-chat:hidden group-focus-visible/new-chat:hidden">
                        Chat
                      </span>
                      <span className="hidden group-hover/new-chat:inline group-focus-visible/new-chat:inline">
                        New Chat
                      </span>
                    </span>
                  ) : (
                    <span>{item.title}</span>
                  )}
                </Link>
              </SidebarMenuButton>
            </AnimateIcon>
            {item.href === "/tasks/" && reminders > 0 && (
              <SidebarMenuBadge
                className="rounded-md bg-brand/10 text-brand"
                title={`${reminders} reminders due`}
              >
                {reminders}
                <span className="sr-only"> reminders due</span>
              </SidebarMenuBadge>
            )}
          </SidebarMenuItem>
        )
      })}
    </SidebarMenu>
  )
}

function ConversationLinks() {
  const pathname = usePathname()
  const current = useSearchParams().get("id")
  const { chats, loading, error, reload } = useChatHistory()
  const { setOpenMobile } = useSidebar()
  if (loading)
    return (
      <p role="status" className="px-3 py-2 text-xs text-muted-foreground">
        Loading conversations…
      </p>
    )
  if (error)
    return (
      <div className="space-y-2 px-3 py-2 text-xs text-muted-foreground">
        <p>Could not load conversations.</p>
        <button type="button" onClick={reload} className="underline underline-offset-4">
          Retry
        </button>
      </div>
    )
  if (!chats.length)
    return (
      <p className="px-3 py-2 text-xs leading-5 text-muted-foreground">
        Your conversations will appear here.
      </p>
    )
  return (
    <SidebarMenu className="gap-0.5">
      {chats.slice(0, 3).map((chat) => (
        <SidebarMenuItem key={chat.id}>
          <SidebarMenuButton
            asChild
            className={ITEM}
            isActive={pathname.startsWith("/chat") && current === chat.id}
          >
            <Link
              href={`/chat/?id=${encodeURIComponent(chat.id)}`}
              title={chat.project ? `${chat.title} · ${chat.project}` : chat.title}
              onClick={(event) => {
                if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey)
                  setOpenMobile(false)
              }}
            >
              {chat.pinned ? <Pin aria-label="Pinned conversation" /> : <MessageSquare />}
              <span>{chat.title}</span>
            </Link>
          </SidebarMenuButton>
          <ChatActions chat={chat}>
            <SidebarMenuAction
              showOnHover
              aria-label={`Actions for ${chat.title}`}
              title="Conversation actions"
            >
              <MoreHorizontal className="size-3.5" />
            </SidebarMenuAction>
          </ChatActions>
        </SidebarMenuItem>
      ))}
      {chats.length > 3 && (
        <SidebarMenuItem>
          <SidebarMenuButton asChild className={cn(ITEM, "text-muted-foreground")}>
            <Link href="/chat/history/" onClick={() => setOpenMobile(false)}>
              <ChevronRight />
              <span>More</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      )}
    </SidebarMenu>
  )
}

function ProjectLinks({ projects }: { projects: string[] }) {
  const pathname = usePathname()
  const params = useSearchParams()
  const current = pathname.startsWith("/projects") ? params.get("name") : params.get("project")
  const { setOpenMobile } = useSidebar()
  return (
    <SidebarMenu className="gap-0.5">
      {projects.slice(0, 3).map((p) => (
        <SidebarMenuItem key={p}>
          <SidebarMenuButton
            asChild
            isActive={
              (pathname.startsWith("/projects") || pathname.startsWith("/meetings")) &&
              current === p
            }
            className={ITEM}
          >
            <Link href={projectHref(p)} onClick={() => setOpenMobile(false)}>
              <Folder style={{ color: colorFor(p) }} className="opacity-75" />
              <span>{p}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
      {projects.length > 3 && (
        <SidebarMenuItem>
          <SidebarMenuButton asChild className={cn(ITEM, "text-muted-foreground")}>
            <Link href="/projects/" onClick={() => setOpenMobile(false)}>
              <ChevronRight />
              <span>More</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      )}
    </SidebarMenu>
  )
}

/** The setup checklist only occupies the sidebar while models need attention. */
function ModelStatus() {
  const { info } = useInfo()
  if (!info) return null
  const rows = [
    { label: "Speech to text", ok: info.status.asr.ok },
    { label: "Voice recognition", ok: info.status.diarization.ok },
    { label: "Summaries (LLM)", ok: info.status.llm.ok },
  ]
  const complete = rows.every((row) => row.ok)
  return <ModelSetupCard key={complete ? "ready" : "setup"} rows={rows} complete={complete} />
}

function ModelSetupCard({
  rows,
  complete,
}: {
  rows: { label: string; ok: boolean }[]
  complete: boolean
}) {
  const reducedMotion = useReducedMotion()
  const [dismissed, setDismissed] = React.useState(false)
  React.useEffect(() => {
    if (!complete) return
    const timer = window.setTimeout(() => setDismissed(true), 1600)
    return () => window.clearTimeout(timer)
  }, [complete])
  const ready = rows.filter((row) => row.ok).length

  return (
    <AnimatePresence initial={false}>
      {!dismissed && (
        <motion.div
          initial={false}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: reducedMotion ? 0 : 0.25 }}
          className="overflow-hidden group-data-[collapsible=icon]:hidden"
        >
          <Link
            href="/settings/"
            className="pressable block rounded-xl border bg-card p-3 transition-colors hover:bg-accent"
          >
            <div className="flex items-baseline justify-between">
              <span className="flex items-center gap-1.5 text-xs font-medium">
                <ShieldCheck className="size-3.5 text-muted-foreground" />
                Local models
              </span>
              {complete ? (
                <span role="status" className="self-center text-success">
                  <span className="sr-only">Setup complete. All local models are ready.</span>
                  <svg className="size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <motion.path
                      d="M5 12l4 4L19 6"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      initial={{ pathLength: reducedMotion ? 1 : 0 }}
                      animate={{ pathLength: 1 }}
                      transition={{ duration: reducedMotion ? 0 : 0.45, ease: "easeOut" }}
                    />
                  </svg>
                </span>
              ) : (
                <span className="text-xs text-muted-foreground tabular-nums">
                  {ready}/{rows.length} ready
                </span>
              )}
            </div>
            {!complete && (
              <>
                <div className="mt-2 flex gap-1" aria-hidden>
                  {rows.map((r) => (
                    <span
                      key={r.label}
                      className={cn("h-1 flex-1 rounded-full", r.ok ? "bg-success" : "bg-track")}
                    />
                  ))}
                </div>
                <ul className="mt-2.5 space-y-1">
                  {rows.map((r) => (
                    <li
                      key={r.label}
                      className="flex items-center gap-2 text-xs text-muted-foreground"
                    >
                      <span
                        className={cn("size-1.5 rounded-full", r.ok ? "bg-success" : "bg-warning")}
                        aria-hidden
                      />
                      {r.label}
                      <span className="sr-only">{r.ok ? "ready" : "needs attention"}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Link>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
