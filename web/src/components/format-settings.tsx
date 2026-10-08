"use client"

import * as React from "react"
import { Loader2, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/animate-ui/components/radix/dialog"
import { useConfirm } from "@/components/confirm"
import { useInfo } from "@/components/providers"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useApi } from "@/hooks/use-api"
import { api } from "@/lib/api"

type Section = {
  title: string
  type: "text" | "list" | "items"
  description: string
  key?: string
}

type Format = {
  key: string
  name: string
  description: string
  instructions: string
  body: string
  sections: Section[]
  builtin: boolean
  edited: boolean
  default: boolean
}

type Draft = Pick<
  Format,
  "name" | "description" | "instructions" | "body" | "sections"
>

const SECTION_TYPES: [Section["type"], string][] = [
  ["text", "A short passage"],
  ["list", "A list of points"],
  ["items", "Headline + sentence pairs"],
]

// what a layout calls an extra field, matching the name the server derives from the title
const sectionKey = (title: string) =>
  title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40)

const VARIABLES: [string, string][] = [
  [
    "{{ meeting.date_long }}, {{ meeting.minutes }}",
    "the date (January 14, 2026) and length in minutes",
  ],
  ["{{ role(name) }}", "the role in a person's profile, such as AD"],
  ["{{ loop.index }}", "1, 2, 3… inside a for loop, for numbered lists"],
  ["{{ notes.summary }}", "the summary paragraph"],
  ["{% for d in notes.decisions %} … {{ d.decision }}", "each decision"],
  [
    "{% for a in notes.action_items %} … {{ task(a) }}",
    "each action item, ready for the Tasks plugin",
  ],
  [
    "{% for t in notes.topics %} … {{ t.title }}, {{ t.points }}",
    "each topic and its points",
  ],
  [
    "{{ notes.open_questions }}, {{ notes.next_meeting }}",
    "open questions, next meeting",
  ],
  ["{{ cite(item) }}", "links an item to the moment it was said"],
  ["{{ person(name) }}", "a [[link]] for a known person"],
  [
    "{{ meeting.title }}, .project, .duration, .attendees",
    "details of the meeting",
  ],
]

function FormatDialog({
  open,
  onOpenChange,
  format,
  starter,
  onSaved,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  format: Format | null // null = a new format
  starter: Format | undefined
  onSaved: () => void
}) {
  const [busy, setBusy] = React.useState(false)
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        {/* mounted only while open, so the form starts from the right format every time */}
        {open && (
          <FormatForm
            format={format}
            starter={starter}
            busy={busy}
            setBusy={setBusy}
            onSaved={() => {
              onSaved()
              onOpenChange(false)
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function FormatForm({
  format,
  starter,
  busy,
  setBusy,
  onSaved,
}: {
  format: Format | null
  starter: Format | undefined
  busy: boolean
  setBusy: (b: boolean) => void
  onSaved: () => void
}) {
  // a new format begins as a copy of the starter, so it starts from something that works
  const [draft, setDraft] = React.useState<Draft>(() => {
    const from = format ?? starter
    return {
      name: format ? format.name : "",
      description: format ? format.description : "",
      instructions: from?.instructions ?? "",
      body: from?.body ?? "",
      // keep each field's key, so a copied or edited layout still finds its fields
      sections: (from?.sections ?? []).map(
        ({ key, title, type, description }) => ({
          key,
          title,
          type,
          description,
        }),
      ),
    }
  })
  const [error, setError] = React.useState<string | null>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) =>
    setDraft((d) => ({ ...d, [k]: v }))
  const setSection = (i: number, sec: Section) =>
    set(
      "sections",
      draft.sections.map((x, j) => (j === i ? sec : x)),
    )

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api(
        format
          ? `/api/templates/${encodeURIComponent(format.key)}`
          : "/api/templates",
        {
          method: format ? "PUT" : "POST",
          json: draft,
        },
      )
      toast.success(format ? "Format saved" : "Format created")
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={save} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>
          {format ? `Edit “${format.name}”` : "New minutes format"}
        </DialogTitle>
        <DialogDescription>
          The instructions tell the AI how to write. The layout decides which
          sections the note has and in what order.
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="fmt-name">Name</Label>
          <Input
            id="fmt-name"
            required
            autoFocus
            placeholder="e.g. Weekly sync"
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="fmt-desc">Short description</Label>
          <Input
            id="fmt-desc"
            placeholder="Shown in the format list"
            value={draft.description}
            onChange={(e) => set("description", e.target.value)}
          />
        </div>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="fmt-instr">Instructions for the AI</Label>
        <Textarea
          id="fmt-instr"
          rows={4}
          placeholder="e.g. Audience is the finance team. Keep the summary to three sentences and list every number that was mentioned."
          value={draft.instructions}
          onChange={(e) => set("instructions", e.target.value)}
        />
      </div>
      <div className="grid gap-2">
        <Label>Extra things for the AI to pick out</Label>
        <p className="text-xs text-muted-foreground">
          Beyond the summary, topics, decisions and actions, the AI can also
          fill in your own fields, such as a meeting purpose or key takeaways.
          Show them in the layout with the name under each field.
        </p>
        {draft.sections.map((sec, i) => (
          <div key={i} className="grid gap-2 rounded-lg border p-3">
            <div className="grid gap-2 sm:grid-cols-[1fr_12rem_auto]">
              <Input
                aria-label="Field title"
                placeholder="e.g. Meeting purpose"
                value={sec.title}
                onChange={(e) =>
                  setSection(i, { ...sec, title: e.target.value })
                }
              />
              <Select
                value={sec.type}
                onValueChange={(v) =>
                  setSection(i, { ...sec, type: v as Section["type"] })
                }
              >
                <SelectTrigger aria-label="Field type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SECTION_TYPES.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Remove field"
                onClick={() =>
                  set(
                    "sections",
                    draft.sections.filter((_, j) => j !== i),
                  )
                }
              >
                <Trash2 />
              </Button>
            </div>
            <Input
              aria-label="What to put in this field"
              placeholder="What should the AI write here?"
              value={sec.description}
              onChange={(e) =>
                setSection(i, { ...sec, description: e.target.value })
              }
            />
            {(sec.key ?? sectionKey(sec.title)) && (
              <p className="text-xs text-muted-foreground">
                In the layout:{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono">
                  {`{{ notes.extra.${sec.key ?? sectionKey(sec.title)} }}`}
                </code>
                {sec.type !== "text" && " (use a for loop)"}
              </p>
            )}
          </div>
        ))}
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              set("sections", [
                ...draft.sections,
                { title: "", type: "text", description: "" },
              ])
            }
          >
            <Plus />
            Add a field
          </Button>
        </div>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="fmt-body">Layout</Label>
        <Textarea
          id="fmt-body"
          rows={12}
          required
          spellCheck={false}
          className="font-mono text-xs"
          value={draft.body}
          onChange={(e) => set("body", e.target.value)}
        />
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none hover:text-foreground">
            What can I put in the layout?
          </summary>
          <p className="mt-2">
            Markdown, with the extracted notes filled in where you place these:
          </p>
          <ul className="mt-2 grid gap-1">
            {VARIABLES.map(([code, what]) => (
              <li key={code}>
                <code className="rounded bg-muted px-1 py-0.5 font-mono">
                  {code}
                </code>
                : {what}
              </li>
            ))}
          </ul>
          <p className="mt-2">
            The AI always extracts the summary, topics, decisions, actions and
            open questions. Use &quot;Extra things&quot; above for anything else
            you want in the note.
          </p>
        </details>
      </div>
      {error && (
        <p
          role="alert"
          className="rounded-md bg-destructive/10 px-3 py-2 text-[13px] text-destructive"
        >
          {error}
        </p>
      )}
      <DialogFooter>
        <Button
          type="submit"
          disabled={busy || !draft.name.trim() || !draft.body.trim()}
        >
          {busy && <Loader2 className="animate-spin" />}
          {format ? "Save format" : "Create format"}
        </Button>
      </DialogFooter>
    </form>
  )
}

export function FormatsCard() {
  const { data, reload } = useApi<Format[]>("/api/templates")
  const { reload: reloadInfo } = useInfo()
  const confirm = useConfirm()
  const [editing, setEditing] = React.useState<Format | null>(null)
  const [open, setOpen] = React.useState(false)

  const refresh = () => {
    reload()
    reloadInfo()
  }
  const openDialog = (f: Format | null) => {
    setEditing(f)
    setOpen(true)
  }

  async function remove(f: Format) {
    const reset = f.builtin
    const ok = await confirm({
      title: reset ? `Reset “${f.name}”?` : `Delete “${f.name}”?`,
      description: reset
        ? "Your changes to this built-in format are lost and it goes back to how it shipped."
        : "The format is deleted. Notes already written with it are not changed.",
      confirmLabel: reset ? "Reset format" : "Delete format",
      destructive: true,
    })
    if (!ok) return
    try {
      await api(`/api/templates/${encodeURIComponent(f.key)}`, {
        method: "DELETE",
      })
      toast.success(reset ? "Format reset" : "Format deleted")
      refresh()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const starter = data?.find((f) => f.key === "standard") ?? data?.[0]

  return (
    <Card>
      <CardHeader>
        <CardTitle>Minutes formats</CardTitle>
        <CardDescription>
          Choose how each meeting&apos;s notes are written and laid out. Create
          your own, or edit the built-in ones. They are saved as Markdown files
          in <code className="font-mono text-xs">Templates/Minutes/</code> in
          your vault.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {!data ? (
          <Skeleton className="h-32 rounded-lg" />
        ) : (
          <ul className="divide-y text-sm">
            {data.map((f) => (
              <li
                key={f.key}
                className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0"
              >
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {f.name}
                    {f.default && <Badge variant="secondary">Default</Badge>}
                    {!f.builtin && <Badge variant="outline">Custom</Badge>}
                    {f.edited && <Badge variant="outline">Edited</Badge>}
                  </p>
                  <p className="text-muted-foreground">
                    {f.description || "No description"}
                  </p>
                </div>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openDialog(f)}
                  >
                    <Pencil />
                    Edit
                  </Button>
                  {(f.edited || (!f.builtin && !f.default)) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => remove(f)}
                    >
                      {f.builtin ? <RotateCcw /> : <Trash2 />}
                      {f.builtin ? "Reset" : "Delete"}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <div>
          <Button
            variant="outline"
            onClick={() => openDialog(null)}
            disabled={!data}
          >
            <Plus />
            New format
          </Button>
        </div>
      </CardContent>
      <FormatDialog
        open={open}
        onOpenChange={setOpen}
        format={editing}
        starter={starter}
        onSaved={refresh}
      />
    </Card>
  )
}

type Defaults = { default_template: string; summary_instructions: string }

export function SummaryDefaultsCard() {
  const { data, reload } = useApi<Defaults>("/api/settings")
  const { info, reload: reloadInfo } = useInfo()
  if (!data) return <Skeleton className="h-64 rounded-xl" />
  // keyed on what is saved so the form resets to it after a save
  return (
    <DefaultsForm
      key={data.default_template + data.summary_instructions}
      saved={data}
      formats={info?.templates ?? []}
      onSaved={() => {
        reload()
        reloadInfo()
      }}
    />
  )
}

function DefaultsForm({
  saved,
  formats,
  onSaved,
}: {
  saved: Defaults
  formats: { key: string; name: string }[]
  onSaved: () => void
}) {
  const [template, setTemplate] = React.useState(saved.default_template)
  const [instructions, setInstructions] = React.useState(
    saved.summary_instructions,
  )
  const [busy, setBusy] = React.useState(false)
  const dirty =
    template !== saved.default_template ||
    instructions.trim() !== saved.summary_instructions.trim()

  async function save() {
    setBusy(true)
    try {
      await api("/api/settings", {
        method: "PUT",
        json: {
          default_template: template,
          summary_instructions: instructions,
        },
      })
      toast.success("Summary defaults saved")
      onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Summary defaults</CardTitle>
        <CardDescription>
          Applied to every new meeting unless you choose otherwise
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2">
          <Label>Default minutes format</Label>
          <Select value={template} onValueChange={setTemplate}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {formats.map((f) => (
                <SelectItem key={f.key} value={f.key}>
                  {f.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="standing">Instructions for every summary</Label>
          <Textarea
            id="standing"
            rows={4}
            placeholder="e.g. Write in British English. Always name the owner of an action item. Keep a neutral tone."
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Added to the format&apos;s own instructions and to anything you type
            for a single meeting.
          </p>
        </div>
        <div>
          <Button onClick={save} disabled={busy || !dirty}>
            {busy && <Loader2 className="animate-spin" />}
            Save
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
