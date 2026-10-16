"use client"

import * as React from "react"
import { GripVertical, Loader2, Pencil, Play, Save, UserRoundPen } from "lucide-react"
import { toast } from "sonner"

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/animate-ui/components/radix/dialog"
import { Checkbox } from "@/components/animate-ui/components/radix/checkbox"
import { SpeakerAvatar } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { clock, colorFor } from "@/lib/format"
import { previewCorrections, speakerCorrection, type TranscriptEdit, type TranscriptRow, type TranscriptSpeaker } from "@/lib/transcript-edits"
import { cn } from "@/lib/utils"

const DRAG_TYPE = "application/x-dzomdu-transcript-turn"

export function TranscriptEditor({
  rows, speakers, people = [], live = false, query = "", activeId, focusId,
  onSeek, onEdit, onSave, onEditingChange, disabled = false, children,
}: {
  rows: TranscriptRow[]
  speakers: TranscriptSpeaker[]
  people?: string[]
  live?: boolean
  query?: string
  activeId?: string | null
  focusId?: string | null
  onSeek?: (row: TranscriptRow) => void
  onEdit?: (edit: TranscriptEdit) => Promise<void>
  onSave?: (edits: TranscriptEdit[]) => Promise<void>
  onEditingChange?: (editing: boolean) => void
  disabled?: boolean
  children?: React.ReactNode
}) {
  const [editing, setEditing] = React.useState(false)
  const [edits, setEdits] = React.useState<TranscriptEdit[]>([])
  const [busy, setBusy] = React.useState(false)
  const [dialog, setDialog] = React.useState<TranscriptRow | null>(null)
  const [name, setName] = React.useState("")
  const [text, setText] = React.useState("")
  const [rename, setRename] = React.useState(false)
  const [error, setError] = React.useState("")
  const [dragging, setDragging] = React.useState<string | null>(null)
  const [dropTarget, setDropTarget] = React.useState<string | null>(null)
  const pointerDrag = React.useRef<{ id: string; x: number; y: number; moved: boolean; target: string | null } | null>(null)
  const suppressClick = React.useRef(false)
  const listId = React.useId()
  React.useEffect(() => { onEditingChange?.(editing) }, [editing, onEditingChange])
  const draft = previewCorrections(rows, speakers, edits)
  const visible = draft.rows.filter(row => !query || (row.text + " " + row.label).toLowerCase().includes(query))
  const locked = busy || disabled

  function open(row: TranscriptRow, all: boolean) {
    setDialog(row)
    setName(row.speaker ? row.label : "")
    setText(row.text)
    setRename(all && !!row.speaker)
    setError("")
  }

  async function correct(edit: TranscriptEdit) {
    if (locked) return false
    if (!live) {
      setEdits(previous => [...previous, edit])
      return true
    }
    setBusy(true)
    try {
      await onEdit?.(edit)
      toast.success("Speaker correction saved")
      return true
    } catch (cause) {
      const message = (cause as Error).message
      setError(message)
      toast.error(message)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function saveDialog() {
    if (!dialog || !name.trim() || (!live && !text.trim())) return
    const cleaned = name.trim().replace(/\s+/g, " ")
    const voice = draft.speakers.find(speaker => speaker.label === cleaned)
    let edit: TranscriptEdit
    if (rename && dialog.speaker && !dialog.speaker.startsWith("name:")) {
      edit = { turn_ids: [], speaker: dialog.speaker, name: cleaned, rename_speaker: true }
    } else if (rename && dialog.speaker) {
      edit = { turn_ids: draft.rows.filter(row => row.speaker === dialog.speaker).map(row => row.id), name: cleaned }
    } else {
      edit = voice ? speakerCorrection([dialog.id], voice) : { turn_ids: [dialog.id], name: cleaned }
      if (!live && text.trim() !== dialog.text) edit.text = text.trim()
    }
    if (await correct(edit)) setDialog(null)
  }

  async function saveBatch() {
    setBusy(true)
    setError("")
    try {
      await onSave?.(edits)
      setEdits([])
      setEditing(false)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function dragOver(event: React.DragEvent, target: string) {
    if (locked || !dragging || !event.dataTransfer.types.includes(DRAG_TYPE)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    setDropTarget(target)
  }

  function drop(event: React.DragEvent, voice: TranscriptSpeaker) {
    event.preventDefault()
    const id = event.dataTransfer.getData(DRAG_TYPE)
    const source = draft.rows.find(row => row.id === id)
    setDragging(null)
    setDropTarget(null)
    if (source && !source.partial && source.speaker !== voice.key && !locked) {
      void correct(speakerCorrection([id], voice))
    }
  }

  // A pointer handle also works on touch screens and embedded browsers that do not expose
  // native HTML drag data. Native paragraph dragging remains available on desktop browsers.
  function moveHandle(event: React.PointerEvent<HTMLButtonElement>) {
    const drag = pointerDrag.current
    if (!drag) return
    if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 6) return
    drag.moved = true
    setDragging(drag.id)
    const target = document.elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>("[data-speaker-target]")
    drag.target = target?.dataset.speakerTarget ?? null
    setDropTarget(target?.dataset.dropTarget ?? null)
  }

  function releaseHandle(event: React.PointerEvent<HTMLButtonElement>) {
    const drag = pointerDrag.current
    pointerDrag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    setDragging(null)
    setDropTarget(null)
    if (!drag?.moved) return
    suppressClick.current = true
    const source = draft.rows.find(row => row.id === drag.id)
    const target = draft.speakers.find(voice => voice.key === drag.target)
    if (source && target && source.speaker !== target.key && !locked) {
      void correct(speakerCorrection([source.id], target))
    }
  }

  return (
    <div className="space-y-4">
      <div className={cn("flex flex-wrap items-center justify-between gap-2", editing && "sticky top-16 z-10 bg-card py-2")}>
        <p className="text-xs text-muted-foreground">
          {editing
            ? live ? "Optional corrections. Saved live names carry into the final review."
              : "Drag a turn onto its speaker, or use Edit. Save when you are ready."
            : live ? "You can assign speakers now or leave them for the final review." : "Speaker and transcript corrections are optional."}
        </p>
        {editing ? (
          <div className="flex gap-2">
            {!live && edits.length > 0 && <Button variant="ghost" size="sm" disabled={locked} onClick={() => { setEdits(previous => previous.slice(0, -1)); setError("") }}>Undo last</Button>}
            <Button variant="outline" size="sm" disabled={locked} onClick={() => { setEdits([]); setEditing(false); setError("") }}>
              {edits.length ? "Discard changes" : "Done"}
            </Button>
            {!live && <Button size="sm" disabled={locked || !edits.length} onClick={saveBatch}>
              {busy ? <Loader2 className="animate-spin" /> : <Save />}
              Save corrections
            </Button>}
          </div>
        ) : (
          <Button variant="outline" size="sm" disabled={disabled} onClick={() => setEditing(true)}>
            <UserRoundPen />{live ? "Edit speakers" : "Edit transcript"}
          </Button>
        )}
      </div>
      {error && <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
      {editing && (
        <div className="rounded-lg border bg-muted/30 p-3">
          <p className="mb-2 text-xs text-muted-foreground">Use the drag handle to move a turn onto the right speaker. Tap a speaker name to rename it.</p>
          <div className="flex flex-wrap gap-2">
            {draft.speakers.map(voice => (
              <span key={voice.key} data-speaker-target={voice.key} data-drop-target={voice.key}
                onDragOver={event => dragOver(event, voice.key)} onDragLeave={() => setDropTarget(null)} onDrop={event => drop(event, voice)}
                className={cn("flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs", dropTarget === voice.key && "border-brand bg-brand/10 ring-2 ring-brand/30")}>
                <SpeakerAvatar name={voice.label} size="sm" />{voice.label}
              </span>
            ))}
          </div>
          {!live && <p className="mt-2 text-xs text-muted-foreground">Saving also regenerates the summary and minutes from the corrected transcript.</p>}
        </div>
      )}
      {!editing && children ? children : (
        <ul className="space-y-1">
          {visible.map(row => {
            const voice = draft.speakers.find(speaker => speaker.key === row.speaker)
            const active = row.id === activeId || row.id === focusId
            return (
              <li key={row.id} id={`turn-${row.id}`} draggable={editing && !row.partial && !locked}
                data-speaker-target={row.speaker ?? undefined} data-drop-target={row.id}
                onDragStart={event => { event.dataTransfer.setData(DRAG_TYPE, row.id); event.dataTransfer.effectAllowed = "move"; setDragging(row.id) }}
                onDragEnd={() => { setDragging(null); setDropTarget(null) }}
                onDragOver={event => voice && dragOver(event, row.id)} onDragLeave={() => setDropTarget(null)} onDrop={event => voice && drop(event, voice)}
                className={cn("relative flex gap-3 rounded-xl px-2 py-2 transition-colors", active && "bg-brand/[0.06]", dropTarget === row.id && "bg-brand/10 ring-2 ring-brand/30", dragging === row.id && "opacity-50")}>
                {editing && !row.partial && (
                  <button type="button" disabled={locked} aria-label={`Reassign speaker at ${clock(row.start)}`} title="Drag to a speaker, or click to assign"
                    onClick={event => {
                      if (suppressClick.current && event.detail > 0) { suppressClick.current = false; return }
                      suppressClick.current = false
                      open(row, false)
                    }}
                    onPointerDown={event => {
                      if (event.button !== 0 || locked) return
                      event.preventDefault()
                      suppressClick.current = false
                      pointerDrag.current = { id: row.id, x: event.clientX, y: event.clientY, moved: false, target: null }
                      event.currentTarget.setPointerCapture(event.pointerId)
                    }}
                    onPointerMove={moveHandle} onPointerUp={releaseHandle}
                    onPointerCancel={() => { pointerDrag.current = null; setDragging(null); setDropTarget(null) }}
                    className="mt-1 h-7 shrink-0 touch-none cursor-grab rounded text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing disabled:opacity-50">
                    <GripVertical className="size-4" />
                  </button>
                )}
                <SpeakerAvatar name={row.label} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    {editing && !row.partial ? (
                      <button type="button" disabled={locked} onClick={() => open(row, true)} className="rounded font-semibold underline decoration-dotted underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring" style={{ color: colorFor(row.label) }}>
                        {row.label}
                      </button>
                    ) : <span className="font-semibold" style={{ color: colorFor(row.label) }}>{row.label}</span>}
                    <button type="button" disabled={!onSeek} onClick={() => onSeek?.(row)} aria-label={`Play from ${clock(row.start)}`} aria-current={active ? "true" : undefined} className="flex items-center gap-1 rounded font-mono text-xs text-muted-foreground enabled:hover:text-brand focus-visible:ring-2 focus-visible:ring-ring">
                      {clock(row.start)}{onSeek && <Play className="size-3" />}
                    </button>
                    {editing && !row.partial && <Button variant="ghost" size="icon-xs" disabled={locked} aria-label={`Edit turn at ${clock(row.start)}`} onClick={() => open(row, false)}><Pencil /></Button>}
                  </div>
                  {!editing && onSeek ? (
                    <button type="button" onClick={() => onSeek(row)} className="mt-0.5 w-full rounded text-left text-sm leading-relaxed hover:text-brand focus-visible:ring-2 focus-visible:ring-ring">{row.text}</button>
                  ) : <p className={cn("mt-0.5 whitespace-pre-wrap text-sm leading-relaxed", row.partial && "text-muted-foreground")}>{row.text}</p>}
                  {row.partial && editing && <p className="text-xs text-muted-foreground">Finishing this sentence…</p>}
                </div>
              </li>
            )
          })}
          {!visible.length && <li className="text-sm text-muted-foreground">No matches.</li>}
        </ul>
      )}
      <Dialog open={!!dialog} onOpenChange={open => { if (!open && !busy) setDialog(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{rename ? "Assign this speaker" : "Correct this turn"}</DialogTitle>
            <DialogDescription>{dialog && clock(dialog.start)} · {live ? "Saved names remain available in the final speaker review." : "Changes are saved together when you select Save corrections."}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor={`${listId}-name`}>Speaker name</Label>
            <Input id={`${listId}-name`} list={`${listId}-people`} maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder="Choose or enter a name" disabled={busy} />
            <datalist id={`${listId}-people`}>{[...new Set([...draft.speakers.map(voice => voice.label), ...people])].map(person => <option key={person} value={person} />)}</datalist>
          </div>
          {dialog?.speaker && <label className="flex items-start gap-2 text-sm"><Checkbox checked={rename} disabled={busy} onCheckedChange={value => setRename(value === true)} />Rename this speaker throughout the transcript</label>}
          {!live && !rename && <div className="grid gap-2"><Label htmlFor={`${listId}-text`}>Transcript text</Label><Textarea id={`${listId}-text`} rows={5} value={text} maxLength={20000} onChange={event => setText(event.target.value)} disabled={busy} /></div>}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setDialog(null)}>Cancel</Button>
            <Button disabled={busy || !name.trim() || (!live && !text.trim())} onClick={saveDialog}>{busy && <Loader2 className="animate-spin" />}{live ? "Save speaker" : "Apply correction"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
