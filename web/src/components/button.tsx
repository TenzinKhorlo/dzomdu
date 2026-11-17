"use client"

import * as React from "react"
import { Button as AstryxButton } from "@astryxdesign/core/Button"
import Link from "next/link"

type Variant = "default" | "outline" | "secondary" | "ghost" | "destructive" | "link"
type Size = "default" | "sm" | "lg" | "icon" | "icon-sm" | "icon-xs"

const VARIANT = {
  default: "primary",
  outline: "secondary",
  secondary: "secondary",
  ghost: "ghost",
  destructive: "destructive",
  link: "ghost",
} as const

type Props = Omit<React.ComponentProps<"button">, "children"> & {
  variant?: Variant
  size?: Size
  asChild?: boolean
  isLoading?: boolean
  children?: React.ReactNode
}

const iconClass = (el: React.ReactElement) =>
  React.cloneElement(el as React.ReactElement<{ className?: string }>, { className: "size-4" })

/**
 * The app's button, drawn by Astryx. Keeps the call shape used across the app (icon and text as
 * children, variant/size names, `asChild` around a <Link>), and maps it onto Astryx's label, icon,
 * endContent and href slots.
 */
export function Button({
  variant = "default",
  size = "default",
  asChild,
  isLoading,
  children,
  disabled,
  type,
  onClick,
  ...rest
}: Props) {
  let href: string | undefined
  let content: React.ReactNode = children
  if (asChild && React.isValidElement<{ href?: string; children?: React.ReactNode }>(children)) {
    href = children.props.href
    content = children.props.children
  }
  const parts = React.Children.toArray(content)
  const text = parts.filter((p) => typeof p === "string" || typeof p === "number").join("").trim()
  const elements = parts.filter(React.isValidElement) as React.ReactElement[]
  const iconOnly = size.startsWith("icon") || !text
  const firstIsLeading = parts.findIndex(React.isValidElement) < parts.findIndex((p) => typeof p === "string")
  const label = text || (rest["aria-label"] as string) || "Button"
  const icon = elements[0] ? iconClass(elements[0]) : undefined

  return (
    <AstryxButton
      variant={VARIANT[variant]}
      size={size === "sm" || size === "icon-sm" || size === "icon-xs" ? "sm" : size === "lg" ? "lg" : "md"}
      label={label}
      aria-label={rest["aria-label"]}
      isIconOnly={iconOnly && !!icon}
      icon={iconOnly || firstIsLeading || !text ? icon : undefined}
      endContent={!iconOnly && !firstIsLeading && icon ? icon : undefined}
      isDisabled={disabled}
      isLoading={isLoading}
      href={href}
      as={href ? (Link as never) : undefined}
      type={type}
      onClick={onClick as never}
    />
  )
}
