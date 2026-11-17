"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { useToast, type ShowToastFn } from "@astryxdesign/core/Toast"

type Options = {
  description?: string | null
  action?: { label: string; onClick: () => void }
}

// Astryx toasts come from a hook, but this app also raises them from plain modules (the recorder,
// data hooks). <ToastBridge /> hands the hook's function to this module once the shell is mounted.
let show: ShowToastFn | null = null
const queued: Array<() => void> = []

function raise(type: "info" | "error", message: string, options?: Options) {
  const fire = () =>
    show?.({
      type,
      body: options?.description ? (
        <span>
          <strong className="font-medium">{message}</strong>
          <span className="block opacity-80">{options.description}</span>
        </span>
      ) : (
        message
      ),
      endContent: options?.action ? (
        <Button
          size="sm"
          variant="ghost"
          label={options.action.label}
          onClick={options.action.onClick}
        />
      ) : undefined,
    })
  if (show) fire()
  else queued.push(fire)
}

/** Same call shape the app already uses: toast.success / error / warning(message, { description, action }). */
export const toast = {
  success: (message: string, options?: Options) => raise("info", message, options),
  warning: (message: string, options?: Options) => raise("info", message, options),
  error: (message: string, options?: Options) => raise("error", message, options),
}

/** Render once inside the Astryx shell (a toast host must be an ancestor of useToast). */
export function ToastBridge() {
  const fn = useToast()
  React.useEffect(() => {
    show = fn
    queued.splice(0).forEach((fire) => fire())
    return () => {
      show = null
    }
  }, [fn])
  return null
}
