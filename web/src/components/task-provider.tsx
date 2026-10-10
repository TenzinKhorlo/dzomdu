"use client"

import * as React from "react"

import { useApi } from "@/hooks/use-api"
import type { OpenTask } from "@/lib/api"

export function localDate(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}

export function reminderIsDue(task: OpenTask) {
  return !task.done && !!task.reminder_date && task.reminder_date <= localDate()
}

const TaskContext = React.createContext<{
  tasks: OpenTask[]
  loading: boolean
  error?: Error
  reload: () => void
}>({ tasks: [], loading: true, reload: () => {} })

export function TaskProvider({ children }: { children: React.ReactNode }) {
  const { data, loading, error, reload } = useApi<OpenTask[]>("/api/tasks", {
    interval: 60000,
  })
  return (
    <TaskContext.Provider value={{ tasks: data ?? [], loading, error, reload }}>
      {children}
    </TaskContext.Provider>
  )
}

export const useTasks = () => React.useContext(TaskContext)
