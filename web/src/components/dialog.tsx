"use client"

import * as React from "react"
import { Dialog as AstryxDialog } from "@astryxdesign/core/Dialog"
import { Heading } from "@astryxdesign/core/Heading"
import { IconButton } from "@astryxdesign/core/IconButton"
import { Icon } from "@astryxdesign/core/Icon"
import { Text } from "@astryxdesign/core/Text"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * Dialog parts with the shape the app already uses (Dialog / Trigger / Content / Header / Title /
 * Description / Footer / Close), drawn by Astryx's Dialog so focus handling, the backdrop and the
 * theme come from the design system.
 */

type Ctx = {
  open: boolean
  setOpen: (open: boolean) => void
  titleId: string
  setWidth: (width: number | string | undefined) => void
}
const DialogCtx = React.createContext<Ctx | null>(null)
const useDialogCtx = () => {
  const ctx = React.useContext(DialogCtx)
  if (!ctx) throw new Error("Dialog parts must be rendered inside <Dialog>")
  return ctx
}

type DialogProps = {
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  children: React.ReactNode
}

export function Dialog({ open, defaultOpen = false, onOpenChange, children }: DialogProps) {
  const [inner, setInner] = React.useState(defaultOpen)
  const [width, setWidth] = React.useState<number | string | undefined>()
  const titleId = React.useId()
  const controlled = open !== undefined
  const isOpen = controlled ? open : inner
  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!controlled) setInner(next)
      onOpenChange?.(next)
    },
    [controlled, onOpenChange],
  )
  const parts = React.Children.toArray(children)
  const content = parts.filter((c) => !(React.isValidElement(c) && c.type === DialogTrigger))
  const triggers = parts.filter((c) => React.isValidElement(c) && c.type === DialogTrigger)
  return (
    <DialogCtx.Provider value={{ open: isOpen, setOpen, titleId, setWidth }}>
      {triggers}
      <AstryxDialog
        isOpen={isOpen}
        onOpenChange={setOpen}
        purpose="form"
        width={width ?? 480}
        padding={0}
        aria-labelledby={titleId}
      >
        {isOpen ? content : null}
      </AstryxDialog>
    </DialogCtx.Provider>
  )
}

export function DialogTrigger({
  children,
}: {
  children: React.ReactNode
  asChild?: boolean
}) {
  const { setOpen } = useDialogCtx()
  if (!React.isValidElement<{ onClick?: (e: React.MouseEvent) => void }>(children)) return <>{children}</>
  return React.cloneElement(children, {
    onClick: (e: React.MouseEvent) => {
      children.props.onClick?.(e)
      if (!e.defaultPrevented) setOpen(true)
    },
  })
}

export function DialogClose({
  children,
  onClick,
}: {
  children: React.ReactElement<{ onClick?: (e: React.MouseEvent) => void }>
  asChild?: boolean
  onClick?: (e: React.MouseEvent) => void
}) {
  const { setOpen } = useDialogCtx()
  return React.cloneElement(children, {
    onClick: (e: React.MouseEvent) => {
      children.props.onClick?.(e)
      onClick?.(e)
      setOpen(false)
    },
  })
}

type ContentProps = React.ComponentProps<"div"> & { showCloseButton?: boolean }

export function DialogContent({ className, children, showCloseButton = true, ...props }: ContentProps) {
  const { setOpen, setWidth } = useDialogCtx()
  // sm:max-w-* classes on the old API carried the intended width; map the common ones
  const wide = /max-w-(2xl|3xl|4xl|5xl)/.exec(className ?? "")
  const medium = /max-w-(lg|xl)/.exec(className ?? "")
  React.useEffect(() => {
    setWidth(wide ? 720 : medium ? 560 : undefined)
  }, [wide, medium, setWidth])
  return (
    <div className={cn("relative flex flex-col gap-4 p-5", className?.replace(/sm:max-w-\S+/g, ""))} {...props}>
      {showCloseButton && (
        <div className="absolute top-3 right-3">
          <IconButton
            variant="ghost"
            size="sm"
            label="Close"
            icon={<Icon icon={X} />}
            onClick={() => setOpen(false)}
          />
        </div>
      )}
      {children}
    </div>
  )
}

export function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1 pr-8", className)} {...props} />
}

export function DialogTitle({ children }: { children: React.ReactNode; className?: string }) {
  const { titleId } = useDialogCtx()
  return (
    <Heading level={3} id={titleId}>
      {children}
    </Heading>
  )
}

export function DialogDescription({ children }: { children: React.ReactNode; className?: string }) {
  return <Text type="supporting" color="secondary">{children}</Text>
}

export function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)} {...props} />
  )
}
