"use client"

import * as React from "react"
import { BookOpen, Check, ChevronDown, Search } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/animate-ui/components/radix/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { MeetingRow } from "@/lib/api"
import { shortDate } from "@/lib/format"
import { cn } from "@/lib/utils"

export function SourcesPicker({
  meetings,
  selected,
  onChange,
  locked,
  disabled,
}: {
  meetings: MeetingRow[]
  selected: string[]
  onChange: (ids: string[]) => void
  locked: boolean
  disabled: boolean
}) {
  const [open, setOpen] = React.useState(false)
  const [chosen, setChosen] = React.useState(selected)
  const [query, setQuery] = React.useState("")
  const label =
    selected.length === 1
      ? (meetings.find((m) => m.id === selected[0])?.title ?? "1 meeting")
      : selected.length
        ? `${selected.length} meetings`
        : "All meeting notes"
  if (locked)
    return (
      <span
        className="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground"
        title={`${label}. Start a new chat to change the selection.`}
      >
        <BookOpen className="size-3.5 shrink-0" />
        <span className="max-w-48 truncate">{label}</span>
      </span>
    )
  const filtered = meetings.filter((m) =>
    `${m.title} ${m.project ?? ""}`.toLowerCase().includes(query.toLowerCase()),
  )
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value)
        if (value) {
          setChosen(selected)
          setQuery("")
        }
      }}
    >
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="min-w-0 max-w-64 px-2 text-xs text-muted-foreground"
        >
          <BookOpen className="size-3.5 shrink-0" />
          <span className="truncate">{label}</span>
          <ChevronDown className="size-3 shrink-0" />
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-card sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Choose your sources</DialogTitle>
          <DialogDescription>
            Search all your notes, or focus this conversation on specific meetings.
          </DialogDescription>
        </DialogHeader>
        <button
          type="button"
          onClick={() => setChosen([])}
          className={cn(
            "flex items-center justify-between rounded-xl border px-4 py-3 text-left",
            !chosen.length && "border-brand/35 bg-brand/5",
          )}
        >
          <span className="flex items-center gap-2 text-[13px] font-medium">
            <BookOpen className="size-4 text-brand" />
            All meeting notes
          </span>
          {!chosen.length && <Check className="size-4 text-brand" />}
        </button>
        <div className="relative">
          <Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" />
          <Input
            aria-label="Find a meeting"
            placeholder="Find a meeting or project…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="max-h-[45svh] space-y-1 overflow-y-auto">
          {filtered.map((meeting) => (
            <label
              key={meeting.id}
              className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-3 hover:bg-accent"
            >
              <input
                type="checkbox"
                className="size-4 shrink-0 accent-brand"
                checked={chosen.includes(meeting.id)}
                disabled={!chosen.includes(meeting.id) && chosen.length >= 50}
                onChange={(e) =>
                  setChosen(
                    e.target.checked
                      ? [...chosen, meeting.id]
                      : chosen.filter((id) => id !== meeting.id),
                  )
                }
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{meeting.title}</span>
                <span className="text-xs text-muted-foreground">
                  {shortDate(meeting.date)}
                  {meeting.project && ` · ${meeting.project}`}
                </span>
              </span>
            </label>
          ))}
          {!filtered.length && (
            <p className="py-6 text-center text-[13px] text-muted-foreground">No meetings found.</p>
          )}
        </div>
        <DialogFooter className="items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            {chosen.length
              ? `${chosen.length} selected · up to 50`
              : `${meetings.length} meetings in your library`}
          </p>
          <Button
            onClick={() => {
              onChange(chosen)
              setOpen(false)
            }}
          >
            Use these notes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
