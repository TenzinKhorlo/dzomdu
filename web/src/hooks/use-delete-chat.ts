"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { toast } from "sonner"

import { useChatHistory } from "@/components/chat/provider"
import { useConfirm } from "@/components/confirm"
import { api, type ChatSummary } from "@/lib/api"

export function useDeleteChat() {
  const confirm = useConfirm()
  const router = useRouter()
  const { reload, startNewChat } = useChatHistory()
  const [deleting, setDeleting] = React.useState<string | null>(null)

  async function deleteChat(chat: ChatSummary) {
    if (deleting) return
    setDeleting(chat.id)
    try {
      const accepted = await confirm({
        title: "Delete conversation?",
        description: `“${chat.title}” and its chat history will be permanently deleted. Your meeting notes are kept.`,
        confirmLabel: "Delete conversation",
        destructive: true,
      })
      if (!accepted) return
      await api(`/api/chats/${encodeURIComponent(chat.id)}`, { method: "DELETE" })
      reload()
      const current = new URLSearchParams(window.location.search).get("id")
      if (window.location.pathname.startsWith("/chat") && current === chat.id) {
        startNewChat()
        router.replace("/chat/")
      }
      toast.success("Conversation deleted")
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setDeleting(null)
    }
  }
  return { deleteChat, deleting }
}
