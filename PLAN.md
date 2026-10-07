# Dzomdu — Offline Meeting Notetaker: Project Plan

> *Dzomdu* (འཛོམས་འདུ།): a meeting / gathering.
> Status: planning · Last updated: 2026-10-07

## 1. Goal

A private, **fully offline, open-source-only** meeting notetaker for in-person (room) meetings that:

1. **Recognises speakers** and remembers them across meetings (voiceprints).
2. Keeps a **profile/bio** per person (role, organisation, what they do).
3. **Transcribes** the meeting **turn by turn, attributed to each speaker** (live during the meeting, refined afterwards).
4. Produces **minutes in a customisable format** plus a **summary** using a local LLM.
5. Stores **project knowledge** (PDFs, presentations, docs) next to the meeting notes.
6. Saves everything as **plain Markdown** that opens directly in **Obsidian** (and imports into Notion or anything else).

Works for one person taking notes on a Mac, and later grows into a shared organisational system.

### Decisions so far

| Topic | Decision |
|---|---|
| Language | **English first**. The ASR layer is pluggable so **Dzongkha** can be added later. |
| Deployment | **Local-first** (a single Mac). **On-prem org server** comes later. |
| Hardware | **Apple Silicon Mac** (MLX / Core ML / Metal). Linux + NVIDIA comes with the server phase. |
| Audio capture | Laptop/phone mic, conference speakerphone, uploaded recordings, **plus live on-screen transcript**. |
| Online meetings | Later phase. |

---

## 2. Research summary: chosen open-source components

### 2.1 Speaker diarization + recognition ("who spoke when" + "who is that")

| Option | Notes | Verdict |
|---|---|---|
| **pyannote.audio 4 + `speaker-diarization-community-1`** | Best open-source diarization at the moment. Big drop in speaker confusion compared with 3.1. Language-agnostic. Uses WeSpeaker embeddings, which we reuse for identification. Runs offline. Code is MIT; the model is CC-BY-4.0. Downloading it once needs a free Hugging Face account and accepting the model terms. | **Primary** |
| WeSpeaker ResNet34 (ONNX, Apache-2.0) / SpeechBrain ECAPA-TDNN | Standalone speaker-embedding models for voiceprints. | Embedding model (via pyannote), with ECAPA as fallback |
| Core ML ports of community-1 (FluidAudio, speakrs) | Hundreds of times faster than real time on Apple Silicon (Neural Engine). | **Later optimisation** on the Mac |
| NVIDIA NeMo Sortformer | Strong, but built around CUDA. | Server phase option |

**How recognition works:** diarization gives anonymous clusters (`SPEAKER_00`, `SPEAKER_01`, …). For each cluster we compute an embedding (the average over its clean, non-overlapping speech). We then compare it by cosine similarity against the **voiceprint library** of known people:

- above the high threshold → auto-label with the name;
- between the high and low thresholds → *suggest* the name and ask the user to confirm;
- below the low threshold → "Unknown speaker N". The user names them once, and from then on that person is recognised in future meetings.

The same tool (pyannote) does both diarization and recognition. Transcription needs a separate ASR model; no single open-source tool currently does all three well.

### 2.2 Speech-to-text (ASR)

| Model | Why | Role |
|---|---|---|
| **NVIDIA Parakeet TDT 0.6B v2** (English) via **`parakeet-mlx`** | Top-tier English accuracy. Native punctuation and casing. **Word-level timestamps**, which we need to align words with speakers. Streaming API. About 1 hour of audio in roughly 1 minute on Apple Silicon. CC-BY-4.0. | **Primary (Mac)** |
| Whisper large-v3-turbo via `mlx-whisper` / `whisper.cpp` | 99 languages. Supports an "initial prompt" for vocabulary hints. | **Fallback** and for multilingual audio |
| Qwen3-ASR 1.7B / 0.6B (+ Qwen3-ForcedAligner) | Apache-2.0, 52 languages/dialects, strong accuracy. | Evaluate in Phase 0 |
| Cohere Transcribe (2B) | Currently #1 on the Open ASR Leaderboard, but only 14 languages. | Evaluate if accuracy matters most |
| **Meta MMS-1B-all + Dzongkha adapter** | The only realistic open-source route to Dzongkha today. Published fine-tunes report about 37% WER, so not production-ready yet. | **Future Dzongkha plug-in** (Phase 5) |

### 2.3 Summaries and minutes (local LLM)

- **Runtime:** **Ollama** (or `mlx-lm` / LM Studio). Every backend is called through an **OpenAI-compatible HTTP API**, so models and runtimes can be swapped without code changes, including a GPU server later.
- **Target machine: 24 GB Apple Silicon Mac.** Memory budget per stage (the stages run one after another, so their peaks don't add up):

  | Stage | Approx. memory |
  |---|---|
  | macOS + browser + app | 6–8 GB |
  | Live mode: Parakeet + VAD + speaker embeddings | ~2–3 GB |
  | After the meeting: diarization + full transcription | ~2–4 GB (unloaded afterwards) |
  | LLM: 14B-class model at 4-bit (e.g. Qwen3-14B) | ~9 GB + ~1–3 GB working memory for a 1-hour transcript |
  | LLM alternative: gpt-oss-20b | ~13 GB + working memory (tighter) |
  | Docling (only while importing documents) | ~1–2 GB |

  - **Default LLM:** a 14B-class model at 4-bit, with an 8B-class model as the fast option. 30B-class models (~17–18 GB) are **not recommended** on 24 GB. Final pick comes from the Phase 0 benchmark.
  - **Settings:**
    - context window of about 16k tokens, with map-reduce for longer meetings;
    - Ollama `OLLAMA_KV_CACHE_TYPE=q8_0` with flash attention, to halve the working memory;
    - unload models between stages (Ollama `keep_alive`).
  - macOS only lets the GPU use about two thirds of memory by default (~16 GB here). If a model doesn't fit, raise it with `sudo sysctl iogpu.wired_limit_mb=18432`.
  - Expected time for an LLM summary of a 1-hour meeting: about 1–3 minutes, depending on the chip.
- **Embeddings for search/RAG:** `bge-m3` or `nomic-embed-text` (via Ollama).

### 2.4 Project documents

- **Docling** (IBM, MIT): PDF / PPTX / DOCX / XLSX / HTML → clean Markdown, including tables and layout. Converted docs go into the vault next to the original file.
- **Vector index:** `sqlite-vec` (a single file, no server). LanceDB is the alternative.

### 2.5 Supporting pieces

- **Silero VAD** (MIT): voice activity detection for live chunking and trimming silence.
- **ffmpeg**: decodes any uploaded audio/video format.
- Prior art reviewed for ideas: Meetily, HushNote, MeetMind, Minutes, Obsidian *Voice MD*. None of them combines **persistent cross-meeting speaker identity + people bios + project document context**. That combination is what sets Dzomdu apart.

---

## 3. Architecture

```
┌──────────────────────────── Mac (local mode) ─────────────────────────────┐
│                                                                           │
│  Web UI (SvelteKit/React)  ── later wrapped as a Mac app with Tauri       │
│   • Record / Live view • Review speakers • People • Projects • Templates  │
│        │  WebSocket (16 kHz PCM audio, live transcript)  │  REST          │
│        ▼                                                 ▼                │
│  Dzomdu Core (Python 3.12, FastAPI)                                        │
│   ├─ audio/      capture, VAD, storage (FLAC/Opus), ffmpeg import         │
│   ├─ asr/        ASR interface → ParakeetMLX | Whisper | Qwen3 | MMS-dz   │
│   ├─ diarize/    pyannote community-1 (MPS/CPU) → Core ML later           │
│   ├─ speakers/   voiceprint library, matching, enrolment, feedback loop   │
│   ├─ align/      words ↔ speaker turns, merging, overlap handling         │
│   ├─ llm/        OpenAI-compatible client → Ollama / mlx-lm / server      │
│   ├─ notes/      templates, minutes, summary, action items → Markdown     │
│   ├─ docs/       Docling ingestion, chunking, embeddings, RAG             │
│   └─ vault/      Markdown writer + file watcher (re-index Obsidian edits) │
│        │                                   │                              │
│        ▼                                   ▼                              │
│  Markdown Vault (source of truth       App data (.dzomdu/)                │
│  for human-readable content)           SQLite + sqlite-vec: segments,     │
│                                        voiceprints, doc chunks, jobs      │
└───────────────────────────────────────────────────────────────────────────┘
```

**Why Python + a web UI:** the whole ML ecosystem we need (pyannote, parakeet-mlx, Docling, MMS for Dzongkha) is Python. A localhost web UI on top of a FastAPI backend becomes the **multi-user server** later with almost no rewrite: browsers record and stream audio to the server instead of to localhost. Tauri can package it as a native Mac app (menu-bar record button, mic permissions) once the core is stable.

### 3.1 Processing pipeline (two-pass)

**Pass 1: live, during the meeting** (low latency, may be slightly wrong)
1. Mic audio → 16 kHz mono PCM → saved continuously to disk, so nothing is lost if the app crashes.
2. Silero VAD cuts the audio into utterances → streaming Parakeet → text appears on screen within about 1–2 s.
3. **Provisional speaker label** per utterance: compute an embedding and match it against the **attendees picked before the meeting starts**. A small closed set is much more accurate than searching everyone. Voices that don't match go to an "unknown" bucket.

**Pass 2: refinement, right after "Stop"** (accurate, takes about 1–3 min for a 1-hour meeting on an M-series Mac)
1. Full-file **pyannote community-1** diarization (exclusive mode, one speaker at a time, so turns align cleanly).
2. Full-file **Parakeet** transcription with word timestamps.
3. **Alignment:** each word goes to the speaker segment it overlaps most. Consecutive words become **turns**.
4. **Identification:** each cluster's embedding is matched against the voiceprint library (auto / suggest / unknown, as described above).
5. **Review screen:** for each speaker, play a 5-second sample and confirm or rename them. Confirmations **update that person's voiceprint**.
6. **LLM step** (see §5): summary, minutes in the chosen template, decisions, action items.
7. Write the Markdown note to the vault and link it to the project and to each person.

Uploaded recordings skip Pass 1 and go straight to Pass 2.

---

## 4. Speaker memory design

- **Person** = Markdown file `People/<Name>.md` (bio, role, organisation, team, email, notes). It's human-editable in Obsidian and auto-linked from every meeting the person attends.
- **Voiceprint** = stored in SQLite, **not** in Markdown (binary, sensitive):
  - several embeddings per person, taken from different meetings, rooms and mics, capped at around 20 using a diversity rule;
  - a centroid plus per-embedding matching, scored by the best match or top-k average;
  - **the reference audio clips are kept** (short, 5–10 s each). Then if we upgrade the embedding model, everyone can be re-embedded without re-enrolling.
  - the embedding model name/version is stored with each vector, because vectors from different models are not comparable.
- **Enrolment paths:**
  1. **Implicit:** name an "Unknown speaker" after a meeting.
  2. **Explicit:** a "Record voice sample" button, 20–30 s of natural speech.
- **Thresholds:** start from the literature defaults, then **calibrate on our own recordings** in Phase 0 (laptop mic vs speakerphone behave differently). Thresholds can be configured per device profile.
- **Feedback loop:** every confirmation or correction is logged and used to re-tune thresholds and improve voiceprints over time.
- **Privacy:** voiceprints are biometric data. We need a consent flag per person, a one-click "forget this voice" that deletes embeddings and clips, encryption at rest (later), and voiceprint files must never be written into the shared vault.

---

## 5. Notes, minutes and templates

### 5.1 Two-step generation (reliability)

1. **Extract** structured data from the transcript with the LLM, constrained to a JSON schema. Each item cites **turn IDs / timestamps** so it can be checked against the transcript:
   `summary`, `topics[]`, `decisions[]`, `action_items[] {task, owner, due, source_turns}`, `open_questions[]`, `risks[]`, `next_meeting`.
2. **Render** that data through a **template**. The template decides the layout, so formatting can't drift between meetings.

Long meetings use **map-reduce**: chunk the transcript by time/topic → extract per chunk → merge. The LLM prompt also gets **context**: attendee bios (role-aware summaries), the project overview, a glossary, and relevant snippets from project documents (RAG). This fixes names and jargon.

### 5.2 Customisable formats

- Templates live in the vault (`Templates/Minutes/*.md`). Each is a Markdown file with placeholders plus a short natural-language instruction block, for example *"Formal board-meeting style, third person, group action items by owner."*
- Built-in templates: **Standard minutes**, **Executive summary**, **Board/committee minutes** (attendance, agenda items, resolutions), **Stand-up**, **Project review**, **1:1**.
- "Regenerate with…" box: a free-text request ("make it shorter, in bullet points for the director") can be **saved as a new template**.
- A project can set its own default template.

### 5.3 Vault layout (Obsidian-compatible)

```
DzomduVault/
├── Projects/
│   └── Solar Microgrid/
│       ├── Solar Microgrid.md                ← project overview (goals, team, status)
│       ├── Meetings/
│       │   └── 2026-10-07 Kickoff.md
│       └── Documents/
│           ├── Feasibility Study.md          ← Docling conversion
│           └── _files/Feasibility Study.pdf  ← original
├── People/
│   └── Tenzin Dorji.md
├── Meetings/                                 ← meetings with no project
├── Templates/Minutes/Standard.md
└── _audio/ (optional, configurable retention)
```

### 5.4 Meeting note format

```markdown
---
type: meeting
title: Kickoff
date: 2026-10-07T10:00
duration: 52m
project: "[[Solar Microgrid]]"
attendees: ["[[Tenzin Dorji]]", "[[Karma Wangmo]]"]
template: standard
audio: _audio/2026-10-07-kickoff.opus
tags: [meeting, solar-microgrid]
---
## Summary
…
## Decisions
- Proceed with site survey in Punakha ([00:14:32](#t-0142))
## Action items
- [ ] [[Karma Wangmo]] Draft budget by 2026-10-14 📅 2026-10-14
## Minutes
…(rendered from template)…
## Transcript
**[[Tenzin Dorji]]** `00:00:05` — Good morning everyone, let's start with…
**[[Karma Wangmo]]** `00:00:21` — Thanks. First item is…
```

YAML frontmatter works with Obsidian **Dataview/Bases**. Action items follow the **Obsidian Tasks** format. Notion imports Markdown directly, and a Notion API sync can be added later.

---

## 6. Phased roadmap

### Phase 0: Validation spike (1–2 weeks)
- Record **5–10 real meetings** with consent, including laptop mic, speakerphone, 2–8 people, and some crosstalk. Hand-label who spoke when for 2–3 of them.
- Benchmark on our own audio:
  - ASR: Parakeet v2 vs Whisper-turbo vs Qwen3-ASR, measured by WER and speed;
  - diarization error rate (DER) for community-1;
  - speaker-ID accuracy and thresholds;
  - 2–3 local LLMs for summaries, judged blind.
- **Deliverable:** a CLI, `dzomdu process meeting.wav --project X` → Markdown note, and a short benchmark report that fixes the model choices.

### Phase 1: Core engine + vault (2–3 weeks)
- The Pass 2 pipeline end to end as a library plus CLI: import → diarize → transcribe → align → identify → summarise → write Markdown.
- The voiceprint library (SQLite), enrolment, matching, and People notes.
- Templates v1 and the JSON-schema extraction.
- Tests on a fixed golden audio set (regression for WER/DER/ID accuracy).

### Phase 2: Local web app (3–4 weeks)
- Record from the mic in the browser, crash-safe audio storage, upload files.
- **Speaker review UI** (play sample → confirm/rename/merge/split), editing People and Projects, attendee pre-selection.
- Template picker and "regenerate with instructions".
- Background job queue with progress, and loading models sequentially so ASR and the LLM fit in RAM together.

### Phase 3: Live transcription (2–3 weeks)
- Streaming VAD + Parakeet over WebSocket, provisional speaker labels, then automatic Pass 2 refinement on stop.
- Live bookmarks ("mark decision", "mark action") that the LLM step uses.
- Optional Core ML diarization/embeddings (FluidAudio/speakrs-style) to free the GPU for the LLM.

### Phase 4: Project knowledge (2–3 weeks)
- Docling ingestion of PDF/PPTX/DOCX into the project's `Documents/`, with chunking and embeddings in sqlite-vec.
- RAG context in summaries, plus an auto-built **project glossary** (names, acronyms) to fix transcription errors.
- **Ask across meetings:** "What did we decide about the budget?" Answers cite the meeting notes and timestamps.
- Watch the vault for edits made in Obsidian and re-index.

### Phase 5: Organisation & extensions (later)
- **Server mode:** Linux + NVIDIA backend (faster-whisper / NeMo Parakeet / Sortformer on CUDA, vLLM for the LLM), multi-user login, roles and permissions per project, a shared voiceprint library, Postgres + pgvector, and audit logs. Mac clients become thin recorders.
- **Dzongkha:** an MMS-1B-all Dzongkha adapter (or our own fine-tune on in-house meeting data), language ID per segment for code-switching, and an LLM that can summarise Dzongkha (or translate first, then summarise).
- **Online meetings:** capture system audio (ScreenCaptureKit on macOS) plus the mic.
- Packaging (Tauri .app), Notion API sync, and calendar integration (auto-fill title and attendees).

---

## 7. Key risks & mitigations

| Risk | Mitigation |
|---|---|
| A single laptop mic in a big room → poor diarization and similar-sounding voices | Recommend a cheap omni speakerphone. Attendee pre-selection (closed set). Human review step. Per-device thresholds. |
| Overlapping speech / interruptions | Exclusive diarization for the transcript. Mark overlaps. Accept that some errors will be corrected in review. |
| Voice drift (colds, different mic) causes missed recognition | Keep several embeddings per person. Every confirmed meeting adds a new sample. |
| LLM invents decisions or action items | Two-step extraction with **citations to timestamps**. Low temperature. User edits before finalising. |
| RAM contention on the Mac (ASR + diarization + LLM) | Run the stages one after another, unload models between stages, and size the LLM to available RAM. |
| Gated model download (pyannote) | One-time download during setup, then the model is bundled in the local model cache. Fully offline after that. |
| Biometric/privacy obligations | Consent, deletion, local-only storage, and encryption in server mode. |
| Dzongkha ASR immaturity | Pluggable ASR interface from day one. Collect consented in-house data now for a future fine-tune. |

---

## 8. Proposed repository layout

```
dzomdu/
├── PLAN.md
├── pyproject.toml            (uv)
├── dzomdu/                   (Python core)
│   ├── audio/ asr/ diarize/ speakers/ align/ llm/ notes/ docs/ vault/
│   ├── api/                  (FastAPI routes + WebSocket)
│   └── cli.py
├── web/                      (SvelteKit or React UI)
├── templates/                (default minutes templates)
├── bench/                    (Phase 0 benchmark scripts + golden set manifest)
└── tests/
```

---

## 9. Open questions

1. ~~Mac RAM~~ → **24 GB** (see §2.3).
2. **Keep the audio** after processing, or delete it once the note is approved (privacy vs being able to re-process)?
3. **Consent policy** for storing colleagues' voiceprints: is a verbal OK enough, or does it need a written/recorded opt-in?
4. Typical **meeting size and length** (e.g. 4 people for 30 min, or 15 people for 3 hours)?
5. **Notion:** is a manual Markdown import enough, or do you want automatic sync via the API?
6. **Frontend preference:** SvelteKit (lighter) or React (bigger ecosystem)?
7. Do you already have a **Dzongkha speech dataset**, or links to the CST/GovTech Dzongkha NLP teams, for the later phase?
