"use client"

import * as React from "react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/animate-ui/components/radix/dialog"
import { Button } from "@/components/ui/button"

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

  const confirm = React.useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>((resolve) => setPending({ ...options, resolve })),
    [],
  )
  const cancelRef = React.useRef<HTMLButtonElement>(null)

  // Keep focus inside while open. A menu that is still animating out (or a pointer-leave on
  // the item that opened us) must not take focus away, or Enter would land somewhere else.
  React.useEffect(() => {
    if (!pending) return
    let last: HTMLElement | null = null
    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement
      if (target.closest?.('[data-slot="dialog-content"]')) last = target
      else (last ?? cancelRef.current)?.focus()
    }
    document.addEventListener("focusin", onFocusIn)
    return () => document.removeEventListener("focusin", onFocusIn)
  }, [pending])

  const close = (ok: boolean) => {
    pending?.resolve(ok)
    setPending(null)
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={pending !== null} onOpenChange={(open) => !open && close(false)}>
        <DialogContent className="sm:max-w-md" showCloseButton={false}>
          {pending && (
            <>
              <DialogHeader>
                <DialogTitle>{pending.title}</DialogTitle>
                {pending.description && (
                  <DialogDescription>{pending.description}</DialogDescription>
                )}
              </DialogHeader>
              <DialogFooter>
                {/* the safe choice has focus, so Enter never destroys anything by accident */}
                <Button ref={cancelRef} variant="outline" autoFocus onClick={() => close(false)}>
                  Cancel
                </Button>
                <Button
                  variant={pending.destructive ? "destructive" : "default"}
                  onClick={() => close(true)}
                >
                  {pending.confirmLabel}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  )
}
