"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { MoreMenu } from "@astryxdesign/core/MoreMenu"
import { TextInput } from "@astryxdesign/core/TextInput"
import { Pencil, Trash2 } from "lucide-react"

import { useChatHistory } from "@/components/chat/provider"
import { useConfirm } from "@/components/confirm"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/dialog"
import { useInfo } from "@/components/providers"
import { useTasks } from "@/components/task-provider"
import { toast } from "@/lib/toast"
import { api, type Project } from "@/lib/api"

export function ProjectActions({
  project,
  onChanged,
}: {
  project: Project
  onChanged: (name?: string) => void
}) {
  const confirm = useConfirm()
  const { reload: reloadInfo } = useInfo()
  const { reload: reloadTasks } = useTasks()
  const { chats, reload: reloadChats } = useChatHistory()
  const [open, setOpen] = React.useState(false)
  const [name, setName] = React.useState(project.name)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const path = `/api/projects/${encodeURIComponent(project.name)}`

  async function rename(event: React.FormEvent) {
    event.preventDefault()
    if (busy || !name.trim()) return
    setBusy(true)
    setError("")
    try {
      const result = await api<{ name: string }>(path, {
        method: "PATCH",
        json: { name },
      })
      setOpen(false)
      reloadInfo()
      reloadTasks()
      reloadChats()
      onChanged(result.name)
      toast.success(`Project renamed to “${result.name}”`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (busy) return
    setBusy(true)
    try {
      const details = await api<{ meetings: number; meeting_ids: string[] }>(path)
      const related = details.meetings
        ? `All ${details.meetings} related meeting${details.meetings === 1 ? "" : "s"}, their notes, and recordings saved by Dzomdu will be permanently deleted. `
        : "There are no saved meetings in this project. "
      const accepted = await confirm({
        title: `Delete “${project.name}”?`,
        description:
          related +
          (chats.some((chat) => chat.project === project.name)
            ? "Linked conversations will be kept without a project link. "
            : "") +
          "The project folder and its contents will also be deleted. This cannot be undone. Do you want to proceed?",
        confirmLabel: details.meetings ? "Delete project and meetings" : "Delete project",
        destructive: true,
      })
      if (!accepted) return
      await api(path, {
        method: "DELETE",
        json: { meeting_ids: details.meeting_ids },
      })
      reloadInfo()
      reloadTasks()
      reloadChats()
      onChanged()
      toast.success(`Project “${project.name}” deleted`)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <MoreMenu
        label={`Actions for ${project.name}`}
        size="sm"
        alignment="end"
        isDisabled={busy}
        items={[
          {
            label: "Rename project",
            icon: Pencil,
            onClick: () => {
              setName(project.name)
              setError("")
              setOpen(true)
            },
          },
          { type: "divider" },
          { label: "Delete project", icon: Trash2, variant: "destructive", onClick: () => void remove() },
        ]}
      />
      <Dialog open={open} onOpenChange={(value) => !busy && setOpen(value)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={rename} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Rename project</DialogTitle>
              <DialogDescription>
                The project folder and its meeting references will use the new name.
              </DialogDescription>
            </DialogHeader>
            <TextInput
              label="Project name"
              hasAutoFocus
              value={name}
              onChange={(value) => setName(value.slice(0, 100))}
              isDisabled={busy}
              status={error ? { type: "error", message: error } : undefined}
            />
            <DialogFooter>
              <Button label="Cancel" variant="secondary" isDisabled={busy} onClick={() => setOpen(false)} />
              <Button
                type="submit"
                variant="primary"
                label="Save name"
                isLoading={busy}
                isDisabled={!name.trim() || name.trim() === project.name}
              />
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
