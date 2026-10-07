"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Mic } from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
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
import { cn } from "@/lib/utils"

const NAV = [
  { title: "Dashboard", href: "/", icon: LayoutDashboard },
  { title: "Record", href: "/record/", icon: AudioLines },
  { title: "Meetings", href: "/meetings/", icon: MessageSquareText },
  { title: "People", href: "/people/", icon: Users },
  { title: "Projects", href: "/projects/", icon: Layers },
]

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href.replace(/\/$/, ""))
}

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()
  const { info } = useInfo()
  const problems = info
    ? [!info.status.asr.ok, !info.status.diarization.ok, !info.status.llm.ok].filter(Boolean)
        .length
    : null

  return (
    <Sidebar collapsible="icon" variant="inset" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <Mic className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">Dzomdu</span>
                  <span className="truncate text-xs text-muted-foreground">Meeting notes</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <AnimateIcon animateOnHover asChild>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive(pathname, item.href)}
                      tooltip={item.title}
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
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <AnimateIcon animateOnHover asChild>
              <SidebarMenuButton
                asChild
                isActive={isActive(pathname, "/settings/")}
                tooltip="Settings & status"
              >
                <Link href="/settings/">
                  <Settings />
                  <span className="flex-1">Settings</span>
                  {problems !== null && (
                    <span
                      className={cn(
                        "size-2 rounded-full",
                        problems === 0 ? "bg-success" : "bg-warning",
                      )}
                      aria-label={problems === 0 ? "All systems ready" : `${problems} issue(s)`}
                    />
                  )}
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
