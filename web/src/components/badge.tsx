"use client"

import * as React from "react"
import { Badge as AstryxBadge } from "@astryxdesign/core/Badge"

/** Same call shape the app used (variant + children); drawn by Astryx's Badge. */
export function Badge({
  variant = "default",
  destructive,
  children,
}: {
  variant?: "default" | "secondary" | "outline" | "destructive"
  children?: React.ReactNode
  className?: string
  destructive?: boolean
}) {
  // an icon element among the children goes in Astryx's icon slot; the rest is the label
  const parts = React.Children.toArray(children)
  const icon = parts.find(React.isValidElement) as React.ReactElement | undefined
  const label = parts.filter((p) => !React.isValidElement(p))
  const tone = destructive ? "error" : variant === "default" ? "info" : variant === "destructive" ? "error" : "neutral"
  return (
    <AstryxBadge
      variant={tone}
      icon={icon ? React.cloneElement(icon as React.ReactElement<{ className?: string }>, { className: "size-3" }) : undefined}
      label={label.length ? label : children}
    />
  )
}
