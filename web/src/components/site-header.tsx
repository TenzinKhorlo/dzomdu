"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { Search } from "lucide-react"
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
import { Separator } from "@/components/ui/separator"
import { useMounted } from "@/hooks/use-mounted"
import { useRecorder } from "@/lib/recorder"
import { cn } from "@/lib/utils"

const TITLES: Record<string, string> = {
  "": "Overview",
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
      <kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded border bg-muted px-1.5 font-sans text-[11px] text-muted-foreground">
        {mac ? "⌘K" : "Ctrl K"}
      </kbd>
    </form>
  )
}

export function SiteHeader() {
  const pathname = usePathname()
  const parts = pathname.split("/").filter(Boolean)
  const crumbs = parts.length ? parts : [""]
  const rec = useRecorder()
  const scrolled = useScrolled()
  const onRecord = pathname.startsWith("/record")

  return (
    <header
      data-scrolled={scrolled}
      className={cn(
        "sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b bg-card px-4 md:px-6 lg:px-8",
        "transition-shadow data-[scrolled=true]:shadow-[0_2px_8px_rgb(0_0_0/0.03)]",
      )}
    >
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem className="hidden sm:block">
            <BreadcrumbLink asChild>
              <Link href="/" className="text-xs">Workspace</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator className="hidden sm:block" />
          {crumbs.map((part, i) => {
            const title = TITLES[part] ?? part
            const last = i === crumbs.length - 1
            const href = "/" + crumbs.slice(0, i + 1).join("/") + (part ? "/" : "")
            return (
              <span key={href} className="contents">
                {i > 0 && <BreadcrumbSeparator />}
                <BreadcrumbItem>
                  {last ? (
                    <BreadcrumbPage className="text-[13px] font-medium">{title}</BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink asChild>
                      <Link href={href} className="text-[13px]">
                        {title}
                      </Link>
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </span>
            )
          })}
        </BreadcrumbList>
      </Breadcrumb>
      <div className="ml-auto flex items-center gap-2">
        <HeaderSearch />
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
          ) : null}
        </AnimatePresence>
        <ThemeToggle />
      </div>
    </header>
  )
}
