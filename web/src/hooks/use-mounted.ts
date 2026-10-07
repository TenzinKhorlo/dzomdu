"use client"

import { useSyncExternalStore } from "react"

const noop = () => () => {}

/**
 * False during the static prerender and hydration, true afterwards. Use it for anything that
 * depends on the visitor (time of day, theme) so the prerendered HTML matches hydration.
 */
export function useMounted(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  )
}
