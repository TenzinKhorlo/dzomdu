"use client"

import { useSyncExternalStore } from "react"

import { toast } from "sonner"

import { wsUrl } from "@/lib/api"

/**
 * Audio capture that survives page navigation: audio is downsampled to 16 kHz PCM in an
 * AudioWorklet and streamed over a WebSocket to the backend, which saves it continuously.
 *
 * Two sources: "room" records the microphone alone. "meeting" records an online meeting
 * (Zoom, Google Meet, Teams…) from a shared tab or screen, optionally adding the microphone.
 * Nothing joins the call and nothing leaves this computer.
 */
export type RecordingSource = "room" | "meeting"

export type MeetingAudioOptions = {
  includeMicrophone: boolean
  reduceBackgroundNoise: boolean
}

type Snapshot = {
  sessionId: string | null
  source: RecordingSource
  includesMicrophone: boolean
  includesMeetingAudio: boolean
  startedAt: number
  levels: number[] // recent input levels (0..1), newest last, for the waveform
}

const HISTORY = 48
let snapshot: Snapshot = {
  sessionId: null,
  source: "room",
  includesMicrophone: false,
  includesMeetingAudio: false,
  startedAt: 0,
  levels: Array(HISTORY).fill(0),
}
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
  async start(
    sessionId: string,
    source: RecordingSource = "room",
    options: MeetingAudioOptions = { includeMicrophone: false, reduceBackgroundNoise: true },
  ) {
    const meeting = source === "meeting"
    const includeMicrophone = !meeting || options.includeMicrophone
    if (!navigator.mediaDevices || (includeMicrophone && !navigator.mediaDevices.getUserMedia)) {
      throw new Error("This browser can't record here. Open Dzomdu at http://localhost.")
    }
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
        if (!snapshot.sessionId) return
        emit({ includesMeetingAudio: false })
        if (stream?.getAudioTracks().some((t) => t.readyState === "live")) {
          toast.warning("Meeting audio stopped. Only your microphone is recording now.")
        } else {
          toast.warning("Meeting audio stopped. The recording is being saved.")
          void recorder.stop()
        }
      })
    }
    if (includeMicrophone) {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            // Cancel speaker echo in calls; room recordings keep distant voices.
            echoCancellation: meeting,
            noiseSuppression: meeting && options.reduceBackgroundNoise,
            autoGainControl: true,
          },
        })
        if (
          meeting && options.reduceBackgroundNoise &&
          stream.getAudioTracks()[0]?.getSettings().noiseSuppression !== true
        ) {
          toast.warning("Microphone noise reduction could not be confirmed. Nearby noise may still be recorded.")
        }
      } catch (e) {
        if (meeting) {
          toast.warning("Microphone unavailable. Only the meeting audio is recording, not your voice.")
        } else if ((e as Error).name === "NotAllowedError") {
          throw new Error("Microphone access was denied. Allow it in the browser and in macOS settings.")
        } else {
          throw e
        }
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
    emit({
      sessionId,
      source,
      includesMicrophone: stream !== null,
      includesMeetingAudio: meeting,
      startedAt: Date.now(),
      levels: Array(HISTORY).fill(0),
    })
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
    emit({ sessionId: null, includesMicrophone: false, includesMeetingAudio: false,
      levels: Array(HISTORY).fill(0) })
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
