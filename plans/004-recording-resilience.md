# Plan 004: Make recording resilient (socket drops, leaked mic, recovered recordings)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- web/src/lib/recorder.ts web/src/components/record/meeting-form.tsx web/src/app/page.tsx dzomdu/server/sessions.py dzomdu/server/app.py web/tests/recorder.test.mjs`
> (`dzomdu/server/app.py` and several `web/src` files had uncommitted edits when this plan was written — anchor on the quoted code.) A mismatch is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (browser audio APIs; needs a manual recording test)
- **Depends on**: plans/003-prevent-data-loss-backend.md (soft dependency: Step 4 assumes the backend already keeps a record even when notes fail; the plan still works without it)
- **Category**: bug
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

Recording is the product's core promise and the failure modes are silent:
1. The browser recorder (`web/src/lib/recorder.ts`) never listens for WebSocket `close`/`error`. If the connection drops, every audio chunk is silently discarded while the UI keeps saying "recording"; the server meanwhile finishes the session with whatever it received.
2. If `recorder.start()` throws after acquiring the microphone/shared tab (e.g. the worklet fails to load), the streams are not released, so the browser's "mic in use" indicator stays on.
3. `MeetingForm.startRecording` calls `recorder.release()` in its `catch` even when the failure was `POST /api/sessions` → 409 "A recording is already in progress"; that call tears down the recording that *is* in progress in this tab.
4. After a crash, the server converts leftover `.pcm` files to `.wav` at startup and reports them in `/api/info` as `recovered`, but nothing in the web UI reads that field and nothing turns the audio into a meeting. The user's recording is on disk but invisible.

## Current state

- `web/src/lib/recorder.ts` `start()` ends with:
  ```ts
  ctx = new AudioContext()
  await ctx.audioWorklet.addModule("/recorder-worklet.js")
  node = new AudioWorkletNode(ctx, "pcm-recorder", { processorOptions: { targetRate: 16000 } })
  ...
  const queue: ArrayBuffer[] = []
  const socket = new WebSocket(wsUrl(`/api/sessions/${sessionId}/audio`))
  socket.binaryType = "arraybuffer"
  socket.onopen = () => queue.splice(0).forEach((b) => socket.send(b))
  ws = socket
  node.port.onmessage = ({ data }) => {
    if (socket.readyState === WebSocket.OPEN) socket.send(data.pcm)
    else if (socket.readyState === WebSocket.CONNECTING) queue.push(data.pcm)
    ...
  ```
  `stop()` flushes, sends `"stop"` and calls `release()`; `release()` stops streams, closes ctx, closes the socket after 500 ms, resets state via `emit(...)`. Module-level variables: `stream`, `meetingStream`, `ctx`, `node`, `ws`, `snapshot`, `listeners`, `recorder` (object with `start/stop/release`), `toast` imported from `@/lib/toast`.
- `web/src/components/record/meeting-form.tsx`:
  ```ts
  async function startRecording(source: RecordingSource = "room") {
    setBusy("record")
    let id: string | null = null
    try {
      id = (await api<{ id: string }>("/api/sessions", { method: "POST", json: payload() })).id
      await recorder.start(id, source, { includeMicrophone, reduceBackgroundNoise })
      onSession(id)
    } catch (e) {
      recorder.release() // drop any microphone or shared-tab stream that was already open
      if (id) await api(`/api/sessions/${id}/cancel`, { method: "POST" }).catch(() => {})
  ```
- Server: `dzomdu/server/sessions.py` `_recover_orphans()` converts `recordings/*.pcm` (≥ 2 s) to WAV once and unlinks the PCM, so it is reported only on that startup; `SessionManager.create(meta, kind)`, `start_upload(s, path)` (analysis starts for an existing audio file), `recordings_dir = cfg.data_dir / "recordings"`. `app.py`: `info()` returns `"recovered": [str(p) for p in manager.recovered]`; `POST /api/upload` shows the pattern for creating a session from audio (`s = manager.create(meeting_meta(meta_dict), "upload")`, then `manager.start_upload(s, dest)`). Records live in `cfg.meetings_dir/<id>.json` with a `source_audio` field.
- `web/src/lib/api.ts:304` already declares `recovered: string[]` on the `Info` type; `web/src/app/page.tsx` is the Overview page; Astryx `Banner` (`@astryxdesign/core/Banner`) is already used in `web/src/app/meetings/view/page.tsx` — copy that usage for the notice. Buttons: use `@/components/button`; toasts: `@/lib/toast`.
- Tests: `web/tests/recorder.test.mjs` (node --test; it runs `recorder.ts` compiled in a `vm` with fake `AudioContext`, `WebSocket`, `navigator.mediaDevices`; note `require("@/lib/toast")` is stubbed there — extend that harness). Python: `tests/test_server.py`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Web tests | `cd web && npm test` | all pass |
| Lint + types | `cd web && npm run lint && npx tsc --noEmit` | exit 0 |
| Python | `pytest -q tests/test_server.py` | pass |
| Build | `cd web && npm run build` | succeeds |

## Scope

**In scope**: `web/src/lib/recorder.ts`, `web/tests/recorder.test.mjs`, `web/src/components/record/meeting-form.tsx`, `web/src/app/page.tsx` (+ one new small component `web/src/components/recovered-recordings.tsx`), `dzomdu/server/app.py` (two new routes only), `dzomdu/server/sessions.py` (one helper), `tests/test_server.py`.
**Out of scope**: the classic UI (`dzomdu/server/static`), reconnect/resume of a dropped WebSocket (note as follow-up), live transcription logic, any styling migration.

## Git workflow
Branch `advisor/004-recording-resilience`; one commit per step; short imperative messages. Do not push.

## Steps

### Step 1: Recorder cleans up after itself and reports a dropped socket
In `recorder.ts`:
- Wrap the body of `start()` after the first resource is acquired in `try { ... } catch (e) { cleanup(); throw e }` where `cleanup()` is the existing release logic factored into an internal function that does not require `snapshot.sessionId` to be set.
- Add `socket.onclose` / `socket.onerror`: if the socket closes while `snapshot.sessionId === sessionId` and no stop was requested (add a module flag `stopping`, set in `stop()` and cleared in `start()`), call `toast.error("Connection to Dzomdu was lost. Recording stopped; what was captured is being saved.")` and `release()`.
**Verify**: add tests to `web/tests/recorder.test.mjs`: (a) `addModule` rejects → streams are stopped (fake tracks record `stop()` calls) and `snapshot.sessionId` stays null; (b) fake socket fires `close` while recording → `release()` ran and a toast was raised; (c) normal `stop()` does not raise the toast. `cd web && npm test` → all pass (13 existing + new).

### Step 2: Don't kill an active recording when starting a second fails
In `meeting-form.tsx` `startRecording`: only call `recorder.release()` when `recorder.start` was actually reached (track with a local `started` flag set just before `await recorder.start(...)`). If `POST /api/sessions` fails, just toast the error. Also disable the Record button while `useRecorder().sessionId` is set (read it via `useRecorder()`), with the tooltip text "A recording is already in progress".
**Verify**: `cd web && npm run lint && npx tsc --noEmit` → exit 0. Manual check listed under Test plan.

### Step 3: Backend — list and process recovered recordings
In `sessions.py` add `unprocessed_recordings(self) -> list[Path]`: `*.wav` files in `recordings_dir` that (a) are ≥ 2 s, (b) are not the `audio_path` of any in-memory session, and (c) are not the `source_audio` of any record JSON (scan `cfg.meetings_dir/*.json` once, reading only the `source_audio` key). In `app.py` add `GET /api/recordings/unprocessed` → `[{"name": p.name, "seconds": <float>, "modified": <iso>}]` and `POST /api/recordings/unprocessed/{name}/process` → validates `name` is exactly one of the listed names (no path separators), then does what `upload` does with the existing file: `s = manager.create(meeting_meta({}), "upload"); manager.start_upload(s, path)`; return `{"id": s.id}`. Never accept a path from the client.
Tests in `tests/test_server.py`: create a `.wav` in `recordings_dir` → listed; process → a session id is returned and the session reaches `review`/`done` with the fake backends; a WAV referenced by an existing record is not listed; `name="../x.wav"` → 404.
**Verify**: `pytest -q tests/test_server.py` → pass.

### Step 4: Surface recovered recordings on the Overview page
New `web/src/components/recovered-recordings.tsx`: `useApi<{name:string;seconds:number;modified:string}[]>("/api/recordings/unprocessed")` (no polling interval); when non-empty render an Astryx `Banner` (`status="warning"`, `title="Unprocessed recording found"`, body "A recording from <date> (<n> min) was saved but never turned into a meeting.") with a "Process it" button per item that POSTs the process route and `router.push("/record/?session=" + id)`. Render it at the top of `web/src/app/page.tsx` above the KPI cards. Keep copy sentence case without trailing periods in labels.
**Verify**: `cd web && npm run lint && npx tsc --noEmit && npm run build` → exit 0; then manual: place a `.wav` in `<data_dir>/recordings/`, run `dzomdu ui`, open the Overview → the banner appears; click "Process it" → the Record page shows the processing session.

## Test plan
Step 1 tests extend `web/tests/recorder.test.mjs` (follow its existing `setup()` fake-environment pattern); Step 3 tests extend `tests/test_server.py`. Manual test (record this in the PR): (1) start a recording, kill the server mid-way → toast appears, mic indicator turns off; (2) start a recording, open the New meeting form in another tab of the same app, click Record → the first recording keeps running (button disabled); (3) the Overview banner flow above.

## Done criteria
- [ ] `cd web && npm test && npm run lint && npx tsc --noEmit && npm run build` all exit 0, new recorder tests present
- [ ] `pytest -q` exits 0 including the new route tests
- [ ] `grep -n "onclose" web/src/lib/recorder.ts` matches
- [ ] `grep -n "unprocessed" dzomdu/server/app.py` shows both routes; no route accepts a filesystem path from the client
- [ ] Only in-scope files modified; `plans/README.md` updated

## STOP conditions
- The `recorder.test.mjs` harness can't simulate a socket `close` without a large rewrite (report instead of rewriting it).
- Listing "unprocessed" WAVs would also list files belonging to an in-progress session or an existing meeting (the check in Step 3 can't be made reliable).
- Reconnect/resume turns out to be required to make Step 1 acceptable — stop and report; it is deliberately out of scope.

## Maintenance notes
- A real reconnect (resume the same session on a new socket) is the proper long-term fix for transient drops; Step 1 only makes the failure visible and safe.
- The unprocessed-recordings list is derived from disk, so it will also show WAVs a user dropped there by hand; that is intended.
- Reviewer focus: the `stopping` flag ordering in `stop()`/`release()`, and that Step 2 can't leave the button permanently disabled after a failed start.
