"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Mic } from "lucide-react"

import { ThemeTogglerButton } from "@/components/animate-ui/components/buttons/theme-toggler"
import { SidebarTrigger } from "@/components/animate-ui/components/radix/sidebar"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { useMounted } from "@/hooks/use-mounted"
import { useRecorder } from "@/lib/recorder"

const TITLES: Record<string, string> = {
  "": "Dashboard",
  record: "Record",
  meetings: "Meetings",
  view: "Meeting",
  people: "People",
  projects: "Projects",
  settings: "Settings",
}

export function SiteHeader() {
  const pathname = usePathname()
  const parts = pathname.split("/").filter(Boolean)
  const crumbs = parts.length ? parts : [""]
  const rec = useRecorder()
  const mounted = useMounted()

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
      <Breadcrumb>
        <BreadcrumbList>
          {crumbs.map((part, i) => {
            const title = TITLES[part] ?? part
            const last = i === crumbs.length - 1
            const href = "/" + crumbs.slice(0, i + 1).join("/") + (part ? "/" : "")
            return (
              <span key={href} className="contents">
                {i > 0 && <BreadcrumbSeparator />}
                <BreadcrumbItem>
                  {last ? (
                    <BreadcrumbPage>{title}</BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink asChild>
                      <Link href={href}>{title}</Link>
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </span>
            )
          })}
        </BreadcrumbList>
      </Breadcrumb>
      <div className="ml-auto flex items-center gap-2">
        {rec.sessionId && !pathname.startsWith("/record") && (
          <Link
            href={`/record/?session=${rec.sessionId}`}
            className="flex items-center gap-2 rounded-full bg-recording/10 px-3 py-1 text-xs font-medium text-recording"
          >
            <span className="size-2 animate-pulse rounded-full bg-recording" />
            Recording
          </Link>
        )}
        {!rec.sessionId && !pathname.startsWith("/record") && (
          <Button size="sm" asChild className="hidden sm:inline-flex">
            <Link href="/record/">
              <Mic />
              New recording
            </Link>
          </Button>
        )}
        {mounted ? (
          <ThemeTogglerButton variant="ghost" size="sm" aria-label="Switch theme" />
        ) : (
          <span className="size-8" aria-hidden />
        )}
      </div>
    </header>
  )
}
