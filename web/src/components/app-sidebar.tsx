"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { Folder, Mic, Plus } from "lucide-react"

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
  SidebarMenuItem,
  SidebarRail,
} from "@/components/animate-ui/components/radix/sidebar"
import { AnimateIcon } from "@/components/animate-ui/icons/icon"
import { AudioLines } from "@/components/animate-ui/icons/audio-lines"
import { Layers } from "@/components/animate-ui/icons/layers"
import { LayoutDashboard } from "@/components/animate-ui/icons/layout-dashboard"
import { MessageSquareText } from "@/components/animate-ui/icons/message-square-text"
import { Settings } from "@/components/animate-ui/icons/settings"
import { Users } from "@/components/animate-ui/icons/users"
import { useInfo } from "@/components/providers"
import { colorFor } from "@/lib/format"
import { cn } from "@/lib/utils"

const NAV = [
  { title: "Overview", href: "/", icon: LayoutDashboard },
  { title: "Record", href: "/record/", icon: AudioLines },
  { title: "Meetings", href: "/meetings/", icon: MessageSquareText },
  { title: "People", href: "/people/", icon: Users },
  { title: "Projects", href: "/projects/", icon: Layers },
]

// the selected item reads as a raised white pill on the grey sidebar
const ITEM =
  "text-[13px] text-sidebar-foreground [&>svg]:text-muted-foreground data-[active=true]:shadow-[0_0_0_1px_var(--sidebar-border),var(--shadow-card)] data-[active=true]:[&>svg]:text-sidebar-accent-foreground"
const LABEL = "text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase"

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href.replace(/\/$/, ""))
}

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()
  const { info } = useInfo()
  const projects = info?.projects ?? []

  return (
    <Sidebar collapsible="icon" variant="inset" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild className="hover:bg-transparent!">
              <Link href="/">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground shadow-[var(--shadow-card)]">
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

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className={LABEL}>Menu</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              {NAV.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <AnimateIcon animateOnHover asChild>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive(pathname, item.href)}
                      tooltip={item.title}
                      className={ITEM}
                    >
                      <Link href={item.href}>
                        <item.icon />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </AnimateIcon>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {projects.length > 0 && (
          <SidebarGroup className="group-data-[collapsible=icon]:hidden">
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
      </SidebarContent>

      <SidebarFooter className="gap-3">
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

function ProjectLinks({ projects }: { projects: string[] }) {
  const pathname = usePathname()
  const current = useSearchParams().get("project")
  return (
    <SidebarMenu className="gap-0.5">
      {projects.slice(0, 8).map((p) => (
        <SidebarMenuItem key={p}>
          <SidebarMenuButton
            asChild
            isActive={pathname.startsWith("/meetings") && current === p}
            className={ITEM}
          >
            <Link href={`/meetings/?project=${encodeURIComponent(p)}`}>
              <Folder style={{ color: colorFor(p), fill: colorFor(p) }} className="opacity-90" />
              <span>{p}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  )
}

/** A compact card with the state of the three local models, like a setup checklist. */
function ModelStatus() {
  const { info } = useInfo()
  if (!info) return null
  const rows = [
    { label: "Speech to text", ok: info.status.asr.ok },
    { label: "Voice recognition", ok: info.status.diarization.ok },
    { label: "Summaries (LLM)", ok: info.status.llm.ok },
  ]
  const ready = rows.filter((r) => r.ok).length
  return (
    <Link
      href="/settings/"
      className="pressable block rounded-xl border bg-background p-3 shadow-[var(--shadow-card)] transition-colors hover:bg-accent group-data-[collapsible=icon]:hidden"
    >
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] font-medium">Local models</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {ready}/{rows.length} ready
        </span>
      </div>
      <div className="mt-2 flex gap-1" aria-hidden>
        {rows.map((r) => (
          <span
            key={r.label}
            className={cn("h-1.5 flex-1 rounded-full", r.ok ? "bg-brand" : "bg-track")}
          />
        ))}
      </div>
      <ul className="mt-2.5 space-y-1">
        {rows.map((r) => (
          <li key={r.label} className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className={cn("size-1.5 rounded-full", r.ok ? "bg-success" : "bg-warning")}
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
