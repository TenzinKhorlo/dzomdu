"use client"

import * as React from "react"
import {
  Check,
  Folder,
  FolderInput,
  Loader2,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react"
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
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/animate-ui/components/radix/dropdown-menu"
import { useChatHistory } from "@/components/chat/provider"
import { useInfo } from "@/components/providers"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useDeleteChat } from "@/hooks/use-delete-chat"
import { api, type ChatSummary } from "@/lib/api"

export function ChatActions({ chat, children }: { chat: ChatSummary; children?: React.ReactNode }) {
  const { reload } = useChatHistory()
  const { projects, info } = useInfo()
  const projectNames = projects?.map((project) => project.name) ?? info?.projects ?? []
  const { deleteChat, deleting } = useDeleteChat()
  const [open, setOpen] = React.useState(false)
  const [name, setName] = React.useState(chat.title)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const fieldId = React.useId()
  const pending = busy || deleting !== null

  async function update(
    changes: Partial<Pick<ChatSummary, "title" | "pinned" | "project">>,
    message: string,
  ) {
    if (pending) return
    setBusy(true)
    setError("")
    try {
      await api(`/api/chats/${encodeURIComponent(chat.id)}`, { method: "PATCH", json: changes })
      setOpen(false)
      reload()
      toast.success(message)
    } catch (err) {
      if ("title" in changes) setError((err as Error).message)
      else toast.error((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={pending}>
          {children ?? (
            <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${chat.title}`}>
              {pending ? <Loader2 className="animate-spin" /> : <MoreHorizontal />}
            </Button>
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem
            onSelect={() => {
              setName(chat.title)
              setError("")
              setOpen(true)
            }}
          >
            <Pencil />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() =>
              void update(
                { pinned: !chat.pinned },
                chat.pinned ? "Conversation unpinned" : "Conversation pinned",
              )
            }
          >
            {chat.pinned ? <PinOff /> : <Pin />}
            {chat.pinned ? "Unpin" : "Pin to top"}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="gap-2">
              <FolderInput className="size-4 shrink-0 text-muted-foreground" />
              Move to project
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-72 w-56 overflow-y-auto">
              <DropdownMenuItem
                disabled={!chat.project}
                onSelect={() => void update({ project: null }, "Project link removed")}
              >
                <Folder />
                No project{!chat.project && <Check className="ml-auto size-3.5" />}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {projectNames.map((project) => (
                <DropdownMenuItem
                  key={project}
                  disabled={chat.project === project}
                  onSelect={() => void update({ project }, `Conversation moved to “${project}”`)}
                >
                  <Folder />
                  <span className="truncate">{project}</span>
                  {chat.project === project && <Check className="ml-auto size-3.5" />}
                </DropdownMenuItem>
              ))}
              {!projectNames.length && (
                <p className="px-2 py-1.5 text-xs text-muted-foreground">
                  Create a project from Projects first.
                </p>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={() => void deleteChat(chat)}>
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={open} onOpenChange={(value) => !busy && setOpen(value)}>
        <DialogContent className="sm:max-w-md">
          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (name.trim()) void update({ title: name.trim() }, "Conversation renamed")
            }}
          >
            <DialogHeader>
              <DialogTitle>Rename conversation</DialogTitle>
              <DialogDescription>
                Give this conversation a name that’s easy to find.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-2">
              <Label htmlFor={fieldId}>Conversation name</Label>
              <Input
                id={fieldId}
                autoFocus
                maxLength={80}
                value={name}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
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
              <Button type="submit" disabled={busy || !name.trim() || name.trim() === chat.title}>
                {busy && <Loader2 className="animate-spin" />}Save name
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
