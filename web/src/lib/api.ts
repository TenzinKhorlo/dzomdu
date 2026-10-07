// Typed client for the Dzomdu Python API.
//
// In production the dashboard is served by the API itself (same origin). During `npm run dev`
// NEXT_PUBLIC_DZOMDU_API points at the API on :8765 (see .env.development).

export const API_BASE = (process.env.NEXT_PUBLIC_DZOMDU_API ?? "").replace(/\/$/, "")

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const res = await fetch(API_BASE + path, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json" } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  const isJson = res.headers.get("content-type")?.includes("json")
  const data = isJson ? await res.json() : null
  if (!res.ok) {
    throw new ApiError(data?.detail ?? `${res.status} ${res.statusText}`, res.status)
  }
  return data as T
}

export function wsUrl(path: string): string {
  const base = API_BASE || window.location.origin
  return base.replace(/^http/, "ws") + path
}

export const apiUrl = (path: string) => API_BASE + path

// -- types ------------------------------------------------------------------------------------

export type Task = {
  line: number
  done: boolean
  text: string
  owner: string | null
  due: string | null
  turn: string | null
  editable: boolean
}

export type OpenTask = Task & { meeting_id: string; meeting_title: string; date: string }

export type MeetingRow = {
  id: string
  title: string
  date: string
  project: string | null
  duration: number
  people: string[]
  unidentified: number
  summary: string | null
  open_actions: number
  has_note: boolean
}

export type ActiveSession = { id: string; title: string; state: SessionState }

export type Dashboard = {
  totals: {
    meetings: number
    hours: number
    voices: number
    open_actions: number
    done_actions: number
  }
  period: {
    days: number
    meetings: number
    minutes: number
    meetings_delta: number | null
    minutes_delta: number | null
  }
  activity: { date: string; meetings: number; minutes: number }[]
  speakers: { name: string; minutes: number; meetings: number }[]
  recent: MeetingRow[]
  actions: OpenTask[]
  projects: { name: string; meetings: number; minutes: number; last: string | null }[]
  active: ActiveSession[]
}

export type Turn = {
  id: string
  speaker: string
  label: string
  start: number
  end: number
  text: string
}

export type MeetingDetail = MeetingRow & {
  attendees: string[]
  speakers: {
    cluster: string
    label: string
    name: string | null
    status: string
    talk_seconds: number
    turns: number
  }[]
  turns: Turn[]
  decisions: { decision: string; source_turns: string[] }[]
  topics: { title: string; points: string[]; source_turns: string[] }[]
  open_questions: string[]
  tasks: Task[]
  note: { path: string; markdown: string; html: string; obsidian_url: string } | null
  models: { asr: string; diarization: string }
}

export type SessionState =
  | "new"
  | "recording"
  | "processing"
  | "review"
  | "summarizing"
  | "done"
  | "error"
  | "cancelled"

export type ReviewSpeaker = {
  cluster: string
  status: "auto" | "suggested" | "unknown" | "confirmed"
  name: string | null
  suggestion: string | null
  score: number | null
  label: string
  unknown_label: string
  talk_seconds: number
  turns: number
  quotes: { start: number; text: string }[]
  has_clip: boolean
}

export type LiveSegment = {
  id: number
  start: number
  end: number
  speaker: string | null
  text: string
}

export type Session = {
  id: string
  kind: "recording" | "upload" | "existing"
  state: SessionState
  meta: {
    title: string | null
    project: string | null
    attendees: string[]
    template: string | null
    instructions: string
    num_speakers: number | null
    live: boolean
    summarize: boolean
  }
  messages: string[]
  error: string | null
  warning: string | null
  elapsed: number
  live: LiveSegment[]
  meeting_id?: string
  title?: string
  duration?: number
  speakers?: ReviewSpeaker[]
  note_path?: string
}

export type Info = {
  templates: { key: string; name: string; description: string }[]
  default_template: string
  people: string[]
  projects: string[]
  vault: string
  models: { asr: string; diarization: string; llm: string }
  status: {
    llm: { ok: boolean; detail: string }
    asr: { ok: boolean }
    diarization: { ok: boolean }
  }
  recovered: string[]
}

export type Voice = {
  name: string
  samples: number
  consent: boolean
  minutes: number
  meetings: number
  role: string
  organisation: string
  bio: string
}

export type Project = {
  name: string
  meetings: number
  minutes: number
  last: string | null
  overview: string
}
