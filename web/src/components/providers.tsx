"use client"

import * as React from "react"
import { MotionConfig } from "motion/react"
import { ThemeProvider } from "next-themes"

import { ConfirmProvider } from "@/components/confirm"
import { Toaster } from "@/components/ui/sonner"
import { api, type Info } from "@/lib/api"
import { spring } from "@/lib/motion"

const InfoContext = React.createContext<{ info?: Info; reload: () => void }>({
  reload: () => {},
})

/** App-wide settings from the backend: templates, known people/projects, model status. */
export function useInfo() {
  return React.useContext(InfoContext)
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [info, setInfo] = React.useState<Info>()
  const reload = React.useCallback(() => {
    api<Info>("/api/info")
      .then(setInfo)
      .catch(() => {})
  }, [])
  React.useEffect(() => reload(), [reload])

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      {/* every motion component defaults to a critically damped spring, and drops movement
          (keeping fades) when the user prefers reduced motion */}
      <MotionConfig transition={spring} reducedMotion="user">
        <ConfirmProvider>
          <InfoContext.Provider value={{ info, reload }}>{children}</InfoContext.Provider>
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
