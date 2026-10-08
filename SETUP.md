# Setup guide (Mac + Python virtual environment)

This guide installs Dzomdu on an Apple Silicon Mac. All of its Python packages go into a
**virtual environment**: a `.venv` folder inside the project. Nothing is installed into your
system Python. To remove every Python package Dzomdu installed, delete that folder.

| What | Where it goes | Size |
|---|---|---|
| Python 3.12, ffmpeg, git, Ollama, Node.js | Homebrew (`/opt/homebrew`) | ~1.2 GB |
| Dashboard build tools (Next.js, only needed to build it) | `dzomdu/web/node_modules/` | ~600 MB |
| Dzomdu and its Python libraries (PyTorch, pyannote, Parakeet…) | `dzomdu/.venv/` | ~3 GB |
| Speech and speaker models (downloaded on first use) | `~/.cache/huggingface/` | ~1.5 GB |
| LLM for summaries (`qwen3:14b`) | `~/.ollama/` | ~9 GB |
| Your meeting notes | the vault folder you choose | — |
| Voiceprints, recordings, caches | `~/Library/Application Support/dzomdu/` | grows with use |

You need macOS 14 or newer, an M1–M4 Mac, and about **15 GB of free disk space**.

---

## 1. Install the system tools (once)

If you don't have [Homebrew](https://brew.sh) yet, install it first:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install Python 3.12, ffmpeg, git, Ollama and Node.js. Node.js is only needed to build
the dashboard:

```bash
brew install python@3.12 ffmpeg git ollama node
python3.12 --version        # should print Python 3.12.x
```

> Use `python3.12`, not plain `python3`. The `python3` that ships with macOS is 3.9, which
> is too old for Dzomdu (it needs 3.11 or newer).

## 2. Get the code

```bash
cd ~
git clone https://github.com/TenzinKhorlo/dzomdu.git
cd dzomdu
git checkout claude/tender-edison-lzi890   # the code lives on this branch until it is merged
ls                                         # you should see pyproject.toml, SETUP.md, dzomdu/
```

If you already had a `dzomdu` folder from earlier, update it instead of cloning:
`git fetch origin && git checkout claude/tender-edison-lzi890`.

## 3. Create and activate the virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Your prompt now starts with `(.venv)`. Check that you are using the environment's Python:

```bash
which python      # → /Users/<you>/dzomdu/.venv/bin/python
python --version  # → Python 3.12.x
python -m pip install --upgrade pip
```

> **Activate it in every new terminal window** before using Dzomdu:
> `cd ~/dzomdu && source .venv/bin/activate`. Type `deactivate` to leave it.

## 4. Install Dzomdu into the environment

```bash
pip install -e ".[mac,diarize]"
```

- **`-e` (editable):** a later `git pull` takes effect without reinstalling.
- **`mac`:** Parakeet and Whisper for speech-to-text on Apple Silicon.
- **`diarize`:** pyannote for speaker separation and voiceprints. This pulls in PyTorch, so
  the install takes a few minutes.
- **Quotes:** keep the quotes around `".[mac,diarize]"`. Without them zsh reports
  `no matches found`.

To also run the Phase 0 benchmarks, add `bench`: `pip install -e ".[mac,diarize,bench]"`.

Check it worked:

```bash
dzomdu --help
```

## 5. Allow the speaker model download (once)

The speaker-separation model is free, but Hugging Face asks you to accept its terms before
you can download it.

1. Create a free account at [huggingface.co](https://huggingface.co/join).
2. Open [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
   and accept the conditions.
3. Create a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
   and choose the token type **Read**. If you pick **Fine-grained** instead, you must tick
   *"Read access to contents of all public gated repos you can access"*. Otherwise the
   download is refused even after accepting the terms.
4. Save the token on this Mac. Run this with the environment active:

   ```bash
   hf auth login               # older versions: huggingface-cli login
   ```

   Paste the token when asked. Answer **n** to "Add token as git credential?".

The token is stored in `~/.cache/huggingface/token`, never in the project. After the first
download the model runs fully offline. `dzomdu doctor` (step 7) asks Hugging Face whether
your account has access and tells you exactly what to fix if not.

## 6. Set up the local LLM (Ollama)

`brew install ollama` installs the command, but the Ollama **server** must also be running.
Run it as a background service: it then starts automatically at every login.

On a **24 GB Mac**, first set these two options. They halve the memory the LLM needs while
it works:

```bash
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
```

Then start the service and download the summary model:

```bash
brew services start ollama
curl http://localhost:11434        # → Ollama is running
ollama pull qwen3:14b              # ~9 GB
```

Check that the memory settings were picked up:

```bash
grep "server config" $(brew --prefix)/var/log/ollama.log | tail -1 | tr ' ' '\n' | grep -E "FLASH_ATTENTION|KV_CACHE_TYPE"
```

You want to see `OLLAMA_FLASH_ATTENTION:true` and `OLLAMA_KV_CACHE_TYPE:q8_0`. If they're
missing, run `brew services restart ollama` and check again. `launchctl setenv` is forgotten
when the Mac restarts, so after a reboot run the two `launchctl` lines again, followed by
`brew services restart ollama`.

> Not using Homebrew's service? Run `ollama serve` in a separate terminal window and leave
> it open. In that case put `export OLLAMA_FLASH_ATTENTION=1` and
> `export OLLAMA_KV_CACHE_TYPE=q8_0` in `~/.zshrc`.

## 7. Configure and check

Choose where your notes should live. This can be a new folder, or a folder inside an
existing Obsidian vault:

```bash
dzomdu init --vault ~/Documents/DzomduVault
dzomdu doctor
```

`doctor` should report a ✓ on every line (on the "Diarization model" line, ✓ means the
download is allowed):

```
✓ Apple Silicon Mac
✓ ffmpeg
✓ ASR backend 'parakeet'
✓ Diarization (pyannote.audio)
✓ Diarization model downloaded — will download on first use with your Hugging Face token
✓ LLM (ollama @ http://localhost:11434) — qwen3:14b available
✓ Vault — /Users/<you>/Documents/DzomduVault
```

In Obsidian, use **Open folder as vault** and pick the vault folder.

## 8. Build the dashboard (once)

```bash
cd ~/dzomdu/web        # or wherever you cloned it
npm install
npm run build
cd ..
```

This writes `web/out/`, which `dzomdu ui` serves. Run it again after a `git pull` that
changes the dashboard. Without a build, `dzomdu ui` shows the simpler classic interface.

## 9. First run

```bash
dzomdu ui
```

Your browser opens **http://localhost:8765**. The first time you press **Start recording**:

- The browser asks for microphone access. Allow it.
- If nothing is recorded, check **System Settings → Privacy & Security → Microphone** and
  turn on your browser.
- The first processing run downloads the speech model (~1.2 GB) and the speaker model, so
  it takes a few extra minutes. Later runs are fast and fully offline.

Before recording a real meeting, try a short test. Record yourself and a colleague for a
minute, or process an existing file:

```bash
dzomdu process ~/Downloads/test.m4a --no-llm
```

---

## Daily use

```bash
cd ~/dzomdu
source .venv/bin/activate
dzomdu ui
```

You can also run the environment's copy of Dzomdu directly, with no activation. Add an
alias to `~/.zshrc`:

```bash
echo "alias dzomdu='$HOME/dzomdu/.venv/bin/dzomdu'" >> ~/.zshrc
source ~/.zshrc
dzomdu ui      # works from any folder now
```

## Updating

```bash
cd ~/dzomdu
source .venv/bin/activate
git pull
pip install -e ".[mac,diarize]"   # picks up any new dependencies
(cd web && npm install && npm run build)   # rebuild the dashboard
```

## Starting over or uninstalling

| To remove | Command | Note |
|---|---|---|
| Python packages | `rm -rf ~/dzomdu/.venv` | Recreate with steps 3–4 |
| Downloaded speech/speaker models | `rm -rf ~/.cache/huggingface/hub/models--pyannote--* ~/.cache/huggingface/hub/models--mlx-community--*` | Downloaded again on next use |
| LLM | `ollama rm qwen3:14b` | |
| Voiceprints, recordings, caches | `rm -rf ~/Library/Application\ Support/dzomdu` | ⚠️ **Forgets every remembered voice** and deletes recordings |
| Settings | `rm -rf ~/.config/dzomdu` | |
| Meeting notes | your vault folder | These are your notes. Keep them! |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip install` says `does not appear to be a Python project` | The folder has no code yet (`ls` shows no `pyproject.toml`). Run `git fetch origin && git checkout claude/tender-edison-lzi890`. |
| `zsh: command not found: hf` | `hf` is installed by step 4, so finish that first. On older versions use `huggingface-cli login`. |
| `zsh: command not found: dzomdu` | The environment isn't active. Run `source ~/dzomdu/.venv/bin/activate`. |
| `zsh: no matches found: .[mac,diarize]` | Put quotes around it: `pip install -e ".[mac,diarize]"` |
| `python3.12: command not found` | Run `eval "$(/opt/homebrew/bin/brew shellenv)"`, or open a new terminal after installing Homebrew. |
| pip says the package `requires a different Python` | The environment was made with an old Python. Run `rm -rf .venv` and repeat step 3 with `python3.12`. |
| `Could not download Pipeline from pyannote/speaker-diarization-community-1` | Run `dzomdu doctor`: the "Diarization model available" line names the cause. Usually the terms weren't accepted with the **same account** as the token (step 5.2), or a fine-grained token lacks gated-repo access (step 5.3). Fix it, then restart `dzomdu ui`. |
| Diarization errors mentioning `mps` | Dzomdu retries on the CPU automatically. To always use the CPU, set `device = "cpu"` under `[diarization]` in `~/.config/dzomdu/config.toml`. |
| Two people come out as one speaker after processing | Dzomdu checks every speaker in short windows and separates voices that clearly differ. If two very similar voices still merge, enter the **Number of speakers** on the Record form, which makes the speaker separation use exactly that many. You can also lower `same_voice_threshold` (default `0.5`) under `[speakers]` in `~/.config/dzomdu/config.toml` to separate more readily. If one person is split in two, give both the same name on the review screen and they're merged. |
| A sentence from the live transcript is missing after processing | The final pass re-transcribes any stretch where speech was heard but no words came back. For a meeting processed before this check existed, process its recording again: upload `~/.local/share/dzomdu/recordings/<session>.wav` on the Record page, or run `dzomdu process` on it. |
| `could not connect to ollama server` / status badge says the LLM is not reachable | Start the server with `brew services start ollama` (or `ollama serve` in another window), then check `ollama list` shows `qwen3:14b`. |
| Browser won't record | Use `http://localhost:8765` exactly, and check the macOS microphone permission (step 8). |
| `dzomdu ui` says "Dashboard not built yet" | Run `cd web && npm install && npm run build` (step 8). |
| `address already in use` | Another copy is running. Close it, or run `dzomdu ui --port 8800`. |
| VS Code shows import errors | **Python: Select Interpreter** → `./.venv/bin/python`. |

## For developers

```bash
source .venv/bin/activate
pip install pytest ruff
pytest            # runs everything with stand-in models; needs no downloads
ruff check .
```

(If you prefer [uv](https://docs.astral.sh/uv/), `uv sync --extra mac --extra diarize` does
steps 3–4 in one go. It also uses a project-local `.venv`, not a global install.)
