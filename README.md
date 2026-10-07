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

## Install (Apple Silicon Mac)

**Step-by-step guide: [SETUP.md](SETUP.md)**. It installs everything into a Python virtual
environment (`.venv`), not globally. In short:

```bash
brew install python@3.12 ffmpeg git ollama
git clone https://github.com/TenzinKhorlo/dzomdu.git && cd dzomdu
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[mac,diarize]"
hf auth login                  # after accepting the pyannote model terms on Hugging Face
ollama pull qwen3:14b
dzomdu init --vault ~/Documents/DzomduVault
dzomdu doctor
```

## Use: web interface

```bash
dzomdu ui          # opens http://localhost:8765 in your browser
```

1. **New meeting**: optionally fill in a title, project, attendees and minutes format,
   then press **Start recording**. Allow microphone access when the browser asks.
   Attendees narrow voice matching to those people.
2. While you record, a **live transcript** appears with provisional speaker labels. It is a
   preview only.
3. Press **Stop**. The whole recording is processed properly: speaker separation,
   transcription and voice matching.
4. **Who said what?** Each speaker is shown with quotes and a **▶ Play voice** button.
   Recognised people are already filled in. Type names for new voices; they are remembered
   for next time.
5. **Notes**: the summary, decisions, action items and minutes are shown with clickable
   timestamps that jump to the transcript. Use **Rewrite these notes in another format** to
   pick a different template or add instructions. Use **Open in Obsidian** to open the
   saved note.

You can also **upload a recording** instead of recording live. **Meetings** lists past
notes, and **Voices** lets you rename or forget remembered voices.

The audio is saved continuously while recording. If the app or the computer crashes, the
recording is recovered the next time `dzomdu ui` starts. The UI runs only on this computer:
it listens on localhost, and nothing is loaded from the internet.

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
