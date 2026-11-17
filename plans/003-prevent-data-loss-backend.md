# Plan 003: Stop losing meetings and pages to crashes, bad front-matter and late failures (backend)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- dzomdu/vault.py dzomdu/audio.py dzomdu/pipeline.py dzomdu/config.py dzomdu/server/sessions.py dzomdu/server/app.py`
> `dzomdu/server/app.py` had uncommitted edits when this plan was written. Anchor on the quoted code, not line numbers. A mismatch is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (changes when a meeting record is first written)
- **Depends on**: none (Plan 004 builds on Step 3)
- **Category**: bug
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

Four independent ways to lose or hide data, all hitting the "my meeting disappeared" experience:
1. A hand-edited Obsidian file with one bad YAML front-matter line (a stray colon or tab in a person, project, template or note file) makes `split_frontmatter` raise `yaml.YAMLError`, which 500s `/api/speakers`, `/api/projects` (polled app-wide), `/api/info`, the meeting detail page, and the note write that runs *after* the LLM has finished.
2. WAV and JSON cache files are written non-atomically; a crash leaves a truncated `audio.wav` that is silently reused, or a truncated JSON cache that raises on every retry.
3. A new meeting's record is only written inside `write_note` (end of the pipeline). Any non-`LLMError` failure while summarising (template render error, disk error, odd LLM JSON) leaves state `error` with **no saved record**, and the transcript plus the human's speaker review exist only in memory.
4. Finished sessions keep the full decoded audio array (`s.analysis`) in RAM (~230 MB per hour of audio) until the server restarts.

## Current state

- `dzomdu/vault.py` (top):
  ```python
  def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
      if text.startswith("---\n"):
          end = text.find("\n---", 4)
          if end != -1:
              meta = yaml.safe_load(text[4:end]) or {}
              body = text[end + 4 :].lstrip("\n")
              return (meta if isinstance(meta, dict) else {}), body
      return {}, text
  ```
  Callers: `grep -rn "split_frontmatter" dzomdu/` — includes `server/markdown.py note_to_html`, `vault.person_profile`, `vault.project_context`, `notes/templates.py parse_template`, `transcript.py` edit paths, `retitle_note`. Only `edit_transcript` (in `server/app.py`) and `projects.overview` currently catch `YAMLError`.
- `dzomdu/vault.py` also has `atomic_write_text(path, text)` (writes `.{name}.tmp` then replaces) used by `write_note`/`save_record`, but these still use plain `write_text`: `ensure_person` (~line 144), `update_person` (~171), `rename_person` (~177), `ensure_project` (~211). `dzomdu/config.py:212`: `path.write_text(dump_config(cfg), encoding="utf-8")` followed by a `chmod(0o600)`.
- `dzomdu/audio.py`:
  ```python
  def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(wav_bytes(samples, sample_rate))
  ```
- `dzomdu/pipeline.py` caches: `cache.write_text(json.dumps([asdict(s) for s in segments]))` in `_diarize` and `cache.write_text(json.dumps([asdict(w) for w in words]))` in `_transcribe`; both read with `json.loads(cache.read_text())` and no error handling.
- `dzomdu/server/sessions.py`:
  - `_analyze_job` ends with `s.analysis, s.record = analysis, analysis.record` then `s.state = "review"` (or `_summarize_job(... overwrite=False)` when there are no turns).
  - `_summarize_job` wraps everything in `try: ... except Exception as exc: s.state, s.error = "error", f"{exc.__class__.__name__}: {exc}"`; inside, only `LLMError` is tolerated, then `s.note_path = pipe.write_note(...)` then `s.state = "done"`.
  - `regenerate` requires `retryable = s.state == "error" and s.note_path is not None`.
- `pipeline.write_note` ends with `self.save_record(record, note_sha=..., notes=notes)`. `save_record` is `@meeting_locked`, takes `note_sha` and `notes` optionally, preserves `_tasks` from an existing file.
- Conventions: tests use fake ASR/diarizer/LLM from `tests/conftest.py`; see `tests/test_server.py` (`wait_for` helper, session flows) and `tests/test_pipeline.py`. Match them.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| All tests | `pytest -q` | all pass |
| Targeted | `pytest -q tests/test_pipeline.py tests/test_server.py tests/test_projects.py tests/test_notes.py` | pass |
| Lint | `ruff check .` | exit 0 |

## Scope

**In scope**: `dzomdu/vault.py`, `dzomdu/audio.py`, `dzomdu/pipeline.py`, `dzomdu/config.py`, `dzomdu/server/sessions.py`, `dzomdu/server/markdown.py` (only if needed), `dzomdu/llm/client.py` (only the `resp.json()` parsing wrapper in Step 3), `dzomdu/okf.py` (only adding `strict=True` to its three `split_frontmatter` calls, see Step 1), `dzomdu/server/app.py` (ONLY the single `split_frontmatter` call in the regenerate path that reads the note's template, see Step 1), plus tests (`tests/test_notes.py`, `tests/test_pipeline.py`, `tests/test_server.py`, `tests/test_projects.py`, new `tests/test_vault_frontmatter.py`).
**Out of scope**: web UI (Plan 004 covers recovered recordings and recorder socket handling), any other change to `server/app.py` routes (if a route needs a change beyond the one call named above, STOP), speaker rename propagation (see Plan 006 maintenance notes).

## Git workflow
Branch `advisor/003-prevent-data-loss-backend`; one commit per step; short imperative messages (e.g. "Write meeting records and notes atomically" is the existing style). Do not push.

## Steps

### Step 1: Make front-matter parsing tolerant for reads
Change `split_frontmatter(text, strict=False)`: on `yaml.YAMLError`, when `strict` is False, log a warning (`logging.getLogger(__name__)`) and return `({}, body_after_closing_marker)`; when `strict=True` re-raise. Set `strict=True` only where the code currently relies on the exception or must not rewrite a file it couldn't parse: `retitle_note`, `update_person`, and the existing `edit_transcript`/`overview` handlers (check each by reading its `except yaml.YAMLError` block; keep those working). Add `tests/test_vault_frontmatter.py`: a note/person/project/template file with `title: a: b` front-matter → `person_profile`, `project_context`, `note_to_html` and `list_templates` all return normally (empty meta), and `update_person` on such a file raises (does not overwrite).
**Callers that must stay strict (found during the first execution attempt — the original list missed them):** `dzomdu/okf.py` calls `split_frontmatter` at three places (reading a people/profile source ~line 179, and two exports ~lines 230 and 241); `tests/test_okf.py::test_export_refuses_existing_destination_and_cleans_failed_bundle` requires `export_bundle` to **raise** `yaml.YAMLError` on a profile with invalid front-matter, so pass `strict=True` at all three. In `dzomdu/server/app.py` the regenerate path reads the note's template with `split_frontmatter(Path(record.note_path).read_text(...))` (~line 845) and previously surfaced a "Fix the note's frontmatter" warning when YAML was invalid; pass `strict=True` there so that behaviour is kept (keep its existing `except yaml.YAMLError`). `dzomdu/chat.py` (~line 285, reads only the note body) and `dzomdu/projects.py` should stay lenient. Run `grep -rn "split_frontmatter" dzomdu/` yourself and decide each remaining caller by what its surrounding `except` block expects.
**Verify**: `pytest -q tests/test_vault_frontmatter.py tests/test_notes.py tests/test_projects.py tests/test_okf.py` → pass.

### Step 2: Atomic writes and self-healing caches
- `write_wav`: write to `path.with_name(f".{path.name}.tmp")` then `os.replace`.
- `Pipeline._diarize` and `_transcribe`: write caches with `atomic_write_text`, and read them via a small helper that returns `None` when the file is unreadable/invalid JSON (delete the bad file, recompute). Same for any cached `audio.wav` reuse: before reusing, check that the WAV header's frame count × 2 bytes ≈ file size (use the stdlib `wave` module); on mismatch re-decode.
- `vault.py` `ensure_person`, `update_person`, `rename_person`, `ensure_project` writes → `atomic_write_text`.
- `config.save_config`: write a temp file created with mode `0o600` (`os.open(..., 0o600)`), then `os.replace`, so the file is never world-readable and never half-written.
Tests: truncated cache file (write `"[{"`) → pipeline recomputes instead of raising (use the fake ASR in `tests/test_pipeline.py`); truncated WAV → re-decoded; `save_config` leaves mode `0o600` (`stat`).
**Verify**: `pytest -q tests/test_pipeline.py tests/test_server.py` → pass.

### Step 3: Save the transcript record before the LLM step and make first-run failures retryable
In `_summarize_job` when `overwrite` is False and `s.record` has turns: call `pipe.save_record(s.record)` **before** `pipe.summarize(...)` and set `s.record.notes_stale = True` for that interim save (check `MeetingRecord` for the field; `write_note` resets it to False). In the outer `except`, keep state `"error"`. Update `regenerate`'s `retryable` rule to `s.state == "error" and s.record is not None and (s.note_path is not None or (self.cfg.meetings_dir / f"{s.record.id}.json").exists())`. Make sure `write_note(..., overwrite=False)` still creates the note when `record.note_path` is unset.
Also wrap `resp.json()`-style parsing failures in `dzomdu/llm/client.py` (search `resp.json()` around lines ~215 and ~240) so a malformed LLM response raises `LLMError`, not `KeyError`/`ValueError`.
Tests in `tests/test_server.py`: force `pipeline.write_note` to raise `OSError` once on a first-run session (monkeypatch) → session ends `error`, the meeting JSON exists with the turns, and calling `regenerate` succeeds and produces a note; and a `LLMError` still yields the existing "Summary skipped" path unchanged.
**Verify**: `pytest -q tests/test_server.py tests/test_llm.py tests/test_pipeline.py` → pass.

### Step 4: Release analysis audio when a session finishes
In `_summarize_job`, after a successful `write_note` (state `"done"`) and in the `except` branch, set `s.analysis = None`. Check every use of `s.analysis` (`grep -n "\.analysis" dzomdu/server/sessions.py`): the speaker-clip code path (`~line 517`, `~537`) already tolerates `None` — confirm by reading it and add a test that requesting a speaker clip for a finished meeting returns the same 404/graceful result it returns for sessions reopened from disk. Do **not** clear `analysis` while state is `review`.
**Verify**: `pytest -q tests/test_server.py` → pass, including the new "finished session has no analysis" test.

## Test plan
Listed per step. Structural patterns: `tests/test_server.py` (sessions, `wait_for`), `tests/test_pipeline.py` (fakes). Final: `pytest -q` and `ruff check .`.

## Done criteria
- [ ] `pytest -q` exits 0 including all new tests; `ruff check .` exits 0
- [ ] `grep -n "yaml.safe_load" dzomdu/vault.py` appears only inside the guarded helper
- [ ] `grep -rn "\.write_text(" dzomdu/vault.py dzomdu/config.py dzomdu/pipeline.py` returns no meeting/person/project/cache/config writes (only `atomic_write_text`)
- [ ] After a forced failure in the first-run summarise step, `<meetings_dir>/<id>.json` exists (test)
- [ ] `s.analysis` is `None` for sessions in `done` state (test)
- [ ] Only in-scope files modified; `plans/README.md` updated

## STOP conditions
- Saving the record early changes what `/api/meetings` or the dashboard shows for a meeting still in review/summarising in a way existing tests can't absorb (e.g. duplicate rows). Report the failing tests instead of editing them.
- `MeetingRecord` has no `notes_stale` field or `save_record` behaves differently from the excerpt.
- Any caller of `split_frontmatter` needs a decision you can't make from its surrounding `except` block.

## Maintenance notes
- New code that parses YAML front-matter from user-editable files should use the lenient default and handle empty meta.
- Plan 004 surfaces recovered recordings; it assumes Step 3's "record exists even when notes failed" behaviour.
- Baseline note from the first attempt: `tests/test_server.py::test_shell_and_info` failed before any change on the executor's machine (it asserts the LLM status is not ok, so it likely fails when something answers on the default LLM port); do not count it against this plan. Also, a first-run retry that hits an `LLMError` says "Your existing notes were kept", which is misleading when none exist; a wording fix is a follow-up, not part of this plan.
- Reviewer focus: the interim `save_record` (must not mark notes as generated), and that `retryable` can't be reached for meetings whose JSON was deleted.
