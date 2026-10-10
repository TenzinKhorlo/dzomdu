# Dzomdu

Offline meeting notes for in-person meetings. Dzomdu recognises who is speaking and
remembers voices across meetings. It writes a speaker-attributed transcript, and produces a
summary, decisions, action items and minutes in the format you choose. Everything is saved
as Markdown that opens directly in Obsidian.

Leave the meeting title blank to have the configured LLM name it from the discussion when
notes are generated. The pencil beside a saved meeting's title lets you rename it at any
time. Custom titles survive **Rewrite**, and renaming preserves the note's file path and
handwritten contents so existing links keep working.

Everything runs locally with open-source models:

| Step | Model / tool |
|---|---|
| Who spoke when + voiceprints | [pyannote.audio 4](https://github.com/pyannote/pyannote-audio) `speaker-diarization-community-1` |
| Speech to text | Parakeet or Whisper Turbo on Apple Silicon; Whisper Turbo through faster-whisper on Linux CPU / NVIDIA CUDA |
| Summary & minutes | Any local LLM via [Ollama](https://ollama.com) (default `qwen3:14b`) |

Dzomdu includes a local dashboard, CLI and benchmark tools. See [PLAN.md](PLAN.md) for the
design and roadmap.

## Setup

Choose an installation path:

| Computer | Manual setup from GitHub | Docker |
|---|---|---|
| Apple Silicon Mac | [Native macOS](#manual-setup-macos-apple-silicon), with Apple GPU acceleration | [CPU container](#docker-setup-macos-or-linux); Docker cannot use the Apple GPU |
| Linux CPU | [Native Linux](#manual-setup-linux), with Whisper Turbo and Pyannote | [CPU container](#docker-setup-macos-or-linux) |
| Linux x86_64 + NVIDIA GPU | [Native Linux with CUDA](#manual-setup-linux), with CUDA-enabled PyTorch and faster-whisper | [NVIDIA container](#docker-setup-linux-nvidia-gpu) |

Native Mac instructions require **Apple Silicon and macOS 14+**. The Linux commands below
target **Ubuntu 24.04** and **Python 3.12**. Other distributions need equivalent system
packages. Use **Node.js 22 LTS** to build the dashboard. Docker includes Python, Node.js,
FFmpeg and the model runtimes, so those tools do not need to be installed on the host.

Allow space for Python packages or container images, model weights, and saved recordings.
The first setup needs internet access to install packages and download models; subsequent
meetings can run offline with downloaded models and a local LLM.

### Hugging Face access (all installation paths)

Accept the model conditions for
[Pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1), then
create a [Hugging Face Read token](https://huggingface.co/settings/tokens) using the same
account. Native installations use `hf auth login`; Docker uses `HF_TOKEN` in `.env`.
The token is needed to download the speaker model, not to send meeting audio anywhere.

### Manual setup: macOS (Apple Silicon)

Install [Homebrew](https://brew.sh/) first if needed, then run:

```bash
brew install python@3.12 ffmpeg git ollama node@22
export PATH="$(brew --prefix node@22)/bin:$PATH"

git clone https://github.com/TenzinKhorlo/dzomdu.git
cd dzomdu
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[mac,diarize,denoise]'
hf auth login

brew services start ollama
ollama pull qwen3:14b
dzomdu init --vault ~/Documents/DzomduVault

cd web
npm ci
npm run build -- --webpack
cd ..
dzomdu doctor
dzomdu ui
```

Open **http://localhost:8765**. The native default is **Parakeet for English** with
**Pyannote for speakers**. For Nepali or automatic language detection, select **Whisper
large-v3 Turbo** in **Settings → Model library**, download it, and save it as the default.
To enable the optional Qwen, Moonshine and Nemotron-3-Diarization runtimes for testing:

```bash
python -m pip install -e '.[mac,speech-models,diarize,denoise]'
```

Restart Dzomdu after installing additional runtimes. Installing a runtime does not download
every model; choose the models you want in Settings. Keep Pyannote for meetings with 15+
participants. A more detailed native Mac walkthrough is in [SETUP.md](SETUP.md).

### Manual setup: Linux

Install [Node.js 22 LTS](https://nodejs.org/en/download) with npm, and
[Ollama for Linux](https://docs.ollama.com/linux). Install the remaining system tools:

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv git ffmpeg libsndfile1 ca-certificates
node --version                 # v22.x
npm --version

git clone https://github.com/TenzinKhorlo/dzomdu.git
cd dzomdu
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

**Choose one PyTorch installation**, before installing Dzomdu:

```bash
# CPU-only Linux
python -m pip install -c docker/constraints.txt torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

```bash
# NVIDIA Linux: install a driver compatible with CUDA 12.8 first
nvidia-smi
python -m pip install -c docker/constraints.txt torch torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Then install the shared audio decoder and Dzomdu runtimes. The constraints pair PyTorch,
torchaudio and TorchCodec versions; decoding runs on CPU even when inference uses CUDA.

```bash
python -m pip install -c docker/constraints.txt torchcodec --index-url https://download.pytorch.org/whl/cpu
python -m pip install -c docker/constraints.txt -e '.[diarize,whisper,denoise,moonshine]'
python -m pip check
hf auth login

sudo systemctl start ollama     # if installed as a systemd service
ollama pull qwen3:14b
dzomdu init --vault ~/Documents/DzomduVault
```

If Ollama is not installed as a service, leave `ollama serve` running in another terminal
before pulling the LLM. Choose a smaller LLM if `qwen3:14b` does not fit your available memory,
and set the same model name in Dzomdu's Settings.

**Configure Linux before starting Dzomdu.** `dzomdu init` currently creates Mac defaults.
Edit `~/.config/dzomdu/config.toml`, replacing its existing `[asr]` and `[diarization]`
sections with the following. Keep the other sections and the vault/data paths:

```toml
[asr]
backend = "faster-whisper"
model = "dropbox-dash/faster-whisper-large-v3-turbo"
language = "en"
device = "cpu"
compute_type = "int8"

[diarization]
backend = "pyannote"
model = "pyannote/speaker-diarization-community-1"
device = "cpu"
```

Use `language = "ne"` for Nepali or `"auto"` for automatic language detection. On **NVIDIA**,
change both `device` values to `"cuda"` and `compute_type` to `"float16"` (or
`"int8_float16"` to reduce transcription VRAM). Apple MLX models are unavailable on Linux.

For native NVIDIA installations, faster-whisper also needs **CUDA 12 cuBLAS and cuDNN 9**.
The CUDA PyTorch installation above includes these Python-packaged libraries; expose their
directories before launching Python, as described in the
[faster-whisper GPU guide](https://github.com/SYSTRAN/faster-whisper#gpu):

```bash
export LD_LIBRARY_PATH="$(python -c 'import nvidia.cublas, nvidia.cudnn; print(nvidia.cublas.__path__[0] + "/lib:" + nvidia.cudnn.__path__[0] + "/lib")')${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
python -c 'import torch, ctranslate2; print("PyTorch CUDA:", torch.cuda.is_available()); print("CTranslate2 GPUs:", ctranslate2.get_cuda_device_count()); print("CUDA kernel:", torch.ones(1, device="cuda").sum().item())'
```

Expect `True`, at least one CTranslate2 GPU, and a successful CUDA kernel. Repeat the library
path export in each new terminal used to run Dzomdu. CPU installations skip this step.

Build and launch the dashboard from the repository root with the virtual environment active:

```bash
cd web
npm ci
npm run build -- --webpack
cd ..
dzomdu doctor
dzomdu ui --no-open
```

Open **http://localhost:8765**. Linux uses **Whisper Turbo** for transcription and **Pyannote**
for speaker separation and saved voice profiles. Download the models in Settings before a
meeting. Selecting a streaming model does not change the current live preview's utterance-based
processing.

### Docker setup: macOS or Linux

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) on macOS, or
[Docker Engine with the Compose plugin](https://docs.docker.com/engine/install/) on Linux.
Start Docker, then clone the repository:

```bash
git clone https://github.com/TenzinKhorlo/dzomdu.git
cd dzomdu
cp .env.example .env
```

Edit `.env` before the first start. For a fully local setup with Ollama in Docker, set:

```dotenv
HF_TOKEN=your_hugging_face_read_token
LLM_BASE_URL=http://ollama:11434
LLM_MODEL=qwen3:14b
DZOMDU_ASR_LANGUAGE=en
```

Start the CPU deployment and download the summary model. For NVIDIA acceleration, use the
GPU commands in the next section instead:

```bash
docker compose --profile local-llm up -d --build
docker compose exec ollama ollama pull qwen3:14b
docker compose logs -f dzomdu
```

Open **http://localhost:8765**. This runs Whisper Turbo, Pyannote and Ollama on CPU. On a Mac,
the native installation can use the Apple GPU; for Docker, you can also use Ollama on the Mac
instead of the LLM container. Set `LLM_BASE_URL=http://host.docker.internal:11434`, start host
Ollama, pull your LLM there, and omit `--profile local-llm`. See [DOCKER.md](DOCKER.md) for
host Ollama on Linux or a hosted LLM connection.

### Docker setup: Linux NVIDIA GPU

Use an **x86_64 Linux** machine with an NVIDIA driver compatible with CUDA 12.8 and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
Follow NVIDIA's guide to install the toolkit, configure Docker's NVIDIA runtime, and restart
Docker. Confirm `nvidia-smi` works on the host.

Clone the repository and prepare `.env` as in the Docker section above. Use both Compose
files to start the GPU deployment with local Ollama:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile local-llm up -d --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec ollama ollama pull qwen3:14b
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec dzomdu python /app/docker/check_gpu.py
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs -f dzomdu
```

Whisper Turbo, Pyannote and the optional Ollama container receive GPU access. They share GPU
memory, so choose an LLM that fits alongside speech processing. The GPU startup check fails
with an explanation if CUDA, cuDNN or GPU access is unavailable. Use both Compose files
consistently for subsequent commands. More GPU troubleshooting and migration details are in
[DOCKER.md](DOCKER.md#nvidia-gpu-linux).

### Storage, restarting and updates

| Installation | Configuration | App data and recordings | Notes |
|---|---|---|---|
| Native Mac | `~/.config/dzomdu/config.toml` | `~/Library/Application Support/dzomdu/` | Your chosen vault |
| Native Linux | `~/.config/dzomdu/config.toml` | `~/.local/share/dzomdu/` | Your chosen vault |
| Docker | `dzomdu-config` volume | `dzomdu-data` and `dzomdu-models` volumes | `./vault/` |

Native paths above are the defaults; config/data environment overrides are supported.
Back up the vault **and** app data to keep notes, recordings, voiceprints and chat history.
Docker volume names normally include the Compose project prefix. `docker compose down`
keeps named volumes; adding `-v` deletes them. See [DOCKER.md](DOCKER.md) for volume backup
and moving notes from Mac to Linux.

For a native installation, stop Dzomdu with **Ctrl+C**, then update from the repository root:

```bash
source .venv/bin/activate
git pull --ff-only
# Repeat the pip installation for your platform above if dependencies changed.
cd web
npm ci
npm run build -- --webpack
cd ..
dzomdu ui
```

On Mac, add the Node.js PATH export from the installation steps in new terminals; on native
NVIDIA Linux, add the `LD_LIBRARY_PATH` export. Keep Ollama running when using summaries/chat.

For Docker CPU, update with `git pull --ff-only`, then
`docker compose --profile local-llm up -d --build`. For NVIDIA, use the same `up -d --build`
command with both Compose files from the GPU section. Existing model/LLM choices are kept;
change them in **Settings**, since most `.env` values initialize a new config only once.

For a remote Linux server, keep Dzomdu bound to localhost and connect with a tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 user@your-linux-server
```

Open `http://localhost:8765` on your own computer; microphone recording works on localhost.
For direct remote access, use HTTPS with authentication and WebSocket support. Dzomdu has no
built-in login.

## Use: dashboard

After setup, activate the virtual environment and run `dzomdu ui`, or start your Docker
deployment. The dashboard is available at **http://localhost:8765**.

| Page | What it does |
|---|---|
| **Dashboard** | Meetings and hours over the last 30 days with trends, time in meetings per day, who talks most, recent meetings, and open action items. Tick an item off, or swipe it to the right. |
| **Record** | Fill in an optional title, project, attendees and minutes format, then press the red button. A live transcript with speaker labels appears while you record: words show up about a second after they're spoken, in a lighter tone until the speaker pauses, with the timer and **Stop & process** on a floating bar at the bottom. **Stop & process** runs the full pipeline. On **Who said what?** you confirm each voice (▶ plays a sample), and new names are remembered for next time. If you give two voices the same name, you're told they'll be merged into one person. You can also drop in an existing recording instead. |
| **Meetings** | Search and filter by project. Each meeting shows the notes, a searchable transcript, its action items, speaking time, decisions, **Open in Obsidian**, and **Rewrite**, which redoes the minutes in another format or with extra instructions. A player bar plays the recording: the transcript follows along, clicking a turn or a timestamp in the notes plays from that moment, and you can drag the scrubber or use the arrow keys. |
| **Tasks** | Action items from all saved meetings, linked to their source meeting and its project. Search or filter by project and completion status. Each new task gets a reminder seven days after it is added, independently of any deadline stated in the meeting; click the reminder date to choose a custom date. Due and overdue reminders appear in **Reminders** and the sidebar count. Completion updates checkbox notes; table-style actions are tracked in the meeting record. Task status and custom dates survive restarts, reordering and regeneration of the same action items. |
| **Ask Dzomdu** | Ask questions across your meeting notes or choose specific meetings. Follow up on answers and open the cited source notes. Answers stream as they are generated. The sidebar shows three conversations, with pinned chats first; **More** opens searchable history. The conversation menu lets you rename, pin/unpin, delete, or move a chat to a project. **Ask about this meeting** on a meeting page starts a focused chat. |
| **People** | Everyone whose voice is known, with role, organisation and bio. These are used as LLM context and saved in `People/` in your vault. You can also rename a person or forget their voice. |
| **Projects** | Open a project to see its assigned team, meeting participants, meeting history, and remaining tasks with assignees. **Manage team** assigns members; tasks can be filtered by assignee, completed, or given a custom reminder from the project page. Each project also has an overview note and glossary. The sidebar shows the three most recent projects; **More** opens the full list. The project menu supports rename and delete, with confirmation before deleting its related meetings, notes, and saved recordings. |
| **Settings** | Model and LLM status, vault location, minutes formats. |

Action items are the Obsidian Tasks lines in your notes. Ticking one in the dashboard updates
the note, and ticking it in Obsidian shows up in the dashboard. Every change offers **Undo** for
a few seconds, so only actions that can't be undone, like forgetting a voice or discarding a
recording, ask for confirmation.

The interface follows your system settings: light or dark appearance (the button in the top
right cycles through them), **Reduce motion** (animations become instant cross-fades),
**Reduce transparency** (translucent bars become solid) and **Increase contrast**.

Chat uses the LLM configured in **Settings**, including local Ollama or a configured remote
provider. It reads the current saved notes (with transcript fallback), retrieves relevant excerpts,
and includes conversation context. Large libraries use selected excerpts, so answers may not
cover every meeting. Conversations are saved in `chats.sqlite` under the Dzomdu data directory;
chat does not modify your notes. Project links organize chats without changing the selected
meeting notes. Linked chats follow project renames and keep their history when a project is
deleted. Project cards link to their conversations. Team assignments stay with the project when it is
renamed and are included in OKF exports.

Audio is saved continuously while recording. If the app or the computer crashes, the recording
is recovered the next time `dzomdu ui` starts. Everything runs on localhost; nothing is loaded
from the internet. The original single-page interface is still at `/classic/`, and it is used
automatically if the dashboard isn't built.

To work on the dashboard itself, see [web/README.md](web/README.md).

## Use: command line

```bash
# Process a recording (any format: m4a, mp3, wav, mp4…)
dzomdu process ~/Recordings/kickoff.m4a \
    --project "Solar Microgrid" -a "Karma Wangmo" -a "Tenzin Dorji"
```

1. Dzomdu diarizes and transcribes the recording, then matches each voice against the
   people it already knows.
2. It asks you to confirm each speaker. Press Enter to accept a match, type a name for a
   new person, `p` to play a short clip, or `-` to leave the speaker unidentified. The
   voices you confirm are remembered for future meetings.
3. The local LLM writes the summary and minutes. The note is saved to
   `Projects/Solar Microgrid/Meetings/2026-10-07 <title>.md`.

Other commands:

```bash
dzomdu regenerate <meeting-id> -T board           # same meeting, different minutes format
dzomdu regenerate <meeting-id> -i "Shorter, bullet points for the director"
dzomdu templates                                  # list formats (standard, executive, board)
dzomdu people add "Karma Wangmo" --role "Project manager" --org "GovTech"
dzomdu speakers enroll "Karma Wangmo" sample.m4a --consent   # 20-30 s of one person talking
dzomdu speakers list | rename OLD NEW | forget NAME
```

Useful `process` options:

- `--num-speakers N`: give the speaker count if you know it.
- `--no-review`: skip the speaker questions.
- `--no-llm`: transcript only.
- `-T <template>`: choose the minutes format.
- `-i "<instructions>"`: add extra style instructions for the LLM.

Transcription and diarization results are cached, so regenerating or re-running is quick.

## What a note looks like

```markdown
---
type: meeting
title: Site survey planning
date: 2026-10-07T10:00+06:00
description: Site survey decisions and next steps.
status: draft
generated: {by: dzomdu/0.1.0, at: '2026-10-07T05:00:00+00:00'}
sources:
  - id: audio
    resource: file:///recordings/site-survey.wav
    title: Original meeting recording
duration: 52m
project: '[[Solar Microgrid]]'
attendees: ['[[Karma Wangmo]]', '[[Tenzin Dorji]]']
...
---
## Decisions
- Proceed with the site survey in Punakha ([[#^t14|00:14:32]])

## Action items
- [ ] [[Karma Wangmo]] Draft the survey budget 📅 2026-10-14 ([[#^t21|00:19:05]])

## Transcript
**[[Tenzin Dorji]]** `00:00:05` Good morning everyone, let's start with… ^t1
```

Every decision and action item links to the transcript turn it came from, so you can check
it against what was actually said.

### The vault

| Path | Contents |
|---|---|
| `People/` | One note per person. The role and bio are used as LLM context. |
| `Projects/<name>/` | The project overview and glossary, plus that project's meetings. |
| `Templates/Minutes/` | Minutes formats. Copy one and edit it to make your own. |

Voiceprints are biometric data, so they are kept **outside** the vault in the app data folder
(`~/Library/Application Support/dzomdu`).

### Open Knowledge Format

New and regenerated meeting notes follow [Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md): UTF-8 Markdown with a YAML `type`, title, description, tags, source provenance, recording hash and generation metadata. A note contains both the summary and speaker-attributed transcript. Generated notes start as `draft`; confirming speaker names does not mark the notes as human-verified. Meeting and generation timestamps include explicit timezone offsets. Older dates without an offset are interpreted in the installation's local timezone.

The live vault retains Obsidian wikilinks and block citations. To create a portable OKF bundle for other tools, including existing meetings:

```bash
dzomdu export-okf ~/Documents/DzomduKnowledge
```

Choose a new destination folder. The export includes `index.md` declaring `okf_version: "0.2"`, separate `meetings/` and `transcripts/` concepts, and people/project context. Citations become standard Markdown footnotes backed by `sources` entries and links to transcript anchors. The export reads current notes, retaining custom sections and extra metadata. Original notes, records and edit-protection hashes remain untouched. If a note is missing, it is reconstructed from its saved record. Recordings, voiceprints, databases and model files are not included; audio provenance uses its SHA-256 fingerprint.

OKF is the portable document format; the local JSON records and SQLite database still support regeneration, the dashboard and chat history. No Google account, cloud service or additional container is required.

## Phase 0 benchmarks

See [bench/README.md](bench/README.md). Record a few real meetings, label who spoke when in
Audacity, then:

```bash
dzomdu bench all -m bench/manifest.yaml
```

This measures word error rate (WER) for each speech-to-text model and diarization error rate
(DER). It also calibrates the voice-matching thresholds and generates blind side-by-side
notes from several LLMs.

## Development

```bash
source .venv/bin/activate
pip install pytest ruff
pytest
ruff check .
```

The test suite runs the whole pipeline with stand-in models and synthetic audio, so it needs
no downloads.

### Meeting model library

Open **Settings → Default meeting models** to choose transcription, meeting language,
speaker separation and an optional maximum speaker count. **Model library** provides individual
and bulk downloads, progress, retry, platform compatibility and runtime setup instructions.
Downloads do not change defaults; select a model and save after testing it. The download queue
survives server restarts and completed files are reused from the local caches.

On Apple Silicon, install the optional alternatives in the same environment as Dzomdu:

```sh
python -m pip install -e '.[mac,speech-models,diarize,denoise]'
```

The catalog includes Parakeet, Whisper large-v3 Turbo (MLX on Mac, CPU/CUDA on Linux/Windows), Moonshine Small/Medium Streaming
and Qwen3-ASR 0.6B/1.7B.
The MLX Qwen adapters use a shared Qwen forced aligner for word timestamps. These
adapters currently expose English; use Whisper for Nepali or automatic language detection.
Dzomdu's live preview still processes utterance chunks; selecting a model with a streaming
architecture does not yet replace that preview with a persistent native streaming session.

**For meetings with 15+ participants on a Mac, keep Pyannote Community-1.** Its clustering and
Dzomdu's voice-profile matching have no fixed eight- or fifteen-speaker slot limit. The optional
Nemotron-3-Diarization adapter has eight slots; selecting it applies a maximum of eight
speakers automatically, and you can set a lower limit.
Larger declared meetings are rejected before recording/upload. Both adapters reuse the same
Pyannote embedding space, so switching does not discard existing confirmed voice profiles.
Large-room recognition quality and speed still need evaluation on actual meeting recordings;
a speaker-count setting is not an accuracy guarantee.

### Background noise suppression

Open **Settings → Audio processing** to enable local RNNoise suppression. It applies to
live transcripts and uploaded recordings. Start with **Light** for meetings; **Balanced**
reduces more noise while still retaining some original signal. It is off until enabled.

```sh
python -m pip install -e '.[denoise]'
```

Restart the backend after installing or updating. RNNoise's model is bundled with the
optional runtime; no separate model download, access token or external service is needed.
The RNNoise code and model use BSD-3-Clause and the Python wrapper uses Apache-2.0, both
permitting commercial use. See [third-party notices](THIRD_PARTY_NOTICES.md).

Noise suppression creates a separate transcription copy and keeps the original recording.
Speaker detection, cluster refinement, identification and saved voice samples use the
original audio, protecting quiet and overlapping participants from denoising artifacts.
It does not select a main speaker or use its voice-activity probability to mute audio.
Even so, suppression may attenuate quiet speech; it cannot guarantee removal of all music,
singing, background conversations or noise. This also does not make ASR transcribe two
simultaneous speakers independently.

The streaming implementation compensates RNNoise's two-frame delay and both resampling
filters, preserves duration and timestamps, and drains the tail at the end of a stream.
Its algorithmic delay is 21.25 ms, plus up to a 10 ms frame and processing/buffering costs.
Performance depends on hardware and concurrent models; measure real meeting latency before
choosing a default. Suppression strength and runtime version are included in enhanced-audio
and transcription cache keys. If suppression fails, processing reports the problem and
uses original audio. Settings cannot change during an active meeting or pending review.
