"use client"

import { useSyncExternalStore } from "react"

import { wsUrl } from "@/lib/api"

/**
 * Microphone capture that survives page navigation: audio is downsampled to 16 kHz PCM in an
 * AudioWorklet and streamed over a WebSocket to the backend, which saves it continuously.
 */
type Snapshot = {
  sessionId: string | null
  startedAt: number
  levels: number[] // recent input levels (0..1), newest last, for the waveform
}

const HISTORY = 48
let snapshot: Snapshot = { sessionId: null, startedAt: 0, levels: Array(HISTORY).fill(0) }
const listeners = new Set<() => void>()

let stream: MediaStream | null = null
let ctx: AudioContext | null = null
let node: AudioWorkletNode | null = null
let ws: WebSocket | null = null

function emit(next: Partial<Snapshot>) {
  snapshot = { ...snapshot, ...next }
  listeners.forEach((l) => l())
}

export const recorder = {
  async start(sessionId: string) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser can't record here. Open Dzomdu at http://localhost.")
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        // room recording: no call-style processing that suppresses distant voices
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: true,
        },
      })
    } catch (e) {
      if ((e as Error).name === "NotAllowedError") {
        throw new Error("Microphone access was denied. Allow it in the browser and in macOS settings.")
      }
      throw e
    }
    ctx = new AudioContext()
    await ctx.audioWorklet.addModule("/recorder-worklet.js")
    const source = ctx.createMediaStreamSource(stream)
    node = new AudioWorkletNode(ctx, "pcm-recorder", { processorOptions: { targetRate: 16000 } })
    const mute = ctx.createGain()
    mute.gain.value = 0
    source.connect(node).connect(mute).connect(ctx.destination)

    const queue: ArrayBuffer[] = []
    const socket = new WebSocket(wsUrl(`/api/sessions/${sessionId}/audio`))
    socket.binaryType = "arraybuffer"
    socket.onopen = () => queue.splice(0).forEach((b) => socket.send(b))
    ws = socket
    node.port.onmessage = ({ data }: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(data.pcm)
      else if (socket.readyState === WebSocket.CONNECTING) queue.push(data.pcm)
      const level = Math.min(1, Math.sqrt(data.rms) * 1.8)
      emit({ levels: [...snapshot.levels.slice(1), level] })
    }
    emit({ sessionId, startedAt: Date.now(), levels: Array(HISTORY).fill(0) })
  },

  async stop() {
    if (!snapshot.sessionId) return
    node?.port.postMessage("flush")
    await new Promise((r) => setTimeout(r, 150)) // let the last chunk arrive
    if (ws?.readyState === WebSocket.OPEN) ws.send("stop")
    this.release()
  },

  release() {
    stream?.getTracks().forEach((t) => t.stop())
    void ctx?.close()
    const socket = ws
    setTimeout(() => socket?.close(), 500)
    stream = null
    ctx = null
    node = null
    ws = null
    emit({ sessionId: null, levels: Array(HISTORY).fill(0) })
  },
}

export function useRecorder(): Snapshot {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => snapshot,
    () => snapshot,
  )
}

if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", (e) => {
    if (snapshot.sessionId) e.preventDefault()
  })
}
