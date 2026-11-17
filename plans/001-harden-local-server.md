# Plan 001: Harden the local API server (template sandbox, Host/Origin checks, key reuse, note images)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- dzomdu/notes/render.py dzomdu/server/app.py dzomdu/server/markdown.py tests/test_server.py tests/test_notes.py`
> NOTE: when this plan was written the working tree already had *uncommitted* edits to
> `dzomdu/server/app.py` (and `cli.py`, `model_library.py`, `diarize/__init__.py`, `pyproject.toml`).
> Line numbers below refer to that working tree; anchor on the quoted code, not the numbers. If a
> quoted excerpt is missing or different, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (Host/Origin allow-list must not lock users out)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

Dzomdu is a local server (default `127.0.0.1:8765`) with no login that holds meeting audio, transcripts and
voiceprints, and exposes destructive routes (delete meetings/projects, change the vault path, upload audio,
write minutes templates). Four gaps combine badly:
1. Minutes templates are rendered by an **unsandboxed** Jinja2 environment and can be written over the API, so
   a planted template can run arbitrary Python at the next meeting.
2. There is **no Host/Origin validation**, so a web page the user visits can use DNS rebinding or cross-site
   requests to reach the API (and chain into #1).
3. `POST /api/settings/llm/test` reuses the **saved LLM API key** for a request-supplied URL.
4. The note renderer allows **remote images**, so prompt-injected transcript text can make the browser fetch
   `https://attacker/...<meeting text>`. (The chat renderer already disables images.)

After this plan: templates cannot execute code, only expected Hosts/Origins are served, the stored key is never sent to a
different URL, and notes cannot load remote images.

## Current state

- `dzomdu/notes/render.py:58` — the unsandboxed environment, used at lines ~193 and ~251:
  ```python
  def _env() -> jinja2.Environment:
      return jinja2.Environment(
          autoescape=False,
          trim_blocks=True,
          lstrip_blocks=True,
          keep_trailing_newline=True,
          undefined=jinja2.StrictUndefined,
      )
  ```
- `dzomdu/notes/templates.py` has `check_template_body(body, specs)` (used by the API to validate a layout before saving) — read it and
  confirm it renders through `_env()`/`render.py`. Template variables are documented in the module docstring (`notes`, `meeting`,
  `role()`, `cite()`, `person()`, `task()`), all simple data and callables.
- `dzomdu/server/app.py` (inside `create_app`):
  ```python
  app = FastAPI(title="Dzomdu", lifespan=lifespan, docs_url=None, redoc_url=None)
  ...
  # `next dev` runs the dashboard on :3000 during development and calls this API directly
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
  No `TrustedHostMiddleware`, no Origin check. The audio WebSocket is `@app.websocket("/api/sessions/{sid}/audio")` (search `async def audio`).
- `app.py` `candidate_llm`: `key = "" if body.clear_api_key else (body.api_key or cfg.llm.api_key)` while `base_url` comes from the body;
  `test_llm` calls `LLMClient(candidate_llm(body)).ping`. `PUT /api/settings` (`save_settings`) also uses `candidate_llm`-style merging — check it.
- `dzomdu/server/markdown.py`:
  ```python
  _md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
  _chat_md = (
      MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").disable("image")
  )
  ```
  `note_to_html` uses `_md`. Notes are injected with `dangerouslySetInnerHTML` in `web/src/app/meetings/view/page.tsx` and
  `dzomdu/server/static/app.js`.
- `dzomdu/cli.py` `ui` command takes `--host` (default `127.0.0.1`) and `--port`; Docker runs it with `--host 0.0.0.0` (see `Dockerfile` CMD).
  `docker-compose.yml` publishes only `127.0.0.1:${DZOMDU_PORT}:8765`.
- Conventions: tests use `fastapi.testclient.TestClient` with fake backends from `tests/conftest.py`; see `tests/test_server.py` for the fixture
  pattern (a `client` built from `create_app(cfg, pipeline)`). Match it. Errors are raised as `HTTPException`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Python tests | `pytest -q` (venv with `pip install -e '.[...]'` + dev deps active) | all pass (some skip) |
| Targeted | `pytest -q tests/test_server.py tests/test_notes.py` | pass |
| Lint | `ruff check .` | exit 0 |
| Web checks (only if you touch web/) | `cd web && npm run lint && npx tsc --noEmit && npm test` | exit 0 |

## Scope

**In scope**:
- `dzomdu/notes/render.py`, `dzomdu/notes/templates.py` (only if needed for the sandbox)
- `dzomdu/server/app.py`
- `dzomdu/server/markdown.py`
- new `dzomdu/server/security.py` (Host/Origin helpers + headers middleware)
- `dzomdu/cli.py` (only to pass the bound host/port so the allow-list can include them)
- tests: `tests/test_server.py`, `tests/test_notes.py`, new `tests/test_security.py`

**Out of scope**: authentication/login, token modes, the classic UI JS, Dockerfile/compose (Plan 002), any route behaviour changes.

## Git workflow

- Branch `advisor/001-harden-local-server`. One commit per step; match the repo's short imperative style
  (see `git log --oneline`, e.g. "Write meeting records and notes atomically"). Do not push.

## Steps

### Step 1: Sandbox the template environment
In `render.py` replace `jinja2.Environment` with `jinja2.sandbox.ImmutableSandboxedEnvironment`, keeping all four options and `StrictUndefined`.
Add a test in `tests/test_notes.py` that `check_template_body` (or rendering) **rejects** bodies such as
`{{ ''.__class__.__mro__[1].__subclasses__() }}` and `{{ notes.__class__ }}` with a `jinja2.exceptions.SecurityError`
(a subclass of `TemplateError`, which `validated_template` already turns into HTTP 400), and a test that every built-in template under
`dzomdu/notes/templates/*.md` still renders with the existing fixtures.
**Verify**: `pytest -q tests/test_notes.py tests/test_pipeline.py` → all pass, new tests included.
(If a built-in template breaks under the sandbox, STOP — see STOP conditions.)

### Step 2: Add Host and Origin validation
Create `dzomdu/server/security.py` with:
- `allowed_hosts(host: str, port: int) -> set[str]`: always `localhost`, `127.0.0.1`, `[::1]`, `testserver` (Starlette TestClient), plus the
  host the server was told to bind to when it is not `0.0.0.0`/`::`, each with and without `:port`; plus extra names from env `DZOMDU_ALLOWED_HOSTS` (comma list).
  When bound to `0.0.0.0` (Docker) accept any Host that is an IP literal or in the env list, since the Docker user reaches it via a mapped loopback port.
- an ASGI/Starlette middleware (use `BaseHTTPMiddleware` or pure ASGI so it also covers WebSocket scopes) that: rejects requests whose `Host` is not allowed with 400;
  for state-changing methods (POST/PUT/PATCH/DELETE) and WebSocket upgrades rejects a present `Origin` header that is not same-origin (scheme+host match the allowed
  hosts) or one of the existing dev origins `http://localhost:3000` / `http://127.0.0.1:3000`; requests with no Origin (curl, CLI) are allowed.
Wire it in `create_app` after the CORS middleware, passing host/port via new optional parameters `create_app(cfg, pipeline=None, config_path=None, *, host="127.0.0.1", port=8765)`;
in `cli.py ui` pass `host=host, port=port`. Keep the default so existing tests calling `create_app(cfg, pipeline)` still work.
**Verify**: `pytest -q tests/test_server.py` → all pass (TestClient sends `Host: testserver`).

### Step 3: Tests for Host/Origin
New `tests/test_security.py`: a request with `Host: evil.example` → 400; `POST /api/projects` with `Origin: https://evil.example` → 403;
same with `Origin: http://localhost:3000` → allowed (not 403); a WebSocket connect to `/api/sessions/x/audio` with a bad Origin is refused;
no Origin → allowed; `DZOMDU_ALLOWED_HOSTS=dzomdu.lan` is honoured (monkeypatch env, rebuild the app).
**Verify**: `pytest -q tests/test_security.py` → all pass.

### Step 4: Stop reusing the saved key for another URL (test endpoint only)
Revised after the first execution attempt: `save_settings` deliberately keeps the saved key when the user edits the URL and leaves the key field blank (the UI shows "Saved. Leave blank to keep it", and `tests/test_server.py::test_settings_change_llm_and_vault` asserts it). Do NOT change `save_settings` or the web UI in this plan.
Change only what `POST /api/settings/llm/test` sends: in `candidate_llm` (or in `test_llm` if `candidate_llm` is shared with `save_settings` — read both; do not alter the saved-config behaviour), fall back to `cfg.llm.api_key` only when the candidate `base_url` (stripped, trailing `/` removed) equals `cfg.llm.base_url` normalised the same way; otherwise use `body.api_key or ""`. Implement it so `save_settings` behaviour is byte-for-byte unchanged (for example a parameter `reuse_saved_key_only_for_same_url: bool` that only `test_llm` sets).
Test: save settings with a key for URL A; call `/api/settings/llm/test` with URL B and no key → the outgoing request (mock `LLMClient.ping` / httpx transport) carries no `Authorization` header; with URL A and no key it does. The existing `test_settings_change_llm_and_vault` must pass unchanged.
**Verify**: `pytest -q tests/test_server.py tests/test_llm.py` → pass, with no existing test edited.

### Step 5: No remote images in notes, plus response headers
- `markdown.py`: `_md = MarkdownIt(...).enable("table").disable("image")`. Add a test in `tests/test_server.py` or a new `tests/test_markdown.py`:
  `note_to_html("![x](https://evil.example/a.png)")` contains no `<img`.
- In `security.py` add a headers middleware setting `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; worker-src 'self' blob:; frame-ancestors 'none'`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. The Next static export uses inline scripts/styles, so `'unsafe-inline'` is required for now; do not use nonces.
  Do NOT apply CSP when `Origin`/dev mode on :3000 is in use (the middleware only touches this server's own responses).
**Verify**: `pytest -q` → pass; then manual: `cd web && npm run build && cd .. && dzomdu ui --no-open`, open http://localhost:8765, load a meeting, play audio, start a recording
(browser console shows no CSP violations). If any violation appears, loosen only that directive and note it in the PR.

## Test plan
New tests are listed per step. Model them on `tests/test_server.py` fixtures and `tests/test_notes.py`. Final: `pytest -q` and `ruff check .` clean.

## Done criteria
- [ ] `pytest -q` exits 0 with the new tests in `tests/test_security.py`, `tests/test_notes.py`, `tests/test_server.py`
- [ ] `ruff check .` exits 0
- [ ] `grep -n "jinja2.Environment(" dzomdu/notes/render.py` returns nothing
- [ ] `grep -n "disable(\"image\")" dzomdu/server/markdown.py` matches both renderers
- [ ] `grep -rn "TrustedHost\|allowed_hosts" dzomdu/server` shows the new middleware wired in `create_app`
- [ ] Only in-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions
- A built-in template fails under the sandbox and the fix would change its rendered output.
- The allow-list breaks `dzomdu ui --host 0.0.0.0` use in Docker (`docker compose up`, then open `http://127.0.0.1:8765`) and you can't fix it by the `0.0.0.0` rule above.
- The web UI (next dev on :3000 or the built export) fails after the Origin middleware and the fix needs web/ edits.
- Step 4 cannot be done without changing `save_settings` or an existing test's intent.

## Maintenance notes
- New state-changing routes are automatically covered by the Origin middleware; new hosts (reverse proxies) must be added through `DZOMDU_ALLOWED_HOSTS`. Document this in README/DOCKER.md (not planned; listed in plans/README.md under "Not planned").
- Known remaining exposure (follow-up, needs a UI change): saving settings with a new URL and a blank key still sends the previously saved key to the new URL on later LLM calls. Fix with a UI that makes the key field explicit when the URL changes, then apply the same-URL rule to `save_settings`.
- This is not authentication. If an org/server mode is built (PLAN.md Phase 5), add a real login before binding non-loopback.
- Reviewers should scrutinize: the CSP in a real browser, and that WebSocket Origin handling doesn't reject the Next dev server.

## Execution outcome (2026-11-12)

Implemented and reviewed on branch `advisor/001-harden-local-server`. Deviations accepted by the reviewer: Host is matched by hostname ignoring the port (Docker/proxies remap it); Origin is accepted when its netloc equals the request Host or is a :3000 dev origin; bad WebSocket Host/Origin close with 1008; a **missing** Host header is allowed (browsers always send one; needed by in-process ASGI tests). Step 4 was narrowed to `/api/settings/llm/test` only.

Follow-ups (not done):
- `testserver` is in the default allowed Host set so Starlette's TestClient works; it should be enabled only under tests (e.g. via `DZOMDU_ALLOWED_HOSTS` in `tests/conftest.py`), because a hostile local network could resolve that name.
- There is no test for the missing-Host case.
- Saving settings with a new URL and a blank key still keeps the old key (needs the Settings UI change described under Maintenance notes).
- Not exercised in a real browser: the Record page's microphone/AudioWorklet flow under the CSP, and `next dev` on :3000 with the Origin guard.
