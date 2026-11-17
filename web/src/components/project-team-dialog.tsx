"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput"
import { Icon } from "@astryxdesign/core/Icon"
import { IconButton } from "@astryxdesign/core/IconButton"
import { TextInput } from "@astryxdesign/core/TextInput"
import { Plus, UserRoundPlus } from "lucide-react"
import { toast } from "@/lib/toast"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/dialog"
import { SpeakerAvatar } from "@/components/common"
import { useInfo } from "@/components/providers"
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
        <Button variant="secondary" size="sm" label="Manage team" icon={<Icon icon={UserRoundPlus} />} />
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
          <TextInput
            label="Search people"
            isLabelHidden
            placeholder="Search people…"
            value={query}
            onChange={setQuery}
            isDisabled={busy}
          />
          <div className="max-h-64 overflow-y-auto rounded-lg border p-1">
            {matches.map((person) => (
              <div key={person} className="flex items-center gap-3 rounded-md p-2.5 hover:bg-muted/60">
                <CheckboxInput
                  label={person}
                  isLabelHidden
                  value={selected.includes(person)}
                  isDisabled={busy}
                  onChange={(checked) =>
                    setSelected((names) =>
                      checked ? [...names, person] : names.filter((value) => value !== person),
                    )
                  }
                />
                <SpeakerAvatar name={person} size="sm" />
                <span className="truncate text-[13px]">{person}</span>
              </div>
            ))}
            {!matches.length && (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                {options.length ? "No matching people." : "Add a team member below to get started."}
              </p>
            )}
          </div>
          <div
            className="flex items-end gap-2"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault()
                add()
              }
            }}
          >
            <div className="flex-1">
              <TextInput
                label="Add someone new"
                placeholder="Team member’s name"
                value={name}
                isDisabled={busy}
                onChange={(value) => setName(value.slice(0, 100))}
              />
            </div>
            <IconButton
              variant="secondary"
              label="Add team member"
              icon={<Icon icon={Plus} />}
              isDisabled={busy || !name.trim()}
              onClick={add}
            />
          </div>
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button label="Cancel" variant="secondary" isDisabled={busy} onClick={() => setOpen(false)} />
            <Button type="submit" variant="primary" label="Save team" isLoading={busy} isDisabled={selected.length > 100} />
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
