import * as React from "react"

import { Fade } from "@/components/animate-ui/primitives/effects/fade"
import { colorFor, initials } from "@/lib/format"
import { cn } from "@/lib/utils"

export function PageHeader({
  title,
  description,
  children,
  actionsClassName,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  children?: React.ReactNode
  actionsClassName?: string
}) {
  return (
    <Fade className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 space-y-1.5">
        <h1 className="text-[22px] font-semibold">{title}</h1>
        {description && <p className="max-w-xl text-[13px] leading-relaxed text-muted-foreground">{description}</p>}
      </div>
      {children && <div className={cn("flex flex-wrap items-center gap-2", actionsClassName)}>{children}</div>}
    </Fade>
  )
}

/** Coloured initials for a person; unidentified speakers are grey. */
export function SpeakerAvatar({
  name,
  size = "md",
  className,
}: {
  name: string
  size?: "sm" | "md" | "lg"
  className?: string
}) {
  const color = colorFor(name)
  return (
    <span
      title={name}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold ring-2 ring-background",
        size === "sm" && "size-6 text-[10px]",
        size === "md" && "size-8 text-xs",
        size === "lg" && "size-11 text-sm",
        className,
      )}
      style={{
        color,
        backgroundColor: `color-mix(in oklch, ${color} 18%, var(--background))`,
      }}
    >
      {initials(name)}
    </span>
  )
}

export function AvatarStack({ names, max = 4 }: { names: string[]; max?: number }) {
  if (!names.length) return <span className="text-sm text-muted-foreground">—</span>
  const shown = names.slice(0, max)
  return (
    <div className="flex -space-x-1">
      {shown.map((n) => (
        <SpeakerAvatar key={n} name={n} size="sm" />
      ))}
      {names.length > max && (
        <span className="inline-flex size-6 items-center justify-center rounded-full bg-muted text-[10px] font-medium ring-2 ring-background">
          +{names.length - max}
        </span>
      )}
    </div>
  )
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/30 px-6 py-12 text-center",
        className,
      )}
    >
      <div className="flex size-10 items-center justify-center rounded-lg border bg-background shadow-[var(--shadow-card)]">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        {description && (
          <p className="mx-auto max-w-sm text-[13px] text-muted-foreground">{description}</p>
        )}
      </div>
      {children}
    </div>
  )
}

/** A small figure card: label on top, the value, and a quiet hint on the right. */
export function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  className,
}: {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  className?: string
}) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-card px-4 py-3.5 shadow-[var(--shadow-card)]",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-medium">{label}</span>
        {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
      </div>
      {/* the hint moves under the value when the tile is narrow, never squeezing it */}
      <div className="mt-2 flex flex-wrap items-end justify-between gap-x-2 gap-y-1">
        <span className="text-xl leading-none font-semibold tracking-[-0.02em] whitespace-nowrap tabular-nums">
          {value}
        </span>
        {hint && <span className="min-w-0 truncate text-xs text-muted-foreground">{hint}</span>}
      </div>
    </div>
  )
}
