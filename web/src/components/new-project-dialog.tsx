"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import { Icon } from "@astryxdesign/core/Icon"
import { TextInput } from "@astryxdesign/core/TextInput"
import { FolderPlus } from "lucide-react"
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
import { api } from "@/lib/api"

/** Creates a project folder in the vault. `children` is the button that opens the dialog. */
export function NewProjectDialog({
  children,
  onCreated,
}: {
  children: React.ReactNode
  onCreated?: (name: string) => void
}) {
  const { reload: reloadInfo } = useInfo()
  const [open, setOpen] = React.useState(false)
  const [name, setName] = React.useState("")
  const [busy, setBusy] = React.useState(false)

  async function create(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    try {
      const res = await api<{ name: string; created: boolean }>("/api/projects", {
        method: "POST",
        json: { name },
      })
      toast.success(res.created ? `Project “${res.name}” created` : `“${res.name}” already exists`)
      reloadInfo() // refreshes the project lists across the app
      onCreated?.(res.name)
      setOpen(false)
      setName("")
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={create} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              A project is a folder in your vault with an overview note and its meetings. You can
              add goals and a glossary to the overview later.
            </DialogDescription>
          </DialogHeader>
          <TextInput
            label="Project name"
            hasAutoFocus
            placeholder="e.g. Solar Microgrid"
            value={name}
            onChange={setName}
          />
          <DialogFooter>
            <Button
              type="submit"
              variant="primary"
              label="Create project"
              icon={<Icon icon={FolderPlus} />}
              isLoading={busy}
              isDisabled={!name.trim()}
            />
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
