"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { Icon } from "@astryxdesign/core/Icon"
import { IconButton } from "@astryxdesign/core/IconButton"
import { TextInput } from "@astryxdesign/core/TextInput"
import { Pencil } from "lucide-react"
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
import { useInfo } from "@/components/providers"
import { useTasks } from "@/components/task-provider"
import { api } from "@/lib/api"

export function RenameMeetingDialog({
  id,
  title,
  onRenamed,
}: {
  id: string
  title: string
  onRenamed: () => void
}) {
  const [open, setOpen] = React.useState(false)
  const [name, setName] = React.useState(title)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const { reload: reloadInfo } = useInfo()
  const { reload: reloadTasks } = useTasks()
  const normalized = name.trim().replace(/\s+/g, " ")

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (busy || !normalized || normalized.length > 120) return
    setBusy(true)
    setError("")
    try {
      await api(`/api/meetings/${encodeURIComponent(id)}`, {
        method: "PATCH",
        json: { title: normalized },
      })
      setOpen(false)
      reloadInfo()
      reloadTasks()
      onRenamed()
      toast.success("Meeting renamed")
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
          setName(title)
          setError("")
        }
        setOpen(value)
      }}
    >
      <DialogTrigger asChild>
        <IconButton variant="ghost" size="sm" label="Rename meeting" tooltip="Rename meeting" icon={<Icon icon={Pencil} />} />
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={save} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Rename meeting</DialogTitle>
            <DialogDescription>
              Choose a name that makes this meeting easy to find.
            </DialogDescription>
          </DialogHeader>
          <TextInput
            label="Meeting title"
            hasAutoFocus
            value={name}
            onChange={(value) => setName(value.slice(0, 120))}
            isDisabled={busy}
            status={error ? { type: "error", message: error } : undefined}
          />
          <DialogFooter>
            <Button label="Cancel" variant="secondary" isDisabled={busy} onClick={() => setOpen(false)} />
            <Button
              type="submit"
              variant="primary"
              label="Save title"
              isLoading={busy}
              isDisabled={!normalized || normalized === title}
            />
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
