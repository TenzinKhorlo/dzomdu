"use client"

import * as React from "react"
import { Card as AstryxCard } from "@astryxdesign/core/Card"
import { Heading } from "@astryxdesign/core/Heading"
import { Text } from "@astryxdesign/core/Text"

import { cn } from "@/lib/utils"

/**
 * Card and its parts. The surface (fill, border, radius) is Astryx's Card, so it follows the
 * theme; the parts lay out a header / content / footer inside it with the app's 20px rhythm.
 */
export function Card({ className, children }: { className?: string; children?: React.ReactNode }) {
  return (
    <AstryxCard padding={0} className={cn("flex flex-col gap-5 py-5", className)}>
      {children}
    </AstryxCard>
  )
}

export function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-1.5 px-5 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-5",
        className,
      )}
      {...props}
    />
  )
}

export function CardTitle({ className, children }: { className?: string; children?: React.ReactNode }) {
  return (
    <Heading level={3} className={className}>
      {children}
    </Heading>
  )
}

export function CardDescription({ className, children }: { className?: string; children?: React.ReactNode }) {
  return (
    <Text type="supporting" color="secondary" display="block" className={className}>
      {children}
    </Text>
  )
}

export function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn("col-start-2 row-span-2 row-start-1 self-start justify-self-end", className)}
      {...props}
    />
  )
}

export function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn("px-5", className)} {...props} />
}

export function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-footer" className={cn("flex items-center px-5 [.border-t]:pt-5", className)} {...props} />
}
