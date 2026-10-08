"use client"

import { useSyncExternalStore } from "react"

import { toast } from "sonner"

import { wsUrl } from "@/lib/api"

/**
 * Audio capture that survives page navigation: audio is downsampled to 16 kHz PCM in an
 * AudioWorklet and streamed over a WebSocket to the backend, which saves it continuously.
 *
 * Two sources: "room" records the microphone alone. "meeting" records an online meeting
 * (Zoom, Google Meet, Teams…) by mixing the microphone with the audio of a browser tab or the
 * screen that the user chooses to share. Nothing joins the call and nothing leaves this computer.
 */
export type RecordingSource = "room" | "meeting"

type Snapshot = {
  sessionId: string | null
  startedAt: number
  levels: number[] // recent input levels (0..1), newest last, for the waveform
}

const HISTORY = 48
let snapshot: Snapshot = { sessionId: null, startedAt: 0, levels: Array(HISTORY).fill(0) }
const listeners = new Set<() => void>()

let stream: MediaStream | null = null
let meetingStream: MediaStream | null = null
let ctx: AudioContext | null = null
let node: AudioWorkletNode | null = null
let ws: WebSocket | null = null

function emit(next: Partial<Snapshot>) {
  snapshot = { ...snapshot, ...next }
  listeners.forEach((l) => l())
}

function releaseStream(s: MediaStream | null) {
  s?.getTracks().forEach((t) => t.stop())
}

export const recorder = {
  async start(sessionId: string, source: RecordingSource = "room") {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser can't record here. Open Dzomdu at http://localhost.")
    }
    const meeting = source === "meeting"
    if (meeting) {
      // Asked first, while the click that started this is still fresh. Chrome insists on a
      // video track; it is dropped straight away and only the audio is kept.
      if (!navigator.mediaDevices.getDisplayMedia) {
        throw new Error("This browser can't capture meeting audio. Use Chrome or Edge.")
      }
      try {
        meetingStream = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        })
      } catch (e) {
        if ((e as Error).name === "NotAllowedError") {
          throw new Error("Sharing was cancelled, so nothing is being recorded.")
        }
        throw e
      }
      meetingStream.getVideoTracks().forEach((t) => t.stop())
      if (meetingStream.getAudioTracks().length === 0) {
        releaseStream(meetingStream)
        meetingStream = null
        throw new Error(
          "No audio was shared. Choose the meeting's browser tab and tick “Also share tab audio” (or share the entire screen with system audio on Windows).",
        )
      }
      meetingStream.getAudioTracks()[0].addEventListener("ended", () => {
        if (snapshot.sessionId) toast.warning("Meeting audio stopped. Only your microphone is recording now.")
      })
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          // in a call the speakers are in the room too: cancel the echo of the other side.
          // A room recording keeps distant voices, so it turns call-style processing off.
          echoCancellation: meeting,
          noiseSuppression: false,
          autoGainControl: true,
        },
      })
    } catch (e) {
      if (meeting) {
        toast.warning("Microphone unavailable. Only the meeting audio is recording, not your voice.")
      } else if ((e as Error).name === "NotAllowedError") {
        throw new Error("Microphone access was denied. Allow it in the browser and in macOS settings.")
      } else {
        throw e
      }
    }
    ctx = new AudioContext()
    await ctx.audioWorklet.addModule("/recorder-worklet.js")
    node = new AudioWorkletNode(ctx, "pcm-recorder", { processorOptions: { targetRate: 16000 } })
    const mixer = ctx.createGain()
    for (const s of [stream, meetingStream]) {
      if (!s) continue
      const gain = ctx.createGain()
      gain.gain.value = meeting ? 0.8 : 1 // headroom so two voices don't clip when summed
      ctx.createMediaStreamSource(s).connect(gain).connect(mixer)
    }
    const mute = ctx.createGain()
    mute.gain.value = 0
    mixer.connect(node).connect(mute).connect(ctx.destination)

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
    releaseStream(stream)
    releaseStream(meetingStream)
    meetingStream = null
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
