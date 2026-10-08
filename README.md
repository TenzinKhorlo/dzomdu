# Dzomdu

Offline meeting notes for in-person meetings. Dzomdu recognises who is speaking and
remembers voices across meetings. It writes a speaker-attributed transcript, and produces a
summary, decisions, action items and minutes in the format you choose. Everything is saved
as Markdown that opens directly in Obsidian.

Everything runs locally with open-source models:

| Step | Model / tool |
|---|---|
| Who spoke when + voiceprints | [pyannote.audio 4](https://github.com/pyannote/pyannote-audio) `speaker-diarization-community-1` |
| Speech to text | NVIDIA Parakeet TDT 0.6B v2 via [parakeet-mlx](https://github.com/senstella/parakeet-mlx) (Whisper as fallback) |
| Summary & minutes | Any local LLM via [Ollama](https://ollama.com) (default `qwen3:14b`) |

See [PLAN.md](PLAN.md) for the full design and roadmap. This is the **Phase 0 prototype**: a
CLI plus benchmark tools.

## Quick start with Docker

Works on Mac, Windows and Linux. See **[DOCKER.md](DOCKER.md)** for the details.

```bash
cp .env.example .env     # add your Hugging Face token and language model choice
docker compose up -d --build
# open http://localhost:8765
```

## Install (Apple Silicon Mac)

**Step-by-step guide: [SETUP.md](SETUP.md)**. It installs everything into a Python virtual
environment (`.venv`), not globally. In short:

```bash
brew install python@3.12 ffmpeg git ollama node
git clone https://github.com/TenzinKhorlo/dzomdu.git && cd dzomdu
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[mac,diarize]"
hf auth login                  # after accepting the pyannote model terms on Hugging Face
ollama pull qwen3:14b
dzomdu init --vault ~/Documents/DzomduVault
dzomdu doctor
(cd web && npm install && npm run build)   # the dashboard
dzomdu ui
```

## Use: dashboard

Build the dashboard once. This needs Node.js (`brew install node`):

```bash
cd web && npm install && npm run build && cd ..
dzomdu ui          # opens http://localhost:8765 in your browser
```

| Page | What it does |
|---|---|
| **Dashboard** | Meetings and hours over the last 30 days with trends, time in meetings per day, who talks most, recent meetings, and open action items. Tick an item off, or swipe it to the right. |
| **Record** | Fill in an optional title, project, attendees and minutes format, then press the red button. A live transcript with speaker labels appears while you record: words show up about a second after they're spoken, in a lighter tone until the speaker pauses, with the timer and **Stop & process** on a floating bar at the bottom. **Stop & process** runs the full pipeline. On **Who said what?** you confirm each voice (▶ plays a sample), and new names are remembered for next time. If you give two voices the same name, you're told they'll be merged into one person. You can also drop in an existing recording instead. |
| **Meetings** | Search and filter by project. Each meeting shows the notes, a searchable transcript, its action items, speaking time, decisions, **Open in Obsidian**, and **Rewrite**, which redoes the minutes in another format or with extra instructions. A player bar plays the recording: the transcript follows along, clicking a turn or a timestamp in the notes plays from that moment, and you can drag the scrubber or use the arrow keys. |
| **People** | Everyone whose voice is known, with role, organisation and bio. These are used as LLM context and saved in `People/` in your vault. You can also rename a person or forget their voice. |
| **Projects** | Project folders from your vault, with their meetings. |
| **Settings** | Model and LLM status, vault location, minutes formats. |

Action items are the Obsidian Tasks lines in your notes. Ticking one in the dashboard updates
the note, and ticking it in Obsidian shows up in the dashboard. Every change offers **Undo** for
a few seconds, so only actions that can't be undone, like forgetting a voice or discarding a
recording, ask for confirmation.

The interface follows your system settings: light or dark appearance (the button in the top
right cycles through them), **Reduce motion** (animations become instant cross-fades),
**Reduce transparency** (translucent bars become solid) and **Increase contrast**.

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
date: 2026-10-07T10:00
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
