"use client"

import * as React from "react"

import { useApi } from "@/hooks/use-api"
import type { ChatSummary } from "@/lib/api"

type ChatHistory = {
  chats: ChatSummary[]
  loading: boolean
  error?: Error
  reload: () => void
  newChatRevision: number
  startNewChat: () => void
}

const ChatHistoryContext = React.createContext<ChatHistory | null>(null)

export function ChatHistoryProvider({ children }: { children: React.ReactNode }) {
  const history = useApi<ChatSummary[]>("/api/chats", { interval: 30000 })
  const [newChatRevision, setNewChatRevision] = React.useState(0)
  const startNewChat = React.useCallback(() => setNewChatRevision((value) => value + 1), [])

  return (
    <ChatHistoryContext.Provider
      value={{
        chats: history.data ?? [],
        loading: history.loading,
        error: history.error,
        reload: history.reload,
        newChatRevision,
        startNewChat,
      }}
    >
      {children}
    </ChatHistoryContext.Provider>
  )
}

export function useChatHistory() {
  const context = React.useContext(ChatHistoryContext)
  if (!context) throw new Error("useChatHistory requires ChatHistoryProvider")
  return context
}
