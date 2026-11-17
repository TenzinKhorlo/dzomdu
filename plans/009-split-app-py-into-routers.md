# Plan 009: Split `dzomdu/server/app.py` into per-area routers behind an unchanged API

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- dzomdu/server/ tests/test_server.py`
> THIS PLAN MUST RUN LAST among the plans that touch `dzomdu/server/app.py` (001, 002, 003, 004, 005, 006). When it was written the working tree already had uncommitted edits to `app.py`; line numbers below are approximate. Re-derive the route list yourself in Step 1 and treat the generated snapshot — not the table in this plan — as the source of truth.

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: MED (pure refactor, but one 1,300-line closure with shared state)
- **Depends on**: plans/001, plans/002, plans/003, plans/005 merged (they edit `app.py`); 004 and 006 preferably merged
- **Category**: tech-debt
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

`create_app` in `dzomdu/server/app.py` is one ~1,100-line function containing ~55 route handlers as nested closures over `cfg`, `pipeline`, `manager`, `chats`, `project_manager`, `project_lock`, `task_manager`, `model_library` and an `answering` set. Business rules (model hot-swapping that assigns `pipeline._asr = pipeline._diarizer = None`, config mutation, template file writes, speaker-limit rules) live inside route bodies, so they can only be tested through `TestClient`, and any change means navigating one file with shared closure state. Splitting it into `APIRouter` modules that receive an explicit context object makes each area readable and independently testable, with zero change to URLs, payloads or status codes.

## Current state

- `dzomdu/server/app.py` top-level: helpers `_audio_type`, `web_dir`, ~18 pydantic body models (`ReviewBody`, `RegenerateBody`, `TaskBody`, `TaskUpdate`, `PersonBody`, `LLMSettings`, `SettingsBody`, `ModelSettingsBody`, `ModelDownloadBody`, `NoiseSettingsBody`, `SectionBody`, `TemplateBody`, `ProjectBody`, `MeetingTitleBody`, `ProjectMembersBody`, `DeleteProjectBody`, `RenameBody`) and `create_app(cfg, pipeline=None, config_path=None)`.
- Inside `create_app`: construction of `Pipeline`, `SessionManager`, `ChatStore`, `ProjectManager`, `TaskManager`, `ModelLibrary`; the FastAPI app with a `lifespan` that shuts managers down; CORS middleware (and, after plan 001, Host/Origin + headers middleware); then route groups in this order (approximate line starts at planning time):
  | Group | Routes | Starts |
  |---|---|---|
  | shell | `/classic/`, `/`, `/api/info`, static mount | ~247 |
  | settings & models | `/api/settings*`, `/api/models*`, `/api/settings/llm/test` | ~334 |
  | templates | `/api/templates*` | ~534 |
  | sessions | `/api/sessions*`, `/api/upload`, `/api/warmup`, audio WebSocket | ~595 |
  | meetings & dashboard & tasks | `/api/meetings*`, `/api/dashboard`, `/api/tasks*` | ~722 |
  | projects | `/api/projects*` | ~931 |
  | speakers & people | `/api/speakers*`, `/api/people` | ~1095 |
  | chats | `/api/chats*` incl. streaming | ~1153 |
  Shared helpers defined as closures near the top of `create_app` (e.g. `session_or_404`, `record_or_404`, `meeting_meta`, `project_idle`, `candidate_llm`, `close_audio_socket`, `chat_or_404`) are used across groups — find every use with grep before moving any of them.
- Tests: `tests/test_server.py` (≈719 lines) drives the whole API through `TestClient(create_app(cfg, pipeline))`; other test files also call `create_app`. They must pass unchanged — they are the safety net. `app.state.manager` and `app.state.model_library` are read elsewhere (check with `grep -rn "app.state" dzomdu tests`).
- Convention: type hints throughout, `HTTPException` for errors, `@meeting_locked` (from `dzomdu/persistence.py`) on mutating meeting/task routes — decorator order matters (route decorator outermost, as today).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| All tests | `pytest -q` | all pass (same count as before, plus the new snapshot test) |
| Lint | `ruff check .` | exit 0 |
| Route snapshot | `pytest -q tests/test_server_routes.py` | pass |
| Web build smoke | `cd web && npm run build && cd .. && python -c "from dzomdu.config import Config; from dzomdu.server.app import create_app; print(len(create_app(Config(vault='/tmp/dz-v', data_dir='/tmp/dz-d')).routes))"` | prints a number equal to the pre-refactor count — adjust the `Config(...)` call to the real constructor (see `tests/conftest.py`) |

## Scope

**In scope**: `dzomdu/server/app.py`, new files under `dzomdu/server/` (`context.py`, `routers/__init__.py`, `routers/<area>.py`, optional `schemas.py`), `tests/test_server_routes.py` (new).
**Out of scope**: any behaviour, URL, payload, status-code or message change; response models/OpenAPI typing (separate plan if wanted); `sessions.py` internals; `Pipeline` private attributes (move the code that touches `_asr`/`_diarizer`/`_llm` verbatim into a router or service function — do not "clean it up" here); renaming symbols imported by tests (keep `create_app` importable from `dzomdu.server.app`).

## Git workflow
Branch `advisor/009-split-app-routers`; **one commit per extracted router**, each leaving `pytest -q` green. Match the repo's short imperative commit style. Do not push.

## Steps

### Step 1: Freeze the API surface with a snapshot test
Create `tests/test_server_routes.py` that builds the app like `tests/test_server.py` does, collects `sorted((method, path) for route in app.routes for method in (route.methods or {"WEBSOCKET"}))` (include the WebSocket route and the static mount's name), and compares it with a literal list committed in the test. Generate that literal from the **current** app first, review it by eye against the table above, then commit.
**Verify**: `pytest -q tests/test_server_routes.py` → passes on the unmodified code.

### Step 2: Introduce the shared context
Create `dzomdu/server/context.py` with a `@dataclass class AppContext` holding exactly the closure state: `cfg`, `pipeline`, `manager`, `chats`, `answering`, `project_manager`, `project_lock`, `task_manager`, `model_library`, `config_path`, plus `web: Path | None`. Build it in `create_app` right after the managers are constructed. Move the cross-group helper closures into `dzomdu/server/context.py` as methods or plain functions taking the context (`ctx.session_or_404(sid)`, `ctx.record_or_404(id)`, …) one helper at a time, replacing call sites in `app.py` as you go.
**Verify**: `pytest -q` → all pass.

### Step 3: Extract routers one at a time, least coupled first
Order: **chats → speakers/people → projects → templates → settings/models → tasks/meetings/dashboard → sessions (incl. WebSocket) → shell**. For each: create `dzomdu/server/routers/<area>.py` exposing `def router(ctx: AppContext) -> APIRouter`, move the handlers verbatim (same decorators, same bodies, same status codes, same `@meeting_locked` placement), move their pydantic models next to them (or into `schemas.py` if another router also uses them), and in `create_app` call `app.include_router(<area>.router(ctx))` **in the same position the routes had originally** (route order can matter for overlapping paths such as `/api/projects/{name}` vs `/api/projects/{name}/overview`). Commit after each router.
**Verify (after every router)**: `pytest -q` → all pass and `pytest -q tests/test_server_routes.py` → unchanged snapshot.

### Step 4: Leave `app.py` as a thin factory
When all routers are out, `create_app` should contain only: manager construction, middleware, lifespan, `include_router` calls, static mount. Keep the public names `create_app`, `web_dir` importable from `dzomdu.server.app` (the CLI and tests import them; check with `grep -rn "server.app import" dzomdu tests`).
**Verify**: `wc -l dzomdu/server/app.py` → under ~200 lines; `pytest -q` and `ruff check .` pass; the web build smoke command in the table prints the same route count as before the refactor.

### Step 5: Manual smoke
Run `cd web && npm run build && cd .. && dzomdu ui --no-open`, open http://localhost:8765 and click through Overview, Meetings (open one), Projects (open one), People, Chat (ask a question if an LLM is configured), Settings (each tab), and start/cancel a recording. No console errors, no 404/500 in the server log.

## Test plan
The refactor is validated by the existing `tests/test_server.py` suite (unchanged) plus the route snapshot added in Step 1. Do not edit existing tests to make them pass; if one fails, the extraction changed behaviour — fix the extraction.

## Done criteria
- [ ] `pytest -q` exits 0 with the same number of tests as before plus the snapshot test; `ruff check .` exits 0
- [ ] `wc -l dzomdu/server/app.py` < 250
- [ ] `grep -c "@app\.\(get\|post\|put\|patch\|delete\|websocket\)" dzomdu/server/app.py` is at most 4 (only the shell routes may remain in `app.py`)
- [ ] `git diff --stat b28d80c..HEAD -- tests/test_server.py` shows no modifications to existing tests (only additions)
- [ ] Manual smoke in Step 5 done and noted in the PR description
- [ ] Only in-scope files modified; `plans/README.md` updated

## STOP conditions
- A helper is used by two routers in a way that forces a circular import you can't resolve with the context object.
- A test needs editing to pass.
- The route snapshot changes for any reason other than ordering you can justify (a path or method appears/disappears).
- Plans 001/002/003/005 are not merged yet (their edits to `app.py` will conflict).
- You find handler logic that mutates `Pipeline` private attributes in several places and moving it would require changing `Pipeline`'s interface — stop and report; that is a follow-up design task (public `Pipeline.reset_models()` / `SessionManager.is_warming()`), not part of this plan.

## Maintenance notes
- New routes go into the matching router; new shared state goes on `AppContext`, not into module globals.
- Follow-ups this unlocks (not in scope): response models + generated TypeScript types; moving settings/model-swap logic into a service object with public methods; a single exception handler mapping `*Conflict` errors to 409.
- Reviewer focus: route ordering within `include_router` calls, decorator order of `@meeting_locked`, and that WebSocket handling and the `lifespan` shutdown still run (`manager.shutdown()`, `model_library.shutdown()`).
