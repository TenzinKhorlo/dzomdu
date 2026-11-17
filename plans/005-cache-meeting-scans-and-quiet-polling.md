# Plan 005: Stop re-parsing the whole vault on every request, and stop polling hidden tabs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- dzomdu/dashboard.py dzomdu/tasks.py dzomdu/server/app.py web/src/hooks/use-api.ts tests/test_dashboard.py tests/test_tasks.py tests/test_server.py`
> (`dzomdu/server/app.py` had uncommitted edits when this plan was written; anchor on quoted code.) A mismatch is a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (cache invalidation; shared mutable records)
- **Depends on**: none. Plan 003 also edits `pipeline.save_record` area; do not run 003 and 005 in parallel branches without rebasing.
- **Category**: perf
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

Every list endpoint re-reads and JSON-parses every `meetings/*.json` (each embeds the full transcript, ~150–300 KB for a 3-hour meeting) and several also re-read each Markdown note. `/api/dashboard` does this twice, `TaskManager.save` scans the whole folder to find one file, and the web app polls these endpoints from every page (dashboard 15 s, meetings 10 s, projects 30 s, tasks 60 s) — including in background tabs, and re-renders even when nothing changed. At a few hundred meetings the backend spends most of its time re-parsing, holding a global lock that also blocks task ticks and the pipeline's final note write. After this plan a repeated request re-parses only files that changed, and hidden tabs stop polling.

## Current state

- `dzomdu/dashboard.py:85`:
  ```python
  def load_records(meetings_dir: Path) -> list[dict[str, Any]]:
      records = []
      if not meetings_dir.is_dir():
          return records
      for path in meetings_dir.glob("*.json"):
          try:
              records.append(json.loads(path.read_text(encoding="utf-8")))
          except (OSError, json.JSONDecodeError):
              continue
      records.sort(key=lambda r: r.get("date") or "", reverse=True)
      return records
  ```
  Callers (`grep -rn load_records dzomdu`): `tasks.py` (`list`, `update`), `chat.py:390`, `server/app.py` (`/api/meetings`, `/api/dashboard`, `/api/projects`, `/api/speakers`, a chat-sources check).
- `dzomdu/server/app.py`:
  ```python
  @app.get("/api/dashboard")
  @meeting_locked
  def dashboard_data(days: int = 30) -> dict[str, Any]:
      task_manager.list()                                   # result discarded; called for its side effect
      records = dashboard.load_records(cfg.meetings_dir)    # parsed again
      data = dashboard.build_dashboard(records, len(pipeline.store.list()), days=days)
  ```
- `dzomdu/tasks.py`: `sync(record)` calls `dashboard.sync_task_state(record)` (mutates, returns True if changed) then `save`; `save` globs and parses every JSON file until `data["id"] == record["id"]` (comment: "Only paths discovered under meetings_dir are used, never an id from a request or an arbitrary record field as a filesystem path"); `list()` and `update()` are `@meeting_locked` and call `load_records` + `sync` per record.
- `dzomdu/persistence.py`: one process-wide `RLock` `MEETING_LOCK`, decorator `meeting_locked`. Writes everywhere use `vault.atomic_write_text` (tmp file + replace), so readers never see half-written files.
- `web/src/hooks/use-api.ts` (full file): `setInterval(load, interval)` with no visibility or in-flight guard; every response calls `setData(d)` with a new object.
- Conventions: tests in `tests/test_dashboard.py`, `tests/test_tasks.py`, `tests/test_server.py` build vaults with the fake pipeline from `tests/conftest.py`. Match their fixtures.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Python tests | `pytest -q` | all pass |
| Targeted | `pytest -q tests/test_dashboard.py tests/test_tasks.py tests/test_server.py tests/test_chat.py` | pass |
| Lint | `ruff check .` | exit 0 |
| Web | `cd web && npm run lint && npx tsc --noEmit && npm test && npm run build` | exit 0 |

## Scope

**In scope**: `dzomdu/dashboard.py`, `dzomdu/tasks.py`, `dzomdu/server/app.py` (only `/api/dashboard` and, if needed, `/api/projects`), `web/src/hooks/use-api.ts`, tests (`tests/test_dashboard.py`, `tests/test_tasks.py`, `tests/test_server.py`, `web/tests/` for the hook logic if extractable).
**Out of scope**: chat retrieval (`chat.py`) caching, pagination, changing response shapes, removing `@meeting_locked`, moving to SQLite, virtualized tables, transcript rendering performance.

## Git workflow
Branch `advisor/005-cache-meeting-scans`; one commit per step; short imperative messages. Do not push.

## Steps

### Step 1: Add a guard test that counts file reads
In `tests/test_dashboard.py` add a test that creates 20 meeting records (use the existing helper/fixture pattern), wraps `pathlib.Path.read_text` with a counter via `monkeypatch`, calls the `/api/dashboard` route twice through `TestClient`, and asserts the **second** call reads at most 20 note files and parses 0 meeting JSONs (count calls whose path ends in `.json` under `meetings/`). It must FAIL on the current code.
**Verify**: `pytest -q tests/test_dashboard.py -k reads` → the new test fails (expected before the change; keep it marked as the target).

### Step 2: mtime-keyed cache in `load_records`
Implement a module-level cache in `dashboard.py`: `_CACHE: dict[Path, tuple[int, int, dict]]` keyed by path, value `(st_mtime_ns, st_size, record)`, guarded by a `threading.Lock`. `load_records` globs, `stat()`s each file, re-parses only when `(mtime_ns, size)` differs, drops cache entries for files that vanished, then sorts as before. Also expose `record_paths(meetings_dir) -> dict[str, Path]` (id → discovered path) built in the same pass, and `invalidate(path)`.
Records returned are the **shared cached objects**: document at the top of `load_records` that callers must treat them as read-only except `TaskManager`, which re-saves. In `TaskManager.sync`, if `save` raises, call `dashboard.invalidate(path)` so a failed write can't leave the cache ahead of disk.
**Verify**: `pytest -q tests/test_dashboard.py tests/test_tasks.py tests/test_server.py tests/test_chat.py tests/test_projects.py` → all pass (the new Step 1 test still fails until Step 3/4).

### Step 3: Remove the double scan in `/api/dashboard`
Replace `task_manager.list()` + `load_records(...)` with a single `records = dashboard.load_records(cfg.meetings_dir)` followed by `for r in records: task_manager.sync(r)` (that is the only side effect `list()` was providing — confirm by reading `TaskManager.list`), then `build_dashboard(records, ...)`. If `/api/projects` runs the full `build_dashboard` only to count meetings per project, leave it but make sure it shares the cached `load_records` (no new code needed).
**Verify**: `pytest -q tests/test_dashboard.py` → the Step 1 read-count test now passes.

### Step 4: O(1) `TaskManager.save`
Change `save(record)` to look the path up in `dashboard.record_paths(self.cfg.meetings_dir)[record["id"]]` (discovered paths only, preserving the original safety comment) and fall back to raising `FileNotFoundError("The meeting was deleted")` when absent; after writing, call `dashboard.invalidate(path)`. Keep `atomic_write_text`.
Test in `tests/test_tasks.py`: saving a record counts exactly one `read_text` of a meetings JSON (the id lookup uses the cached map), and a record with an id that has no file still raises `FileNotFoundError`.
**Verify**: `pytest -q tests/test_tasks.py tests/test_dashboard.py` → pass.

### Step 5: Quiet polling in `useApi`
In `web/src/hooks/use-api.ts`: (a) skip a tick when `document.visibilityState === "hidden"` and run an immediate refresh on `visibilitychange` back to visible; (b) skip a tick while a previous request is still in flight (a `useRef<boolean>`); (c) keep the previous `data` object when the new response is JSON-equal (compare `JSON.stringify` of the new payload with a ref holding the last string) so unchanged polls cause no re-render. Keep the exported shape `{ data, error, loading, reload }` identical.
**Verify**: `cd web && npm run lint && npx tsc --noEmit && npm test && npm run build` → exit 0. Manual: open the Overview, switch to another tab for 30 s, then watch the server log/network: no `/api/dashboard` requests while hidden; returning triggers one.

## Test plan
Step 1/3 read-count test (acceptance for the cache); Step 4 save test; existing dashboard/tasks/server/chat/projects tests must stay green unchanged. Add one cache-invalidation test in `tests/test_dashboard.py`: modify a record file (rewrite with new title and a different `mtime_ns`, e.g. `os.utime`) → the next `load_records` returns the new title; delete a file → it disappears from the result.

## Done criteria
- [ ] `pytest -q` exits 0; the read-count, invalidation and save tests exist and pass
- [ ] `grep -n "task_manager.list()" dzomdu/server/app.py` no longer matches inside `dashboard_data`
- [ ] `grep -n "glob(\"\*.json\")" dzomdu/tasks.py` returns nothing
- [ ] `cd web && npm run lint && npx tsc --noEmit && npm test && npm run build` exit 0
- [ ] Only in-scope files modified; `plans/README.md` updated

## STOP conditions
- Any existing test fails because a caller mutates a cached record and the fix isn't local to `TaskManager` (report which caller).
- `sync_task_state` or `meeting_tasks` turn out to depend on state outside the record JSON and note file in a way that makes caching by the JSON's mtime unsafe (e.g. they read the note — then the note's change must also invalidate; if that can't be done simply, stop).
- The read-count test can't be made to fail before the change.

## Maintenance notes
- Notes edited in Obsidian are read via `_source_tasks` on each request; the cache only covers the JSON records. If the note reads become the bottleneck, key a second cache on the note's mtime.
- `@meeting_locked` still wraps list/dashboard routes; with cheap reads this is acceptable, and removing it is a separate, riskier change.
- Reviewer focus: shared-object mutation (only `TaskManager` may mutate cached records), and cache growth (bounded by number of meetings).
