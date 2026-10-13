import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

// Exercise the production recorder with browser devices and audio routing mocked.
const code = ts.transpileModule(readFileSync(new URL("../src/lib/recorder.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

function setup({ micDenied = false, noTabAudio = false, suppression = true } = {}) {
  const calls = { mic: [], display: [], sources: [], warnings: [], messages: [], timers: [] }
  function track(kind) {
    return {
      kind, readyState: "live", ended: null,
      stop() { this.readyState = "ended" },
      addEventListener(event, callback) { if (event === "ended") this.ended = callback },
      getSettings: () => ({ noiseSuppression: suppression }),
      end() { this.readyState = "ended"; this.ended?.() },
    }
  }
  function media(tracks) {
    return {
      getTracks: () => tracks,
      getAudioTracks: () => tracks.filter((t) => t.kind === "audio"),
      getVideoTracks: () => tracks.filter((t) => t.kind === "video"),
    }
  }
  const mic = media([track("audio")])
  const tab = media([track("video"), ...(!noTabAudio ? [track("audio")] : [])])
  const mediaDevices = {
    async getDisplayMedia(options) { calls.display.push(options); return tab },
    async getUserMedia(options) {
      calls.mic.push(options)
      if (micDenied) throw Object.assign(new Error("Denied"), { name: "NotAllowedError" })
      return mic
    },
  }
  const connectable = () => ({ connect(next) { return next }, gain: { value: 1 } })
  class AudioContext {
    audioWorklet = { addModule: async () => {} }
    destination = connectable()
    createGain = connectable
    createMediaStreamSource(s) { calls.sources.push(s); return connectable() }
    async close() {}
  }
  class AudioWorkletNode {
    port = { postMessage: (m) => calls.messages.push(m) }
    connect(next) { return next }
  }
  class WebSocket {
    static OPEN = 1
    static CONNECTING = 0
    readyState = 1
    send(m) { calls.messages.push(m) }
    close() {}
  }
  const exports = {}
  vm.runInNewContext(code, {
    exports, navigator: { mediaDevices }, AudioContext, AudioWorkletNode, WebSocket,
    // Run timers explicitly so ending tab sharing can be verified without real delays.
    setTimeout: (callback) => calls.timers.push(callback),
    require(name) {
      if (name === "react") return { useSyncExternalStore: (_, get) => get() }
      if (name === "sonner") return { toast: { warning: (m) => calls.warnings.push(m) } }
      if (name === "@/lib/api") return { wsUrl: (url) => url }
      throw new Error(`Unexpected import: ${name}`)
    },
  })
  return { ...exports, calls, mic, tab, mediaDevices }
}

test("meeting defaults to tab audio only and never requests or mixes a microphone", async () => {
  const s = setup()
  await s.recorder.start("meeting-1", "meeting")
  assert.equal(s.calls.mic.length, 0)
  assert.deepEqual(s.calls.sources, [s.tab])
  assert.equal(s.useRecorder().includesMicrophone, false)
  assert.equal(s.useRecorder().source, "meeting")
  assert.equal(s.tab.getVideoTracks()[0].readyState, "ended")
  s.recorder.release()
  assert.equal(s.tab.getAudioTracks()[0].readyState, "ended")
})

test("tab-only recording works even when microphone capture is unavailable", async () => {
  const s = setup()
  delete s.mediaDevices.getUserMedia
  await s.recorder.start("meeting-1", "meeting")
  assert.deepEqual(s.calls.sources, [s.tab])
})

for (const reduceBackgroundNoise of [true, false]) {
  test(`optional microphone uses noise reduction ${reduceBackgroundNoise} without filtering tab audio`, async () => {
    const s = setup()
    await s.recorder.start("meeting-1", "meeting", { includeMicrophone: true, reduceBackgroundNoise })
    assert.equal(s.calls.mic[0].audio.noiseSuppression, reduceBackgroundNoise)
    assert.equal(s.calls.mic[0].audio.echoCancellation, true)
    assert.equal(s.calls.display[0].audio.noiseSuppression, false)
    assert.deepEqual(s.calls.sources, [s.mic, s.tab])
    assert.equal(s.useRecorder().includesMicrophone, true)
    s.recorder.release()
    assert.equal(s.mic.getAudioTracks()[0].readyState, "ended")
  })
}

test("room recording retains microphone capture without call processing", async () => {
  const s = setup()
  await s.recorder.start("room-1", "room", { includeMicrophone: false, reduceBackgroundNoise: true })
  assert.equal(s.calls.display.length, 0)
  assert.equal(s.calls.mic[0].audio.noiseSuppression, false)
  assert.equal(s.calls.mic[0].audio.echoCancellation, false)
  assert.deepEqual(s.calls.sources, [s.mic])
})

test("denied optional microphone falls back to meeting audio and reports the actual source", async () => {
  const s = setup({ micDenied: true })
  await s.recorder.start("meeting-1", "meeting", { includeMicrophone: true, reduceBackgroundNoise: true })
  assert.deepEqual(s.calls.sources, [s.tab])
  assert.equal(s.useRecorder().includesMicrophone, false)
  assert.match(s.calls.warnings[0], /Microphone unavailable/)
})

test("unconfirmed microphone suppression warns instead of claiming noise is removed", async () => {
  const s = setup()
  // Simulate a browser that reports suppression as disabled.
  s.mic.getAudioTracks()[0].getSettings = () => ({ noiseSuppression: false })
  await s.recorder.start("meeting-1", "meeting", { includeMicrophone: true, reduceBackgroundNoise: true })
  assert.match(s.calls.warnings[0], /noise reduction could not be confirmed/)
})

test("sharing without audio fails without silently recording the surroundings", async () => {
  const s = setup({ noTabAudio: true })
  await assert.rejects(s.recorder.start("meeting-1", "meeting"), /No audio was shared/)
  assert.equal(s.calls.mic.length, 0)
  assert.equal(s.useRecorder().sessionId, null)
})

test("ending tab-only sharing flushes and saves the recording", async () => {
  const s = setup()
  await s.recorder.start("meeting-1", "meeting")
  s.tab.getAudioTracks()[0].end()
  assert.match(s.calls.warnings[0], /recording is being saved/)
  assert.deepEqual(s.calls.messages, ["flush"])
  s.calls.timers.shift()()
  await new Promise((r) => setImmediate(r))
  assert.deepEqual(s.calls.messages, ["flush", "stop"])
  assert.equal(s.useRecorder().sessionId, null)
})

test("ending sharing while the microphone is live keeps recording with a truthful warning", async () => {
  const s = setup()
  await s.recorder.start("meeting-1", "meeting", { includeMicrophone: true, reduceBackgroundNoise: true })
  s.tab.getAudioTracks()[0].end()
  assert.match(s.calls.warnings[0], /Only your microphone/)
  assert.equal(s.useRecorder().includesMeetingAudio, false)
  assert.equal(s.useRecorder().sessionId, "meeting-1")
  assert.deepEqual(s.calls.messages, [])
})
