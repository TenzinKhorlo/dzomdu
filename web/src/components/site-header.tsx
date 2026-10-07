"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Mic } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"

import { SidebarTrigger } from "@/components/animate-ui/components/radix/sidebar"
import { ThemeToggle } from "@/components/theme-toggle"
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
import { useRecorder } from "@/lib/recorder"
import { cn } from "@/lib/utils"

const TITLES: Record<string, string> = {
  "": "Dashboard",
  record: "Record",
  meetings: "Meetings",
  view: "Meeting",
  people: "People",
  projects: "Projects",
  settings: "Settings",
}

function useScrolled(threshold = 4) {
  const [scrolled, setScrolled] = React.useState(false)
  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [threshold])
  return scrolled
}

export function SiteHeader() {
  const pathname = usePathname()
  const parts = pathname.split("/").filter(Boolean)
  const crumbs = parts.length ? parts : [""]
  const rec = useRecorder()
  const scrolled = useScrolled()
  const onRecord = pathname.startsWith("/record")

  return (
    // A translucent layer: content scrolls underneath. Instead of a hard divider, a soft edge
    // appears only once content actually passes beneath it.
    <header
      data-scrolled={scrolled}
      className={cn(
        "material sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 px-4 md:rounded-t-xl",
        "after:pointer-events-none after:absolute after:inset-x-0 after:top-full after:h-6 after:bg-gradient-to-b after:from-background/70 after:to-transparent after:opacity-0 after:transition-opacity after:duration-300",
        "data-[scrolled=true]:after:opacity-100",
      )}
    >
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
                    <BreadcrumbPage className="font-medium">{title}</BreadcrumbPage>
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
        <AnimatePresence initial={false} mode="popLayout">
          {rec.sessionId && !onRecord ? (
            <motion.div
              key="recording"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
            >
              <Link
                href={`/record/?session=${rec.sessionId}`}
                className="pressable flex items-center gap-2 rounded-full bg-recording/12 px-3 py-1.5 text-xs font-semibold text-recording"
              >
                <span className="size-2 animate-pulse rounded-full bg-recording" />
                Recording · back to it
              </Link>
            </motion.div>
          ) : !onRecord ? (
            <motion.div
              key="new"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="hidden sm:block"
            >
              <Button size="sm" asChild>
                <Link href="/record/">
                  <Mic />
                  New recording
                </Link>
              </Button>
            </motion.div>
          ) : null}
        </AnimatePresence>
        <ThemeToggle />
      </div>
    </header>
  )
}
