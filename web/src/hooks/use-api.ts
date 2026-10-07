"use client"

import * as React from "react"

import { api } from "@/lib/api"

/** Minimal data-fetching hook: loads `path`, optionally re-polls, exposes `reload`. */
export function useApi<T>(path: string | null, options: { interval?: number } = {}) {
  const [data, setData] = React.useState<T | undefined>(undefined)
  const [error, setError] = React.useState<Error | undefined>(undefined)
  const [version, setVersion] = React.useState(0)

  React.useEffect(() => {
    if (!path) return
    let cancelled = false
    const load = () =>
      api<T>(path).then(
        (d) => {
          if (cancelled) return
          setData(d)
          setError(undefined)
        },
        (e: Error) => {
          if (!cancelled) setError(e)
        },
      )
    void load()
    const timer = options.interval ? window.setInterval(load, options.interval) : undefined
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [path, options.interval, version])

  const reload = React.useCallback(() => setVersion((v) => v + 1), [])
  return { data, error, loading: data === undefined && !error, reload }
}
