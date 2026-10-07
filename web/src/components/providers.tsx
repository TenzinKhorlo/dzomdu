"use client"

import * as React from "react"
import { ThemeProvider } from "next-themes"

import { Toaster } from "@/components/ui/sonner"
import { api, type Info } from "@/lib/api"

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
      <InfoContext.Provider value={{ info, reload }}>{children}</InfoContext.Provider>
      <Toaster position="bottom-right" />
    </ThemeProvider>
  )
}
