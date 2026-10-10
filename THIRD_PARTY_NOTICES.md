# Third-party notices

Dzomdu itself is proprietary (see `LICENSE`). It uses the open-source software and AI models
below, each under its own licence. This file lists them and what each licence asks of you.

Licences were checked from package metadata and public model pages in October 2026. Where a
licence could not be confirmed it is marked **unverified**. Re-check before each release and
whenever you add a dependency or change a default model. This is a technical inventory, not
legal advice.

## AI models

Dzomdu's source does **not** include model weights. Speech recognition and diarization weights
are downloaded separately; the optional RNNoise runtime includes its pretrained model in the
installed native library. The publisher's licence applies in each case. If you bundle, pre-download
or host the weights for customers, you take on the attribution duties below.

| Model | Used for | Licence | What it asks |
| --- | --- | --- | --- |
| [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) (pyannote.ai, built from pyannote segmentation, WeSpeaker embeddings and VBx clustering) | Telling speakers apart, voiceprints | CC-BY-4.0 | Credit the authors and link the licence. Access is gated: each user accepts the model's conditions on Hugging Face and uses their own token. |
| NVIDIA Parakeet TDT 0.6B v2 (`mlx-community/parakeet-tdt-0.6b-v2`, MLX conversion of [nvidia/parakeet-tdt-0.6b-v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2)) | Default speech to text | CC-BY-4.0 (**unverified**: NVIDIA's NIM model card cites the NVIDIA Community Model License instead) | Credit NVIDIA and link the licence. Confirm the licence field on the Hugging Face page before shipping. |
| OpenAI Whisper large-v3-turbo (`mlx-community/whisper-large-v3-turbo`) and the `faster-whisper` models | Optional speech to text | MIT | Keep the copyright and licence notice. |
| Qwen3 14B (`qwen3:14b`) | Default local summaries | Apache-2.0 (**unverified**) | Keep the licence and notices if you redistribute it. |
| gpt-oss (`gpt-oss:120b`) | Suggested Ollama Cloud model | Apache-2.0 (**unverified**) | As above. |
| [RNNoise v0.2](https://github.com/xiph/rnnoise), bundled native model in `pyrnnoise==0.4.3` | Optional background noise suppression for transcription | [BSD-3-Clause](https://github.com/xiph/rnnoise/blob/main/COPYING) | Permits commercial use. Retain copyright, licence conditions and disclaimer when redistributing source or binaries; do not imply contributor endorsement. |

Suggested attribution wherever the app's credits or documentation are shown:

> Speaker separation uses the pyannote community-1 pipeline (CC-BY-4.0, pyannote.ai).
> Speech recognition uses NVIDIA Parakeet TDT 0.6B v2 (CC-BY-4.0) and OpenAI Whisper (MIT).

### Hosted language models

If a user points Dzomdu at **Ollama Cloud**, meeting transcripts are sent to Ollama. Its
[privacy policy](https://registry.ollama.ai/privacy) and [terms](https://registry.ollama.ai/terms)
apply to that use. Other OpenAI-compatible servers have their own terms. Dzomdu is otherwise
local, so describe the app as "offline" only when it is configured with a local model.

## Python dependencies

Installed from PyPI, not copied into this repository.

| Package | Licence |
| --- | --- |
| numpy | BSD-3-Clause (with bundled permissive parts: 0BSD, MIT, Zlib, CC0-1.0) |
| typer, rich, pyyaml, pydantic, fastapi | MIT |
| jinja2, markdown-it-py | BSD-3-Clause / MIT (per PyPI classifiers) |
| httpx, uvicorn, websockets | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| parakeet-mlx (optional `mac`) | Apache-2.0 |
| mlx-whisper, mlx (optional `mac`) | MIT |
| faster-whisper, ctranslate2 (optional `whisper`) | MIT |
| pyannote.audio (optional `diarize`) | MIT (**unverified**: no licence in its PyPI metadata) |
| torch (pulled in by pyannote) | BSD-style, with Apache-2.0 and MIT parts |
| scipy (optional `bench`, `denoise`) | BSD-3-Clause |
| [pyrnnoise](https://github.com/pengzhendong/pyrnnoise) (optional `denoise`) | Apache-2.0; bundled RNNoise library/model is BSD-3-Clause |
| huggingface-hub | Apache-2.0 |

The full transitive tree behind `uv.lock` has **not** been scanned. Run a licence report
(for example `pip-licenses`) in an environment with all extras installed before a release.

## Web interface dependencies

Direct dependencies of `web/`. They are bundled into the static build served by the app.

| Package | Licence |
| --- | --- |
| next, react, react-dom, radix-ui, @floating-ui/react, clsx, motion, next-themes, recharts, sonner, tailwind-merge, tw-animate-css | MIT |
| class-variance-authority | Apache-2.0 |
| lucide-react (icons) | ISC; parts derived from Feather are MIT |
| geist (Geist Sans and Geist Mono fonts) | SIL Open Font License 1.1, Copyright (c) 2023 Vercel, in collaboration with basement.studio |

Build-time tools (Tailwind CSS, TypeScript, ESLint) are not shipped. Of these, `lightningcss`
and `axe-core` are MPL-2.0 (file-level copyleft; no obligation when used unmodified as tools).
The optional `sharp` image libraries that Next.js can install are LGPL-3.0; they are not part
of the static build.

### Fonts

Geist is licensed under the SIL Open Font License 1.1. You may bundle and use it in a
commercial product. Keep its licence text with any copy of the font files you distribute
(`web/node_modules/geist/LICENSE.txt`), and do not sell the font files on their own.

### Copied component code

`web/src/components/ui/` and `web/src/components/animate-ui/` contain code copied into the
repository with the shadcn CLI from [shadcn/ui](https://ui.shadcn.com) and
[Animate UI](https://animate-ui.com). Both are published under the MIT licence. Keep their
copyright notices if you redistribute that source. The Animate UI licence was **not**
independently checked here.
