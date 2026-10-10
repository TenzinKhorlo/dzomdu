"use client"

import * as React from "react"
import { Loader2, MoreHorizontal, Pencil, Trash2 } from "lucide-react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/animate-ui/components/radix/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/animate-ui/components/radix/dropdown-menu"
import { useConfirm } from "@/components/confirm"
import { useInfo } from "@/components/providers"
import { useTasks } from "@/components/task-provider"
import { useChatHistory } from "@/components/chat/provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
  const fieldId = React.useId()
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
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            className="relative z-10"
            disabled={busy}
            aria-label={`Actions for ${project.name}`}
          >
            {busy ? <Loader2 className="animate-spin" /> : <MoreHorizontal />}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => {
              setName(project.name)
              setError("")
              setOpen(true)
            }}
          >
            <Pencil />
            Rename project
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={() => void remove()}>
            <Trash2 />
            Delete project
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={open} onOpenChange={(value) => !busy && setOpen(value)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={rename} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Rename project</DialogTitle>
              <DialogDescription>
                The project folder and its meeting references will use the new name.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-2">
              <Label htmlFor={fieldId}>Project name</Label>
              <Input
                id={fieldId}
                autoFocus
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={busy}
              />
              {error && (
                <p role="alert" className="text-xs text-destructive">
                  {error}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !name.trim() || name.trim() === project.name}>
                {busy && <Loader2 className="animate-spin" />}Save name
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
