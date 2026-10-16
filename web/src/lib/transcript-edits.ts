export type TranscriptRow = {
  id: string
  start: number
  end: number
  speaker: string | null
  label: string
  text: string
  partial?: boolean
  rev?: number
}

export type TranscriptSpeaker = { key: string; label: string }
export type TranscriptEdit = {
  turn_ids: string[]
  speaker?: string
  name?: string
  text?: string
  rename_speaker?: boolean
}

/** Preview a batch without changing stable turn ids, timing, or chronological order. */
export function previewCorrections(
  rows: TranscriptRow[], speakers: TranscriptSpeaker[], edits: TranscriptEdit[],
) {
  const draft = rows.map(row => ({ ...row }))
  const voices = speakers.map(speaker => ({ ...speaker }))
  for (const edit of edits) {
    if (edit.rename_speaker) {
      const voice = voices.find(speaker => speaker.key === edit.speaker)
      if (voice && edit.name) voice.label = edit.name
      for (const row of draft) {
        if (row.speaker === edit.speaker && edit.name) row.label = edit.name
      }
      continue
    }
    let target = voices.find(speaker => speaker.key === edit.speaker)
    if (edit.name) {
      target = voices.find(speaker => speaker.label === edit.name)
      if (!target) {
        target = { key: `name:${edit.name}`, label: edit.name }
        voices.push(target)
      }
    }
    for (const row of draft) {
      if (!edit.turn_ids.includes(row.id)) continue
      if (target) {
        row.speaker = target.key
        row.label = target.label
      }
      if (edit.text !== undefined) row.text = edit.text
    }
  }
  return { rows: draft, speakers: voices }
}

export function speakerCorrection(ids: string[], speaker: TranscriptSpeaker): TranscriptEdit {
  return speaker.key.startsWith("name:")
    ? { turn_ids: ids, name: speaker.label }
    : { turn_ids: ids, speaker: speaker.key }
}
