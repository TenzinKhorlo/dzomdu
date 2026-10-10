"use client"

import * as React from "react"
import { MotionConfig } from "motion/react"
import { ThemeProvider } from "next-themes"

import { ConfirmProvider } from "@/components/confirm"
import { ChatHistoryProvider } from "@/components/chat/provider"
import { TaskProvider } from "@/components/task-provider"
import { Toaster } from "@/components/ui/sonner"
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
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      {/* every motion component defaults to a critically damped spring, and drops movement
          (keeping fades) when the user prefers reduced motion */}
      <MotionConfig transition={spring} reducedMotion="user">
        <ConfirmProvider>
          <InfoContext.Provider value={{ info, projects: projects.data, reload }}>
            <ChatHistoryProvider>
              <TaskProvider>{children}</TaskProvider>
            </ChatHistoryProvider>
          </InfoContext.Provider>
        </ConfirmProvider>
        <Toaster
          position="bottom-right"
          toastOptions={{ className: "material-toast" }}
          style={
            {
              "--normal-bg": "color-mix(in oklch, var(--popover) 78%, transparent)",
              "--normal-text": "var(--popover-foreground)",
              "--normal-border": "color-mix(in oklch, var(--border) 70%, transparent)",
              "--border-radius": "calc(var(--radius) + 4px)",
            } as React.CSSProperties
          }
        />
      </MotionConfig>
    </ThemeProvider>
  )
}
