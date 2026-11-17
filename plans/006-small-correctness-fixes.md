# Plan 006: Fix five small correctness bugs (clearing profile fields, blank renames, validation errors, date shift, token estimate)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- dzomdu/vault.py dzomdu/speakers/store.py dzomdu/llm/summarize.py dzomdu/server/app.py web/src/lib/api.ts web/src/lib/format.ts tests/test_speakers.py tests/test_llm.py`
> (`dzomdu/server/app.py` had uncommitted edits when this plan was written; anchor on quoted code.) A mismatch is a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S–M (five independent steps; each is its own commit)
- **Risk**: LOW
- **Depends on**: none. If plan 003 has landed, `vault.py` writes are already atomic — keep them that way.
- **Category**: bug
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

Five bugs that each make the UI lie or mis-handle input, none of them large:
1. Clearing a person's Role/Organisation/Bio in People shows "Profile saved" but the vault file keeps the old values (the update is gated on truthiness).
2. Renaming a voice accepts a blank/whitespace name (creating an empty-named speaker and an `Untitled.md` person note) and silently does nothing in the vault when the target note already exists.
3. FastAPI validation errors (HTTP 422, `detail` is a list) display as `[object Object]` in toasts.
4. Date-only values (`YYYY-MM-DD` task due/reminder dates) are parsed as UTC, so west of UTC "Due Oct 14" shows as "Oct 13".
5. The summariser sizes chunks at ~4 characters per token; for Devanagari/Tibetan text (Nepali is a supported language) that undercounts, so Ollama silently truncates over-long chunks and notes ignore parts of the meeting.

## Current state

- `dzomdu/vault.py`:
  ```python
  def ensure_person(self, name, role=None, organisation=None, bio=None):
      path = self.person_path(name)
      if path.exists():
          if role or organisation or bio:
              self.update_person(name, role=role, organisation=organisation, bio=bio)
          return path
  ...
  def update_person(self, name, role=None, organisation=None, bio=None):
      ...
      if role:
          meta["role"] = role
      if organisation:
          meta["organisation"] = organisation
      if bio:
          if re.search(r"^## Bio\s*$", body, re.MULTILINE):
              body = re.sub(r"(^## Bio\s*$\n)(.*?)(?=^#{1,2}\s|\Z)", lambda m: m.group(1) + "\n" + bio.strip() + "\n\n", body, count=1, flags=re.MULTILINE | re.DOTALL)
          else:
              body = body.rstrip() + f"\n\n## Bio\n\n{bio.strip()}\n"
  ```
  Callers: `server/app.py` `save_person` (`PersonBody` fields default to `None`; the web People form sends strings, `""` when cleared), `cli.py:395`, `pipeline.py:295,330` (name only → fields `None`). So `None` must keep meaning "leave unchanged" and `""` must mean "clear".
- `dzomdu/speakers/store.py` `rename(old, new)`: raises `KeyError` if unknown, `ValueError` on duplicate, then `UPDATE speakers SET name = ? ... (new.strip(), ...)` — never checks that `new.strip()` is non-empty. `vault.rename_person(old, new)`: `if src.exists() and not dst.exists(): ... dst.write_text(...); src.unlink()` (silent no-op otherwise). Route: `POST /api/speakers/rename` in `server/app.py` (`RenameBody`, then `pipeline.store.rename` → HTTP 404/409 mapping, then `pipeline.vault.rename_person`).
- `web/src/lib/api.ts`:
  ```ts
  if (!res.ok) {
    throw new ApiError(data?.detail ?? `${res.status} ${res.statusText}`, res.status)
  }
  ```
- `web/src/lib/format.ts`:
  ```ts
  export function shortDate(iso: string | null | undefined): string {
    if (!iso) return ""
    return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" })
  }
  ```
  Called with full timestamps (meeting dates) and with date-only strings (`task-row.tsx`, `action-list.tsx`).
- `dzomdu/llm/summarize.py`: `def estimate_tokens(text: str) -> int: return len(text) // 4 + 1`; `chunk_lines(lines, max_tokens)`; default `max_chunk_tokens: int = 6000`; `config.py` default `num_ctx` is 16384.
- Conventions: Python tests in `tests/` (`test_speakers.py` for the store, `test_llm.py`, `test_notes.py` for vault/people), web tests are `node --test` files in `web/tests/*.test.mjs` (see `transcript-edits.test.mjs` for a pure-function pattern).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Python | `pytest -q` | all pass |
| Lint | `ruff check .` | exit 0 |
| Web | `cd web && npm run lint && npx tsc --noEmit && npm test` | exit 0 |

## Scope

**In scope**: `dzomdu/vault.py`, `dzomdu/speakers/store.py`, `dzomdu/server/app.py` (only `save_person` and `rename_speaker`), `dzomdu/llm/summarize.py`, `web/src/lib/api.ts`, `web/src/lib/format.ts`, and tests (`tests/test_speakers.py`, `tests/test_notes.py`, `tests/test_llm.py`, `tests/test_server.py`, `web/tests/format.test.mjs` new).
**Out of scope**: propagating a speaker rename into existing meeting records/notes (deliberately deferred — see Maintenance notes), changing how names are sanitised, the transcript editor, any UI layout.

## Git workflow
Branch `advisor/006-small-correctness-fixes`; **one commit per step**; short imperative messages. Do not push.

## Steps

### Step 1: Let people fields be cleared
In `ensure_person` change the gate to `if role is not None or organisation is not None or bio is not None:`. In `update_person` use `if role is not None: meta["role"] = role` (same for organisation), and for `bio is not None`: if empty after `.strip()`, replace the Bio section body with the stub placeholder text used by `PERSON_STUB` (look it up in `vault.py`) instead of leaving the old text; otherwise current behaviour.
Tests (`tests/test_notes.py` or the existing people tests — find with `grep -rn "ensure_person" tests/`): set role "Chair" → clear with `""` → `person_profile(name)["role"] == ""`; passing `None` leaves it unchanged; clearing bio removes the old text.
**Verify**: `pytest -q tests/test_notes.py tests/test_server.py` → pass.

### Step 2: Reject blank speaker names and report vault conflicts
In `SpeakerStore.rename` raise `ValueError("A name is required")` when `new.strip()` is empty (before any DB write). In `Vault.rename_person` return a bool (`True` when renamed); in `rename_speaker` (route) if the store rename succeeded but the person file could not be moved because the destination exists, still succeed but include `{"name": ..., "note": "A people note called <new> already exists; the old note was left in place."}`-style info only if that is a trivial dict addition — otherwise leave the response as is and just add the vault check. Do not change the 404/409 mapping.
Tests: `tests/test_speakers.py` — rename to `"   "` raises `ValueError`; route test in `tests/test_server.py` — blank → 409 and nothing renamed.
**Verify**: `pytest -q tests/test_speakers.py tests/test_server.py` → pass.

### Step 3: Readable validation errors in the web client
In `api.ts`, build the message from `detail`: if it is a string use it; if an array, join each item's `msg` (strip a leading `"Value error, "`) with `"; "`; else fall back to `` `${res.status} ${res.statusText}` ``. Extract this into an exported pure function `errorMessage(data, res)` so it can be unit-tested.
New `web/tests/api-error.test.mjs`: follow how `web/tests/transcript-edits.test.mjs` loads TypeScript (read its header; reuse the same loader approach). Cases: string detail, FastAPI 422 array, missing detail.
**Verify**: `cd web && npm test && npm run lint && npx tsc --noEmit` → exit 0.

### Step 4: Parse date-only strings as local dates
In `format.ts` add `parseDate(iso)`: if `/^\d{4}-\d{2}-\d{2}$/` return `new Date(y, m - 1, d)` (local), else `new Date(iso)`. Use it in `shortDate`, `longDate` and `relative`. Test `web/tests/format.test.mjs`: with `process.env.TZ = "America/Los_Angeles"` set before any Date use (node --test runs files in separate processes), `shortDate("2026-10-14")` contains "14"; a full ISO timestamp still formats as before.
**Verify**: `cd web && TZ=America/Los_Angeles npm test` and `cd web && TZ=Asia/Thimphu npm test` → both pass.

### Step 5: Script-aware token estimate
In `summarize.py` replace `estimate_tokens` with: count characters; if more than 30% are non-ASCII letters (`ord(c) > 0x2FF` is a fine proxy for Devanagari/Tibetan/CJK) use `len(text) // 2 + 1` (conservative), else keep `len(text) // 4 + 1`. Keep the function name and signature.
Tests in `tests/test_llm.py`: 4000 ASCII chars ≈ 1001 tokens (unchanged); 4000 Devanagari chars ≥ 2000 estimated; `chunk_lines` splits a long Nepali transcript into more chunks than the same character count of English.
**Verify**: `pytest -q tests/test_llm.py tests/test_notes.py` → pass.

## Test plan
Per step above. Run the full `pytest -q`, `ruff check .`, and the web checks at the end.

## Done criteria
- [ ] `pytest -q`, `ruff check .`, and `cd web && npm run lint && npx tsc --noEmit && npm test` all exit 0
- [ ] `grep -n "if role:" dzomdu/vault.py` returns nothing
- [ ] New tests exist: people-clear, blank-rename, api error message, local date parse, non-ASCII token estimate
- [ ] Only in-scope files modified; `plans/README.md` updated

## STOP conditions
- A caller you didn't expect passes `""` to `ensure_person` meaning "leave unchanged" (grep before changing the gate).
- `PERSON_STUB` has no recognisable Bio placeholder to restore.
- The web test loader can't import TypeScript modules the way `transcript-edits.test.mjs` does and a workaround isn't obvious.

## Maintenance notes
- Deferred on purpose: after a voice rename, existing meeting records and notes still carry the old name, and `/api/speakers` matches meetings by name, so the renamed person shows 0 meetings. Fixing it needs either a stable `speaker_id` link in records or a rename propagation pass over records and notes — a separate design decision; do not bolt it onto this plan.
- Names are sanitised inconsistently across entry points (`clean_name` in `transcript.py` vs raw names in `apply_review`/people routes); worth a dedicated plan if wikilinks with `[`, `]`, `|`, `/` characters become a problem.
