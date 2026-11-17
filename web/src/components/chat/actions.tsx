"use client"

import * as React from "react"
import { Button } from "@astryxdesign/core/Button"
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem,
  DropdownMenuSubMenu,
} from "@astryxdesign/core/DropdownMenu"
import { Icon } from "@astryxdesign/core/Icon"
import { IconButton } from "@astryxdesign/core/IconButton"
import { TextInput } from "@astryxdesign/core/TextInput"
import { Check, Folder, FolderInput, Loader2, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from "lucide-react"

import { useChatHistory } from "@/components/chat/provider"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/dialog"
import { useInfo } from "@/components/providers"
import { useDeleteChat } from "@/hooks/use-delete-chat"
import { api, type ChatSummary } from "@/lib/api"
import { toast } from "@/lib/toast"

export function ChatActions({ chat }: { chat: ChatSummary }) {
  const { reload } = useChatHistory()
  const { projects, info } = useInfo()
  const projectNames = projects?.map((project) => project.name) ?? info?.projects ?? []
  const { deleteChat, deleting } = useDeleteChat()
  const [open, setOpen] = React.useState(false)
  const [name, setName] = React.useState(chat.title)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
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
      <DropdownMenu
        placement="below"
        alignment="end"
        menuWidth={208}
        renderTrigger={(props) => (
          <IconButton
            {...props}
            variant="ghost"
            size="sm"
            isDisabled={pending}
            label={`Actions for ${chat.title}`}
            tooltip="Conversation actions"
            icon={<Icon icon={pending ? Loader2 : MoreHorizontal} />}
          />
        )}
      >
        <DropdownMenuItem
          icon={Pencil}
          label="Rename"
          onClick={() => {
            setName(chat.title)
            setError("")
            setOpen(true)
          }}
        />
        <DropdownMenuItem
          icon={chat.pinned ? PinOff : Pin}
          label={chat.pinned ? "Unpin" : "Pin to top"}
          onClick={() =>
            void update(
              { pinned: !chat.pinned },
              chat.pinned ? "Conversation unpinned" : "Conversation pinned",
            )
          }
        />
        <DropdownMenuDivider />
        <DropdownMenuSubMenu label="Move to project" icon={FolderInput} menuWidth={224}>
          <DropdownMenuItem
            icon={Folder}
            label="No project"
            isDisabled={!chat.project}
            endContent={!chat.project ? <Icon icon={Check} /> : undefined}
            onClick={() => void update({ project: null }, "Project link removed")}
          />
          <DropdownMenuDivider />
          {projectNames.map((project) => (
            <DropdownMenuItem
              key={project}
              icon={Folder}
              label={project}
              isDisabled={chat.project === project}
              endContent={chat.project === project ? <Icon icon={Check} /> : undefined}
              onClick={() => void update({ project }, `Conversation moved to “${project}”`)}
            />
          ))}
          {!projectNames.length && (
            <DropdownMenuItem isDisabled label="Create a project from Projects first" />
          )}
        </DropdownMenuSubMenu>
        <DropdownMenuDivider />
        <DropdownMenuItem
          variant="destructive"
          icon={Trash2}
          label="Delete"
          onClick={() => void deleteChat(chat)}
        />
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
            <TextInput
              label="Conversation name"
              hasAutoFocus
              value={name}
              isDisabled={busy}
              onChange={(value) => setName(value.slice(0, 80))}
              status={error ? { type: "error", message: error } : undefined}
            />
            <DialogFooter>
              <Button label="Cancel" variant="secondary" isDisabled={busy} onClick={() => setOpen(false)} />
              <Button
                type="submit"
                variant="primary"
                label="Save name"
                isLoading={busy}
                isDisabled={!name.trim() || name.trim() === chat.title}
              />
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
