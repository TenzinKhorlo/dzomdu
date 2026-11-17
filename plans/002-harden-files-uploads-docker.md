# Plan 002: Harden file handling (vault-bounded delete, upload cap, ffmpeg protocols) and Docker defaults

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- dzomdu/pipeline.py dzomdu/audio.py dzomdu/server/app.py Dockerfile docker-compose.yml docker/`
> The working tree had uncommitted edits to `dzomdu/server/app.py` when this plan was written; anchor on the quoted code, not line numbers.
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (Docker volume permissions; ffmpeg flags)
- **Depends on**: none (independent of Plan 001, but both edit `server/app.py` — merge one before starting the other, or rebase)
- **Category**: security
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

The vault and data folders can be synced or shared, and uploads are untrusted files. Four gaps:
1. `Pipeline.delete_record` unlinks the `note_path` stored in a meeting's JSON without checking it lies inside the vault, unlike the rename/edit flows that do. A tampered or stale record can delete an arbitrary file.
2. `GET /api/meetings/{id}/audio` serves whatever path is in the record's `source_audio`.
3. `POST /api/upload` only checks the file extension and has no size cap; ffmpeg then probes by *content* with all protocols enabled (playlist-style inputs disguised as `.wav` can make it read other local files or open network connections).
4. The Docker image runs as root with `chmod 777` data dirs. (The Dockerfile comment says this is deliberate so a compose `user:` override "just works"; this plan keeps that working and only adds a safer default where it can be done without breaking existing volumes.)

## Current state

- `dzomdu/pipeline.py` `delete_record`:
  ```python
  data = json.loads(path.read_text(encoding="utf-8"))
  if data.get("note_path"):
      Path(data["note_path"]).unlink(missing_ok=True)
  source = Path(data.get("source_audio") or "")
  if recordings_dir is not None and source.is_file() and source.parent == recordings_dir:
      source.unlink(missing_ok=True)
  path.unlink()
  ```
  The guarded pattern to copy is in `rename_meeting` in the same file:
  ```python
  note = Path(data["note_path"])
  if note.is_symlink() or not note.resolve().is_relative_to(self.cfg.vault.resolve()):
      raise ValueError("Move this meeting note into the current vault before renaming it")
  ```
- `dzomdu/server/app.py`:
  ```python
  @app.get("/api/meetings/{meeting_id}/audio")
  def meeting_audio(meeting_id: str) -> FileResponse:
      r = record_or_404(meeting_id)
      candidates = [Path(r.get("source_audio") or "")]
      if sha := r.get("audio_sha"):
          candidates.append(cfg.cache_dir / sha[:16] / "audio.wav")
      for path in candidates:
          if path.is_file():
              return FileResponse(path, media_type=_audio_type(path))
  ```
  and `upload`: suffix check against `UPLOAD_SUFFIXES`, then `shutil.copyfileobj(file.file, out)` into `manager.recordings_dir / f"{s.id}{suffix}"` — no size limit.
  `source_audio` may legitimately be a user file anywhere on disk (CLI `dzomdu process -a /path/to/file`), so the player must keep working for those; only restrict by file type.
- `dzomdu/audio.py` `decode`:
  ```python
  cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path)]
  ```
  Search for any other `ffmpeg`/`subprocess` call: `grep -rn "ffmpeg" dzomdu/ --include=*.py` and apply the same flags to each *input* the app does not generate itself.
- `Dockerfile`: `RUN mkdir -p /config /vault /data /models && chmod 777 /config /vault /data /models`, no `USER`, `CMD ["dzomdu", "ui", "--host", "0.0.0.0", ...]`. `docker/entrypoint.sh` runs first (read it before Step 5). `docker-compose.yml` publishes `127.0.0.1:${DZOMDU_PORT}:8765`.
- Conventions: tests live in `tests/`, use fixtures from `tests/conftest.py` (`tests/test_meetings.py` and `tests/test_server.py` cover delete). Errors in routes are `HTTPException`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Tests | `pytest -q` | all pass |
| Lint | `ruff check .` | exit 0 |
| Docker smoke (Step 5 only) | `docker build -t dzomdu:test . && docker run --rm --entrypoint python dzomdu:test /app/docker/smoke.py` | exit 0 |

## Scope

**In scope**: `dzomdu/pipeline.py`, `dzomdu/audio.py`, `dzomdu/server/app.py` (only `meeting_audio`, `upload`), `dzomdu/config.py` (only a new upload-limit setting if you choose config over env), `Dockerfile`, `docker/entrypoint.sh`, tests (`tests/test_meetings.py`, `tests/test_server.py`, new `tests/test_audio_safety.py`).
**Out of scope**: Host/Origin/CSP work (Plan 001), UI changes, changing where recordings are stored, any model/ASR code.

## Git workflow
Branch `advisor/002-harden-files-uploads-docker`; one commit per step; short imperative messages like the existing log. Do not push.

## Steps

### Step 1: Bound `delete_record` to the vault
In `delete_record`, before unlinking `note_path`: skip the unlink (do not raise — deleting the record must still succeed) when the note is a symlink or `resolve()` is not under `self.cfg.vault.resolve()`; log a warning via `logging.getLogger(__name__).warning(...)`. Tests in `tests/test_meetings.py`: (a) normal delete removes the note; (b) a record whose `note_path` points to a file outside the vault leaves that file in place while the record is removed; (c) a symlinked note is not followed.
**Verify**: `pytest -q tests/test_meetings.py` → pass with 3 new tests.

### Step 2: Restrict what `meeting_audio` will serve
For each candidate path require `path.suffix.lower() in UPLOAD_SUFFIXES` (the same set the upload accepts) in addition to `is_file()`. Test in `tests/test_server.py`: a record whose `source_audio` is `<tmp>/secret.txt` → 404; a `.wav` source → 200.
**Verify**: `pytest -q tests/test_server.py -k audio` → pass.

### Step 3: Cap upload size
Replace `shutil.copyfileobj(file.file, out)` with a chunked copy (1 MiB) that counts bytes; when the total exceeds the limit, close and delete the partial file, remove the just-created session (`manager.sessions.pop(s.id, None)` — check `SessionManager` for a proper cancel/discard method and prefer it), and raise `HTTPException(413, "That file is larger than the upload limit (<N> MB)")`. Limit: env `DZOMDU_MAX_UPLOAD_MB` default `4096`. Create the session *after* a successful copy if that is simpler and keeps behaviour identical for valid uploads. Test with a tiny limit via monkeypatch env (e.g. 1 MB limit, 2 MB body) → 413 and no file left in `recordings_dir`.
**Verify**: `pytest -q tests/test_server.py -k upload` → pass.

### Step 4: Restrict ffmpeg input protocols
In `decode` add `"-protocol_whitelist", "file,pipe"` immediately before `"-i"`. Apply to any other third-party-input ffmpeg call you found. Also stop echoing raw stderr to API clients: keep the full text in the exception for logs but have `audio.decode` raise `RuntimeError(f"ffmpeg could not decode {path.name}")` plus the first stderr line only. Create `tests/test_audio_safety.py` (skip if `shutil.which("ffmpeg")` is None): (a) a normal 1 s WAV and an MP3/M4A if the repo already has fixtures decode fine; (b) a text file named `x.wav` containing `ffconcat version 1.0\nfile '/etc/hosts'\n` raises `RuntimeError`.
**Verify**: `pytest -q tests/test_audio_safety.py tests/test_pipeline.py tests/test_live.py` → pass. If an mp4/m4a/mov fixture or real-file manual check (`dzomdu process` on a small .m4a) fails with the whitelist, STOP.

### Step 5: Docker — non-root default, only if it stays compatible
Read `docker/entrypoint.sh` and `DOCKER.md`. Goal: the image runs as an unprivileged user by default while `user:` overrides and existing named volumes keep working. Create user `dzomdu` (uid 10001) in the Dockerfile, keep the directories world-writable (existing rationale), add `USER 10001` before `ENTRYPOINT`. Do NOT remove the 777 modes. Do not pass `HF_TOKEN` differently in this plan.
**Verify**: build + run the smoke command above; then `docker compose up -d`, `curl -s http://127.0.0.1:8765/api/settings` returns JSON, `docker compose exec dzomdu id` shows non-root, and a fresh start with empty named volumes writes `/config/config.toml`. If any of these fail, revert Step 5 only and record "deferred" in the status row.

## Test plan
Covered per step. Pattern: `tests/test_meetings.py` for delete, `tests/test_server.py` for routes. Final: full `pytest -q`, `ruff check .`.

## Done criteria
- [ ] `pytest -q` exits 0 with the new tests; `ruff check .` exits 0
- [ ] `grep -n "protocol_whitelist" dzomdu/audio.py` matches
- [ ] `grep -n "is_relative_to" dzomdu/pipeline.py` shows the guard inside `delete_record`
- [ ] Uploading a file larger than the limit returns 413 and leaves nothing in `recordings_dir` (test)
- [ ] Docker smoke test passes (or Step 5 explicitly marked deferred with a reason)
- [ ] Only in-scope files modified; `plans/README.md` updated

## STOP conditions
- A real recording format (m4a/mp4/mov) fails to decode with `-protocol_whitelist file,pipe`.
- The upload endpoint's session creation can't be undone cleanly (no discard method) and the fix needs changes in `server/sessions.py`.
- Step 5 breaks existing bind-mounted volume permissions you can't reproduce a fix for.
- Excerpts above don't match the code.

## Maintenance notes
- Any new code that unlinks a path read from a JSON record must apply the same vault check (consider a shared helper if a third site appears).
- New ffmpeg call sites need the same whitelist.
- Deferred: hashing/validating uploaded files by magic bytes; network exposure guidance in DOCKER.md (not planned; see plans/README.md).

## Execution outcome (2026-11-12)

Steps 1-4 implemented and reviewed on branch `advisor/002-harden-files-uploads-docker`. **Step 5 deferred:** the image sets `HOME=/data/home`, `XDG_CACHE_HOME=/data/cache`, `HF_HOME=/models/huggingface`, `TORCH_HOME=/models/torch`; on existing deployments those subdirectories were created by root inside the named volumes (typically mode 755), and a Linux `./vault` bind mount is owned by the host user, so a default `USER 10001` cannot write to them and `chmod 777` on the top-level directories does not help. A safe version needs `docker/entrypoint.sh` to start as root, fix ownership of those subdirectories, then drop privileges (for example with `gosu`/`setpriv`) — a separate plan. Minor nit: `.upload-*.part` files left by a hard crash mid-upload are not cleaned up (`_recover_orphans` only globs `*.pcm`).
