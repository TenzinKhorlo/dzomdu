"use client"

import * as React from "react"
import { Loader2, Plus, Search, UserRoundPlus } from "lucide-react"
import { toast } from "sonner"

import { Checkbox } from "@/components/animate-ui/components/radix/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/animate-ui/components/radix/dialog"
import { SpeakerAvatar } from "@/components/common"
import { useInfo } from "@/components/providers"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type ProjectOverview } from "@/lib/api"

export function ProjectTeamDialog({
  project,
  onChanged,
}: {
  project: ProjectOverview
  onChanged: () => void
}) {
  const { info, reload } = useInfo()
  const [open, setOpen] = React.useState(false)
  const [selected, setSelected] = React.useState<string[]>([])
  const [query, setQuery] = React.useState("")
  const [name, setName] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const id = React.useId()
  const options = [
    ...new Set([
      ...(info?.people ?? []),
      ...project.team.map((person) => person.name),
      ...selected,
    ]),
  ].sort((a, b) => a.localeCompare(b))
  const matches = options.filter((person) =>
    person.toLowerCase().includes(query.trim().toLowerCase()),
  )

  function add() {
    const value = name.trim().replace(/\s+/g, " ")
    if (!value) return
    const existing = options.find((person) => person.toLowerCase() === value.toLowerCase()) ?? value
    setSelected((names) => (names.includes(existing) ? names : [...names, existing]))
    setName("")
    setQuery("")
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError("")
    try {
      await api(`/api/projects/${encodeURIComponent(project.name)}/members`, {
        method: "PUT",
        json: { members: selected },
      })
      onChanged()
      reload()
      setOpen(false)
      toast.success("Project team updated")
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (busy) return
        if (value) {
          setSelected(project.members)
          setQuery("")
          setName("")
          setError("")
        }
        setOpen(value)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <UserRoundPlus className="size-3.5" />
          Manage team
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form className="grid gap-4" onSubmit={save}>
          <DialogHeader>
            <DialogTitle>Manage project team</DialogTitle>
            <DialogDescription>
              Choose who is assigned to {project.name}. Meeting participants and task assignees will
              still appear in the project’s activity.
            </DialogDescription>
          </DialogHeader>
          <div className="relative">
            <Search className="absolute top-2.5 left-3 size-3.5 text-muted-foreground" />
            <Input
              aria-label="Search people"
              placeholder="Search people…"
              className="pl-9"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              disabled={busy}
            />
          </div>
          <div className="max-h-64 overflow-y-auto rounded-lg border p-1">
            {matches.map((person) => (
              <label
                key={person}
                className="flex cursor-pointer items-center gap-3 rounded-md p-2.5 hover:bg-muted/60"
              >
                <Checkbox
                  checked={selected.includes(person)}
                  disabled={busy}
                  onCheckedChange={(checked) =>
                    setSelected((names) =>
                      checked === true
                        ? [...names, person]
                        : names.filter((value) => value !== person),
                    )
                  }
                />
                <SpeakerAvatar name={person} size="sm" />
                <span className="truncate text-[13px]">{person}</span>
              </label>
            ))}
            {!matches.length && (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                {options.length ? "No matching people." : "Add a team member below to get started."}
              </p>
            )}
          </div>
          <div className="grid gap-2">
            <Label htmlFor={id}>Add someone new</Label>
            <div className="flex gap-2">
              <Input
                id={id}
                placeholder="Team member’s name"
                maxLength={100}
                value={name}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault()
                    add()
                  }
                }}
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label="Add team member"
                disabled={busy || !name.trim()}
                onClick={add}
              >
                <Plus />
              </Button>
            </div>
          </div>
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button disabled={busy || selected.length > 100}>
              {busy && <Loader2 className="animate-spin" />}Save team
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
