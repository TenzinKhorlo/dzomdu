import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const code = ts.transpileModule(readFileSync(new URL('../src/lib/transcript-edits.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const exports = {}
vm.runInNewContext(code, { exports })
const { previewCorrections, speakerCorrection } = exports
const rows = [
  { id: 't1', start: 0, end: 4, speaker: 'a', label: 'Alice', text: 'Opening.' },
  { id: 't2', start: 5, end: 9, speaker: 'b', label: 'Bob', text: 'Wrong text.' },
  { id: 't3', start: 10, end: 13, speaker: 'a', label: 'Alice', text: 'Closing.' },
]
const speakers = [{ key: 'a', label: 'Alice' }, { key: 'b', label: 'Bob' }]

test('drag reassignment changes only attribution, retains ids and chronological audio timing', () => {
  const edit = speakerCorrection(['t2'], speakers[0])
  const result = previewCorrections(rows, speakers, [edit])
  assert.equal(result.rows[1].speaker, 'a')
  assert.equal(result.rows[1].label, 'Alice')
  assert.equal(JSON.stringify(result.rows.map(row => [row.id, row.start, row.end, row.text])), JSON.stringify(rows.map(row => [row.id, row.start, row.end, row.text])))
  assert.equal(rows[1].speaker, 'b')
})

test('batch preview respects rename, reassignment and text correction order without mutating sources', () => {
  const result = previewCorrections(rows, speakers, [
    { turn_ids: [], speaker: 'a', name: 'Alicia', rename_speaker: true },
    { turn_ids: ['t2'], speaker: 'a', text: 'Correct words.' },
    { turn_ids: ['t3'], name: 'Carol' },
  ])
  assert.equal(result.rows[0].label, 'Alicia')
  assert.equal(result.rows[1].label, 'Alicia')
  assert.equal(result.rows[1].text, 'Correct words.')
  assert.equal(result.rows[2].label, 'Carol')
  assert.equal(rows[1].text, 'Wrong text.')
  assert.equal(speakers[0].label, 'Alice')
})

test('a newly introduced person can receive more turns before the batch is saved', () => {
  const first = previewCorrections(rows, speakers, [{ turn_ids: ['t2'], name: 'Carol' }])
  const newVoice = first.speakers.find(voice => voice.label === 'Carol')
  const edit = speakerCorrection(['t3'], newVoice)
  assert.equal(edit.name, 'Carol')
  assert.equal(edit.speaker, undefined)
  const result = previewCorrections(rows, speakers, [{ turn_ids: ['t2'], name: 'Carol' }, edit])
  assert.equal(result.rows[1].speaker, result.rows[2].speaker)
  assert.equal(result.speakers.filter(voice => voice.label === 'Carol').length, 1)
})
