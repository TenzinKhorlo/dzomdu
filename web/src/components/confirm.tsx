"use client"

import * as React from "react"
import { AlertDialog } from "@astryxdesign/core/AlertDialog"

type ConfirmOptions = {
  title: string
  description?: string
  confirmLabel: string
  destructive?: boolean
}

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void }

const ConfirmContext = React.createContext<(o: ConfirmOptions) => Promise<boolean>>(
  async () => false,
)

/**
 * In-app confirmation for genuinely destructive, irreversible actions only (forget a voice,
 * discard a recording, overwrite edits). Everything else uses Undo instead.
 */
export function useConfirm() {
  return React.useContext(ConfirmContext)
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = React.useState<Pending | null>(null)
  // the last request stays rendered while the dialog animates out
  const [shown, setShown] = React.useState<Pending | null>(null)

  const confirm = React.useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>((resolve) => {
        const request = { ...options, resolve }
        setShown(request)
        setPending(request)
      }),
    [],
  )

  const close = (ok: boolean) => {
    pending?.resolve(ok)
    setPending(null)
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AlertDialog
        isOpen={pending !== null}
        onOpenChange={(open) => !open && close(false)}
        title={shown?.title ?? ""}
        description={shown?.description ?? ""}
        actionLabel={shown?.confirmLabel ?? ""}
        actionVariant={shown?.destructive ? "destructive" : "primary"}
        onAction={() => close(true)}
      />
    </ConfirmContext.Provider>
  )
}
