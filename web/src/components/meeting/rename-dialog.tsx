"use client"

import * as React from "react"
import { Loader2, Pencil } from "lucide-react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/animate-ui/components/radix/dialog"
import { useInfo } from "@/components/providers"
import { useTasks } from "@/components/task-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
  const fieldId = React.useId()
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
        <Button
          variant="ghost"
          size="icon-sm"
          className="shrink-0 text-muted-foreground"
          aria-label="Rename meeting"
          title="Rename meeting"
        >
          <Pencil className="size-3.5" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={save} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Rename meeting</DialogTitle>
            <DialogDescription>
              Choose a name that makes this meeting easy to find.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor={fieldId}>Meeting title</Label>
            <Input
              id={fieldId}
              autoFocus
              maxLength={120}
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
            <Button type="button" variant="outline" disabled={busy} onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={busy || !normalized || normalized.length > 120 || normalized === title}
            >
              {busy && <Loader2 className="animate-spin" />}Save title
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
