"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput"
import { Icon } from "@astryxdesign/core/Icon"
import { TextInput } from "@astryxdesign/core/TextInput"
import { BookOpen, Check, ChevronDown } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/dialog"
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
          isDisabled={disabled}
          label={label}
          icon={<Icon icon={BookOpen} />}
          endContent={<Icon icon={ChevronDown} />}
        />
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
        <TextInput
          label="Find a meeting"
          isLabelHidden
          placeholder="Find a meeting or project…"
          value={query}
          onChange={setQuery}
        />
        <div className="max-h-[45svh] space-y-1 overflow-y-auto">
          {filtered.map((meeting) => (
            <div key={meeting.id} className="rounded-lg px-3 py-2 hover:bg-accent">
              <CheckboxInput
                label={meeting.title}
                description={`${shortDate(meeting.date)}${meeting.project ? ` · ${meeting.project}` : ""}`}
                value={chosen.includes(meeting.id)}
                isDisabled={!chosen.includes(meeting.id) && chosen.length >= 50}
                onChange={(checked) =>
                  setChosen(checked ? [...chosen, meeting.id] : chosen.filter((id) => id !== meeting.id))
                }
              />
            </div>
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
            variant="primary"
            label="Use these notes"
            onClick={() => {
              onChange(chosen)
              setOpen(false)
            }}
          />
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
