"use client"

import * as React from "react"
import { LinkProvider } from "@astryxdesign/core/Link"
import { Theme } from "@astryxdesign/core/theme"
import Link from "next/link"
import { MotionConfig } from "motion/react"
import { ThemeProvider, useTheme } from "next-themes"

import { defaultThemeSlug, themes } from "@/astryx-themes"
import { ConfirmProvider } from "@/components/confirm"
import { ChatHistoryProvider } from "@/components/chat/provider"
import { TaskProvider } from "@/components/task-provider"
import { useApi } from "@/hooks/use-api"
import { api, type Info, type Project } from "@/lib/api"
import { spring } from "@/lib/motion"

const InfoContext = React.createContext<{
  info?: Info
  projects?: Project[]
  reload: () => void
}>({
  reload: () => {},
})

/** App-wide settings from the backend: templates, known people/projects, model status. */
export function useInfo() {
  return React.useContext(InfoContext)
}

/** Astryx follows the same light/dark choice as the rest of the app (next-themes). */
function AstryxTheme({ children }: { children: React.ReactNode }) {
  const { resolvedTheme } = useTheme()
  // The page is pre-rendered, so the server always says "system". Using the saved choice on the first
  // client render would mismatch it and React keeps the server's attributes, leaving the wrong mode.
  const mounted = React.useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  )
  const mode = mounted && resolvedTheme === "dark" ? "dark" : mounted && resolvedTheme === "light" ? "light" : "system"
  return (
    <Theme theme={themes[defaultThemeSlug]} mode={mode}>
      <LinkProvider component={Link}>{children}</LinkProvider>
    </Theme>
  )
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [info, setInfo] = React.useState<Info>()
  const projects = useApi<Project[]>("/api/projects", { interval: 30000 })
  const fetchInfo = React.useCallback(() => {
    api<Info>("/api/info")
      .then(setInfo)
      .catch(() => {})
  }, [])
  const reloadProjects = projects.reload
  const reload = React.useCallback(() => {
    fetchInfo()
    reloadProjects()
  }, [fetchInfo, reloadProjects])
  React.useEffect(() => fetchInfo(), [fetchInfo])

  return (
    <ThemeProvider attribute={["class", "data-theme"]} defaultTheme="system" enableSystem disableTransitionOnChange>
      {/* every motion component defaults to a critically damped spring, and drops movement
          (keeping fades) when the user prefers reduced motion */}
      <AstryxTheme>
      <MotionConfig transition={spring} reducedMotion="user">
        <ConfirmProvider>
          <InfoContext.Provider value={{ info, projects: projects.data, reload }}>
            <ChatHistoryProvider>
              <TaskProvider>{children}</TaskProvider>
            </ChatHistoryProvider>
          </InfoContext.Provider>
        </ConfirmProvider>
      </MotionConfig>
      </AstryxTheme>
    </ThemeProvider>
  )
}
