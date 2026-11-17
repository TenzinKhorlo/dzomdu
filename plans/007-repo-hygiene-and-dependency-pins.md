# Plan 007: Repo hygiene — untrack video binaries, fix ignore files, pin fast-moving dependencies, align torch between uv.lock and Docker

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat b28d80c..HEAD -- .gitignore .dockerignore pyproject.toml uv.lock docker/constraints.txt web/package.json web/package-lock.json`
> (`pyproject.toml`, `uv.lock`, `web/package.json` and `web/package-lock.json` had uncommitted edits when this plan was written — they belong to an in-progress UI migration; do not revert or reformat them.) A mismatch with the excerpts below is a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED (Step 4 changes resolved dependency versions; Step 1 touches git index)
- **Depends on**: none
- **Category**: tech-debt / dependencies
- **Planned at**: commit `b28d80c` (+ uncommitted working tree), 2026-11-12

## Why this matters

1. `videos/` has 47 tracked files (14 are large binaries: `.mp4`, `.ecproj` project files) totalling ~185 MB; the repository pack is ~322 MiB for an app of ~12k lines of Python. Every clone, CI checkout and Docker build context carries it (`.dockerignore` doesn't exclude it). `.gitignore` doesn't cover `videos/` or local agent/OS files (`.DS_Store`, `.claude/`, `.agents/`).
2. The new UI framework `@astryxdesign/*` is pre-1.0 and on caret ranges (`^0.7.11` = any `0.7.x`), so a patch release can change a design-system component under the app without a commit. The Python extras `diarize` and `whisper` have only a floor while Docker caps them (`<5`, `<2`), so native installs and Docker disagree about supported versions.
3. `uv.lock` resolves `torch 2.14.1`, `torchaudio 2.11.0`, `torchcodec 0.17.0`; `docker/constraints.txt` pins `torch==2.10.0`, `torchaudio==2.10.0`, `torchcodec==0.10.0` ("Keep native PyTorch/TorchCodec ABIs paired"). Local/dev and Docker therefore run different torch stacks, and the lock's torch/torchaudio pair is itself mismatched.

## Current state

- `.gitignore` (whole file): Python/venv caches, `bench_out/`, audio extensions (`*.wav *.flac *.m4a *.mp3 *.opus *.sqlite`), `bench/data/`, `bench/manifest.yaml`, `.env`, `/vault/`. No `videos`, no `.DS_Store`.
- `.dockerignore` (whole file): `.git .github .venv .pytest_cache .ruff_cache __pycache__ *.pyc bench tests PLAN.md web/node_modules web/.next web/out web/tsconfig.tsbuildinfo vault *.wav *.flac *.m4a *.mp3 *.opus *.sqlite .env`.
- Tracked large files: `git ls-files videos | grep -E "\.(mp4|ecproj|filmcraft|scraft|wav|mov)$"` → 14 files (e.g. `videos/04-signal-to-substance/assets/delivery-15s.mp4` ≈ 33 MB, `videos/05-brand-aligned/assets/filmcraft-master.mp4` ≈ 32 MB). Small files (README.md, PNG/SVG/JPG previews) are fine to keep. Two mp4s under `videos/` show as deleted in the working tree (user's pending deletion) — leave them alone.
- `web/package.json` dependencies: `"@astryxdesign/core": "^0.7.11"`, `"@astryxdesign/theme-neutral": "^0.7.11"`, `"@stylexjs/stylex": "^0.19.1"`; devDependency `"@astryxdesign/cli": "^0.7.11"`. `next` and `react` are already exact-pinned. The generated theme lives in `web/src/themes/dzomdu/` (built by `npx astryx theme build src/themes/dzomdu/dzomduTheme.ts`) and is imported through `web/src/astryx-themes.ts`.
- `pyproject.toml` extras: `diarize = ["pyannote.audio>=4.0"]`, `whisper = ["faster-whisper>=1.1"]`; `[dependency-groups] dev = ["pytest>=8", "ruff>=0.6"]`; there is no `[tool.uv]` section.
- `docker/constraints.txt` (whole file):
  ```
  torch==2.10.0
  torchaudio==2.10.0
  torchcodec==0.10.0
  pyannote.audio>=4.0,<5
  faster-whisper>=1.2.1,<2
  ctranslate2>=4.5,<5
  ```
  The Dockerfile installs with `pip install -c docker/constraints.txt ".[${EXTRAS}]"` and does not use `uv.lock`. CI (`.github/workflows/docker.yml`) builds CPU and CUDA images and runs `docker/smoke.py`.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Python tests | `pytest -q` | all pass |
| Lock | `uv lock` | exit 0, only intended version changes |
| Web | `cd web && npm install && npm run lint && npx tsc --noEmit && npm test && npm run build` | exit 0 |
| Theme drift | `cd web && npx astryx theme build src/themes/dzomdu/dzomduTheme.ts && git status --short src/themes` | no unexpected changes |
| Docker smoke (Step 4 only) | `docker build -t dzomdu:test . && docker run --rm --entrypoint python dzomdu:test /app/docker/smoke.py` | exit 0 |

## Scope

**In scope**: `.gitignore`, `.dockerignore`, `pyproject.toml` (only the two extras and a new `[tool.uv]` constraint block), `uv.lock` (regenerated), `docker/constraints.txt` (only if Step 4 decides to change it), `web/package.json`, `web/package-lock.json`.
**Out of scope**: rewriting git history (`git filter-repo`/BFG) — it breaks existing clones and needs the owner's decision; deleting files from disk; moving media to Git LFS or releases (owner decision); Dockerfile logic; any source code.

## Git workflow
Branch `advisor/007-repo-hygiene`; one commit per step; short imperative messages. Do not push.

## Steps

### Step 1: Ignore binaries and local files; untrack the large video files
- `.gitignore`: add `.DS_Store`, `.claude/settings.local.json`, `.claude/worktrees/`, `.agents/`, and under a comment `# video masters and editor project files live outside git`: `videos/**/*.mp4`, `videos/**/*.mov`, `videos/**/*.ecproj`, `videos/**/*.filmcraft`, `videos/**/*.scraft`.
- `.dockerignore`: add `videos`, `.claude`, `.agents`, `.codex`, and `.DS_Store`.
- Untrack (keep on disk): `git ls-files videos | grep -E "\.(mp4|ecproj|filmcraft|scraft|wav|mov)$" | xargs git rm --cached --`. Do **not** pass `-f` and do **not** delete files from disk. Skip any path git reports as already deleted in the working tree (the user's pending deletions) — those stay as they are.
**Verify**: `git status --short | head` shows the files as staged deletions only (no file removed from disk: `ls videos/04-signal-to-substance/assets/` still lists the mp4s); `git check-ignore -v videos/02-dzomdu-promo-20s.mp4` prints the `.gitignore` rule; `git ls-files videos | grep -cE "\.mp4$"` → `0`.

### Step 2: Pin the Astryx packages exactly
In `web/package.json` set `@astryxdesign/core`, `@astryxdesign/theme-neutral`, `@astryxdesign/cli` to `"0.7.11"` and `@stylexjs/stylex` to `"0.19.1"` (the currently resolved versions — confirm with `npm ls @astryxdesign/core @stylexjs/stylex`). Run `cd web && npm install`.
**Verify**: `cd web && npm ls @astryxdesign/core` → `0.7.11`; `npm run lint && npx tsc --noEmit && npm test && npm run build` → exit 0; the theme drift command above leaves `src/themes/` unchanged.

### Step 3: Align Python extras with Docker's supported ranges
In `pyproject.toml`: `diarize = ["pyannote.audio>=4.0,<5"]` and `whisper = ["faster-whisper>=1.2.1,<2"]`. Add the same kind of upper bound for other fast-moving extras **only** if you can read the currently locked major in `uv.lock` (`grep -n -A1 '^name = "<pkg>"$' uv.lock`) — use `<next major>` for ≥1.0 packages and `<next minor>` for 0.x packages (`cactus-needle`, `moonshine-voice`, `mlx-audio`, `parakeet-mlx`, `mlx-whisper`); skip any whose locked version you can't read. Run `uv lock`.
**Verify**: `uv lock --check` → exit 0; `git diff --stat uv.lock` shows only metadata/specifier changes (no package version bumps); `pytest -q` → pass.

### Step 4: Make `uv.lock` follow the torch pairing Docker uses
Add to `pyproject.toml`:
```toml
[tool.uv]
# Keep native PyTorch/TorchCodec ABIs paired exactly as in docker/constraints.txt
constraint-dependencies = ["torch==2.10.0", "torchaudio==2.10.0", "torchcodec==0.10.0"]
```
Run `uv lock`. Expect `torch`, `torchaudio`, `torchcodec` to move to 2.10.0 / 2.10.0 / 0.10.0 and nothing else of substance to change. Then run the test suite in the resolved environment (`uv run --extra diarize pytest -q`; model-dependent tests may skip) and the Docker smoke test.
**Verify**: `grep -n -A1 '^name = "torch"$' uv.lock` shows `version = "2.10.0"`; `pytest -q` passes; Docker smoke exits 0.
If `uv lock` reports an unsatisfiable resolution (e.g. `pyannote-audio` requires a newer torch), STOP — do not loosen the constraint; report the conflicting requirement so the owner can choose which side moves.

## Test plan
No new tests; correctness is the verify lines above (lock check, install, lint/types/tests/build, Docker smoke).

## Done criteria
- [ ] `git ls-files videos | grep -cE "\.(mp4|ecproj|filmcraft|scraft|mov)$"` → `0`, and the files still exist on disk
- [ ] `git check-ignore -q .DS_Store && git check-ignore -q .agents/skills/x` exit 0
- [ ] `grep -n '"\^0' web/package.json` shows no `@astryxdesign` or `@stylexjs` entries
- [ ] `uv lock --check` exits 0; `pytest -q` exits 0; web lint/tsc/tests/build exit 0
- [ ] `grep -n "pyannote.audio" pyproject.toml` shows `<5`
- [ ] Only in-scope files modified; `plans/README.md` updated

## STOP conditions
- `git rm --cached` would remove a file that is *not* a video/editor binary, or a listed file is referenced by the app/build (`grep -rn "videos/" dzomdu web/src web/package.json Dockerfile` — it should return nothing).
- Step 4 resolution fails or changes unrelated package versions.
- `npm install` changes any package other than the pinned ones in `web/package-lock.json`.
- The owner has already moved the media elsewhere or asked for a history rewrite (then this plan is superseded for Step 1).

## Maintenance notes
- Untracking does not shrink history: the 322 MiB pack remains for existing clones. A history rewrite or a fresh repo is a separate owner decision; if chosen, do it after merging this plan and coordinate with anyone holding clones.
- Astryx updates are now deliberate: bump, run the web checks, rebuild the theme (`npx astryx theme build ...`), and eyeball the app in light and dark.
- When Docker's torch pin moves, change `docker/constraints.txt` and the `[tool.uv]` block together.
