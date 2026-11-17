import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const code = ts.transpileModule(readFileSync(new URL('../src/lib/bubbles.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const exports = {}
vm.runInNewContext(code, { exports })
const { bubbleDiameter } = exports

test('the largest value gets the full diameter', () => {
  assert.equal(bubbleDiameter(67, 67, 9), 9)
})

test('area, not diameter, is proportional to the value', () => {
  const big = bubbleDiameter(67, 67, 9)
  const small = bubbleDiameter(67 / 4, 67, 9)
  assert.ok(Math.abs(small - big / 2) < 1e-9)
})

test('empty or invalid input never produces NaN', () => {
  assert.equal(bubbleDiameter(0, 67, 9), 0)
  assert.equal(bubbleDiameter(5, 0, 9), 0)
})

const { scatterBubbles } = exports
const people = [67, 28, 13, 12, 7, 7]

test('scatter is deterministic for the same seed and differs for another', () => {
  const a = scatterBubbles(people, 'karpo|nima')
  assert.deepEqual(a, scatterBubbles(people, 'karpo|nima'))
  assert.notDeepEqual(a, scatterBubbles(people, 'someone else'))
})

test('every bubble stays inside the box and no bubble covers another centre', () => {
  for (const seed of ['a', 'b', 'c', 'karpo|nima|uzal']) {
    const b = scatterBubbles(people, seed)
    b.forEach((p, i) => {
      assert.ok(p.cx - p.d / 2 >= -1e-9 && p.cx + p.d / 2 <= 100 + 1e-9, 'x in bounds')
      assert.ok(p.cy - p.d / 2 >= -1e-9 && p.cy + p.d / 2 <= 72 + 1e-9, 'y in bounds')
      b.forEach((q, j) => {
        if (i < j) assert.ok(Math.hypot(p.cx - q.cx, p.cy - q.cy) >= Math.max(p.d, q.d) / 2, `centres clear (${seed})`)
      })
    })
  }
})

test('scatter handles empty input', () => {
  assert.deepEqual(scatterBubbles([], 'x'), [])
})
