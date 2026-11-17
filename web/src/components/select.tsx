"use client"

import * as React from "react"
import { Selector } from "@astryxdesign/core/Selector"

/**
 * Select parts with the shape the app already uses, drawn by Astryx's Selector. <Select> reads its
 * <SelectItem>s (through SelectContent, fragments and mapped lists) into the Selector's options, and
 * takes the accessible name from <SelectTrigger aria-label>.
 */

type ItemProps = { value: string; disabled?: boolean; children?: React.ReactNode }
export function SelectItem(props: ItemProps) {
  void props
  return null
}
export function SelectContent({ children }: { children?: React.ReactNode; className?: string; position?: string; align?: string }) {
  return <>{children}</>
}
export function SelectTrigger(props: { id?: string; className?: string; "aria-label"?: string; children?: React.ReactNode }) {
  void props
  return null
}
export function SelectValue(props: { placeholder?: string }) {
  void props
  return null
}

function text(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return ""
  if (typeof node === "string" || typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(text).join("")
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) return text(node.props.children)
  return ""
}

function collect(children: React.ReactNode, items: { value: string; label: string; disabled?: boolean }[], meta: { label?: string; placeholder?: string }) {
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement<Record<string, unknown>>(child)) return
    if (child.type === SelectItem) {
      const p = child.props as unknown as ItemProps
      items.push({ value: p.value, label: text(p.children), disabled: p.disabled })
    } else if (child.type === SelectTrigger) {
      meta.label = (child.props["aria-label"] as string | undefined) ?? meta.label
    } else if (child.props.children) {
      collect(child.props.children as React.ReactNode, items, meta)
    }
  })
}

export function Select({
  value,
  onValueChange,
  disabled,
  children,
}: {
  value?: string
  onValueChange?: (value: string) => void
  disabled?: boolean
  children?: React.ReactNode
}) {
  const items: { value: string; label: string; disabled?: boolean }[] = []
  const meta: { label?: string } = {}
  collect(children, items, meta)
  return (
    <Selector
      label={meta.label ?? "Options"}
      isLabelHidden
      value={value}
      onChange={(next) => next != null && onValueChange?.(next)}
      options={items}
      isDisabled={disabled}
    />
  )
}
