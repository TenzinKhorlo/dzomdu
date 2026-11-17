"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { AppShell } from "@astryxdesign/core/AppShell"
import { BreadcrumbItem, Breadcrumbs } from "@astryxdesign/core/Breadcrumbs"
import { Button } from "@astryxdesign/core/Button"
import { Icon } from "@astryxdesign/core/Icon"
import { IconButton } from "@astryxdesign/core/IconButton"
import { SideNav, SideNavHeading, SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav"
import { TopNav } from "@astryxdesign/core/TopNav"
import {
  AudioLines,
  Folder,
  Layers,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  MessageSquareText,
  MessagesSquare,
  Mic,
  Monitor,
  Moon,
  Pin,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Users,
} from "lucide-react"
import { useTheme } from "next-themes"
import { flushSync } from "react-dom"

import { ChatActions } from "@/components/chat/actions"
import { useChatHistory } from "@/components/chat/provider"
import { useInfo } from "@/components/providers"
import { reminderIsDue, useTasks } from "@/components/task-provider"
import { useMounted } from "@/hooks/use-mounted"
import { ToastBridge } from "@/lib/toast"
import { projectHref } from "@/lib/api"
import { useRecorder } from "@/lib/recorder"

const NAV = [
  { title: "Overview", href: "/", icon: LayoutDashboard },
  { title: "Record", href: "/record/", icon: AudioLines },
  { title: "Meetings", href: "/meetings/", icon: MessageSquareText },
  { title: "Tasks", href: "/tasks/", icon: ListChecks },
  { title: "Chat", href: "/chat/", icon: MessagesSquare },
  { title: "People", href: "/people/", icon: Users },
  { title: "Projects", href: "/projects/", icon: Layers },
]

const TITLES: Record<string, string> = {
  record: "Record",
  meetings: "Meetings",
  tasks: "Tasks",
  chat: "Ask Dzomdu",
  history: "Conversations",
  view: "Meeting",
  people: "People",
  projects: "Projects",
  settings: "Settings",
}

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href.replace(/\/$/, ""))
}

/** The app frame: Astryx's shell with the side navigation, top bar and page content slot. */
export function AppChrome({ children }: { children: React.ReactNode }) {
  return (
    <AppShell
      variant="elevated"
      topNav={
        <React.Suspense>
          <AppTopNav />
        </React.Suspense>
      }
      sideNav={
        <React.Suspense>
          <AppSideNav />
        </React.Suspense>
      }
    >
      <ToastBridge />
      <div className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-5 px-4 py-6 md:px-6 lg:px-8">
        {children}
      </div>
    </AppShell>
  )
}

/* -- side navigation ------------------------------------------------------------------- */

function AppSideNav() {
  const pathname = usePathname()
  const params = useSearchParams()
  const { info, projects: projectRows } = useInfo()
  const { startNewChat } = useChatHistory()
  const { tasks } = useTasks()
  const reminders = tasks.filter(reminderIsDue).length
  const projects = projectRows?.map((project) => project.name) ?? info?.projects ?? []
  const currentProject = pathname.startsWith("/projects") ? params.get("name") : params.get("project")

  return (
    <SideNav
      collapsible
      header={
        <SideNavHeading
          heading="Dzomdu"
          subheading="Meeting notes"
          headingHref="/"
          icon={
            <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
              <Mic className="size-4" />
            </span>
          }
        />
      }
      footer={<ModelStatus />}
      footerIcons={
        <SideNavItem
          label="Settings"
          icon={Settings}
          href="/settings/"
          isSelected={isActive(pathname, "/settings/")}
        />
      }
    >
      <SideNavSection title="Workspace" isHeaderHidden>
        {NAV.map((item) => {
          const isChat = item.href === "/chat/"
          return (
            <SideNavItem
              key={item.href}
              label={isChat ? "Chat" : item.title}
              icon={item.icon}
              href={item.href}
              isSelected={
                isActive(pathname, item.href) &&
                (!isChat || (pathname.replace(/\/$/, "") === "/chat" && !params.get("id")))
              }
              onClick={(event) => {
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                if (isChat) startNewChat()
              }}
              endContent={
                item.href === "/tasks/" && reminders > 0 ? (
                  <span className="font-mono text-xs tabular-nums" title={`${reminders} reminders due`}>
                    {reminders}
                    <span className="sr-only"> reminders due</span>
                  </span>
                ) : undefined
              }
            />
          )
        })}
      </SideNavSection>

      {projects.length > 0 && (
        <SideNavSection title="Projects">
          {projects.slice(0, 3).map((name) => (
            <SideNavItem
              key={name}
              label={name}
              icon={Folder}
              href={projectHref(name)}
              isSelected={
                (pathname.startsWith("/projects") || pathname.startsWith("/meetings")) &&
                currentProject === name
              }
            />
          ))}
          {projects.length > 3 && <SideNavItem label="More projects" href="/projects/" />}
        </SideNavSection>
      )}

      <SideNavSection title="Recent conversations">
        <ConversationLinks />
      </SideNavSection>
    </SideNav>
  )
}

function ConversationLinks() {
  const pathname = usePathname()
  const current = useSearchParams().get("id")
  const { chats, loading, error, reload } = useChatHistory()
  if (loading)
    return (
      <p role="status" className="px-3 py-2 text-xs text-muted-foreground">
        Loading conversations…
      </p>
    )
  if (error)
    return (
      <div className="flex flex-col items-start gap-1 px-3 py-2 text-xs text-muted-foreground">
        <span>Could not load conversations.</span>
        <Button size="sm" variant="ghost" label="Retry" onClick={reload} />
      </div>
    )
  if (!chats.length)
    return (
      <p className="px-3 py-2 text-xs leading-5 text-muted-foreground">
        Your conversations will appear here.
      </p>
    )
  return (
    <>
      {chats.slice(0, 3).map((chat) => (
        <SideNavItem
          key={chat.id}
          label={chat.title}
          icon={chat.pinned ? Pin : MessageSquare}
          href={`/chat/?id=${encodeURIComponent(chat.id)}`}
          isSelected={pathname.startsWith("/chat") && current === chat.id}
          actions={<ChatActions chat={chat} />}
        />
      ))}
      {chats.length > 3 && <SideNavItem label="More conversations" href="/chat/history/" />}
    </>
  )
}

/** The setup checklist only occupies the sidebar while local models need attention. */
function ModelStatus() {
  const { info } = useInfo()
  if (!info) return null
  const rows = [
    { label: "Speech to text", ok: info.status.asr.ok },
    { label: "Voice recognition", ok: info.status.diarization.ok },
    { label: "Summaries (LLM)", ok: info.status.llm.ok },
  ]
  if (rows.every((row) => row.ok)) return null
  const ready = rows.filter((row) => row.ok).length
  return (
    <Link
      href="/settings/"
      className="pressable block rounded-xl border bg-card p-3 transition-colors hover:bg-accent"
    >
      <div className="flex items-baseline justify-between">
        <span className="flex items-center gap-1.5 text-xs font-medium">
          <ShieldCheck className="size-3.5 text-muted-foreground" />
          Local models
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {ready}/{rows.length} ready
        </span>
      </div>
      <ul className="mt-2.5 space-y-1">
        {rows.map((r) => (
          <li key={r.label} className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className={`size-1.5 rounded-full ${r.ok ? "bg-success" : "bg-warning"}`}
              aria-hidden
            />
            {r.label}
            <span className="sr-only">{r.ok ? "ready" : "needs attention"}</span>
          </li>
        ))}
      </ul>
    </Link>
  )
}

/* -- top bar --------------------------------------------------------------------------- */

function AppTopNav() {
  const pathname = usePathname()
  const rec = useRecorder()
  const parts = pathname.split("/").filter(Boolean)
  const onRecord = pathname.startsWith("/record")
  return (
    <TopNav
      label="Page"
      startContent={
        <Breadcrumbs label="Breadcrumb">
          <BreadcrumbItem href="/">Workspace</BreadcrumbItem>
          {(parts.length ? parts : [""]).map((part, i, all) => {
            const title =
              part === ""
                ? "Overview"
                : part === "view" && pathname.startsWith("/projects/")
                  ? "Project"
                  : (TITLES[part] ?? part)
            const last = i === all.length - 1
            const href = "/" + all.slice(0, i + 1).join("/") + (part ? "/" : "")
            return (
              <BreadcrumbItem key={href} href={last ? undefined : href} isCurrent={last}>
                {title}
              </BreadcrumbItem>
            )
          })}
        </Breadcrumbs>
      }
      endContent={
        <div className="flex items-center gap-2">
          <HeaderSearch />
          {rec.sessionId && !onRecord ? (
            <Button
              size="sm"
              variant="secondary"
              href={`/record/?session=${rec.sessionId}`}
              label="Recording · back to it"
              icon={<span className="size-2 animate-pulse rounded-full bg-recording" />}
            />
          ) : null}
          <ThemeToggle />
        </div>
      }
    />
  )
}

/** Search meetings from anywhere. ⌘K / Ctrl+K focuses it; Enter opens the filtered list. */
function HeaderSearch() {
  const router = useRouter()
  const ref = React.useRef<HTMLInputElement>(null)
  const mounted = useMounted()
  const mac = !mounted || /Mac|iPhone|iPad/.test(navigator.platform)
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        ref.current?.focus()
        ref.current?.select()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  return (
    <form
      role="search"
      className="relative hidden w-64 md:block lg:w-72"
      onSubmit={(e) => {
        e.preventDefault()
        const q = ref.current?.value.trim() ?? ""
        router.push(q ? `/meetings/?q=${encodeURIComponent(q)}` : "/meetings/")
        ref.current?.blur()
      }}
    >
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <input
        ref={ref}
        type="search"
        placeholder="Search meetings…"
        aria-label="Search meetings"
        className="h-8 w-full rounded-lg border bg-background/60 pr-12 pl-8 text-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40 [&::-webkit-search-cancel-button]:hidden"
      />
      <kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded border bg-muted px-1.5 font-sans text-xs text-muted-foreground">
        {mac ? "⌘K" : "Ctrl K"}
      </kbd>
    </form>
  )
}

type Mode = "light" | "dark" | "system"
const MODE_ICON = { light: Sun, dark: Moon, system: Monitor }
const MODE_LABEL = { light: "Light", dark: "Dark", system: "Match system" }

/**
 * Cycles system → the opposite look → the system's look again, explicitly → system, with a short
 * cross-fade (no abrupt brightness jump). Starting from "system", the first click always changes
 * what you see. next-themes persists the choice; Astryx follows it (see providers.tsx).
 */
export function ThemeToggle() {
  const { theme, setTheme, systemTheme } = useTheme()
  const mounted = useMounted()
  const sys = systemTheme === "dark" ? "dark" : "light"
  const order: Mode[] = ["system", sys === "dark" ? "light" : "dark", sys]
  const current: Mode = mounted && order.includes(theme as Mode) ? (theme as Mode) : "system"
  const next = order[(order.indexOf(current) + 1) % order.length]

  function change() {
    const apply = () => flushSync(() => setTheme(next))
    if (typeof document !== "undefined" && "startViewTransition" in document) {
      document.startViewTransition(apply)
    } else {
      apply()
    }
  }

  return (
    <IconButton
      variant="ghost"
      label={`Appearance: ${MODE_LABEL[current]}. Switch to ${MODE_LABEL[next]}`}
      tooltip={`Appearance: ${MODE_LABEL[current]}`}
      icon={<Icon icon={MODE_ICON[current]} />}
      onClick={change}
    />
  )
}
