# Run Dzomdu with Docker

The quickest way to try Dzomdu on any computer (Mac, Windows, Linux). You need
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with the
Compose plugin) and enough free disk space for the image, model weights and recordings.
The CUDA image is larger than the CPU image.

## Quick start

```bash
git clone https://github.com/TenzinKhorlo/dzomdu.git && cd dzomdu
cp .env.example .env          # then open .env and fill in the two things below
docker compose up -d --build  # the first build takes several minutes
```

Open **http://localhost:8765**. Meeting notes appear in the `vault/` folder next to
`docker-compose.yml`; open that folder in Obsidian with *Open folder as vault*.

Two things to put in `.env`:

1. **`HF_TOKEN`** for the speaker-recognition model. Accept the terms at
   [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1),
   then create a *Read* token at <https://huggingface.co/settings/tokens>. It is only used for
   the first download.
2. **A language model** for the summaries. Pick one:

| Option | Set in `.env` | Notes |
|---|---|---|
| **Ollama Cloud** | `LLM_BASE_URL=https://ollama.com`<br>`LLM_MODEL=gpt-oss:120b`<br>`LLM_API_KEY=…` | Nothing to download. Transcripts are sent to Ollama. |
| **Ollama on your computer** (default) | nothing, or `LLM_MODEL=qwen3:14b` | Install [Ollama](https://ollama.com), run `ollama pull qwen3:14b`. On a Mac this uses the GPU. On Linux, start Ollama with `OLLAMA_HOST=0.0.0.0` so the container can reach it. |
| **Ollama in Docker** | `LLM_BASE_URL=http://ollama:11434` | `docker compose --profile local-llm up -d`, then `docker compose exec ollama ollama pull qwen3:14b`. CPU only, so slow. |

Model and language-model values are read **once**, when the config file is first created. After that, change the
language model, vault folder, minutes formats and summary instructions on the **Settings**
page in the app. The vault path you enter there is a path *inside the container*; leave it as
`/vault` and move the folder by changing the `./vault:/vault` line in `docker-compose.yml`.

## What runs where

| In the container | Kept in | Holds |
|---|---|---|
| `/vault` | `./vault` (a normal folder) | meeting notes, people, projects, formats |
| `/config` | Docker volume `dzomdu-config` | `config.toml` (includes any API key) |
| `/data` | Docker volume `dzomdu-data` | meeting records, voiceprints, saved conversations, recordings, caches |
| `/models` | Docker volume `dzomdu-models` | downloaded speech and speaker models |

Voiceprints and saved conversations use SQLite files in `/data`. Each installation keeps its
own persistent data volume; no separate database container is required.

Everything stays on your computer except what you send to a hosted language model.
The port is published on `127.0.0.1` only. The app has **no login**, so do not expose it to a
network without putting something in front of it that authenticates.

## Differences from the Mac install

- Docker runs Linux, so the Apple-only speech models (Parakeet, MLX Whisper) are not used.
  The container uses **Whisper Turbo through faster-whisper**, with English, Nepali and
  automatic language detection. The standard Compose configuration uses the CPU; the NVIDIA
  configuration below uses CUDA. Settings lists the Linux/Windows Turbo variant and marks
  Apple-only models as unavailable. The removed full Whisper large-v3 and Nemotron ASR
  models are not reintroduced.
- Docker on a Mac cannot use the Mac's GPU, so for speed on a Mac the
  [native install](SETUP.md) is better.
- Recording works from `http://localhost:8765` because browsers allow the microphone there.
  Recording an online meeting needs Chrome or Edge.

## Everyday commands

```bash
docker compose logs -f dzomdu     # watch what it is doing
docker compose restart dzomdu
docker compose down               # stop (your data is kept)
git pull && docker compose up -d --build    # update
docker compose down -v            # stop AND delete the config, voiceprints and models
```

To back up: copy `./vault`, and export the volumes
(`docker run --rm -v dzomdu_dzomdu-data:/d -v "$PWD":/b alpine tar czf /b/data.tgz -C /d .`).

To export saved notes and transcripts as a portable Open Knowledge Format v0.2 bundle:

```bash
docker compose exec dzomdu dzomdu export-okf /vault/exports/knowledge-2026-10-09
```

The result appears under `./vault/exports/knowledge-2026-10-09` on the host. Use a new folder name for each export. It includes linked Markdown documents and an index; recordings and voiceprints stay in the installation.

## NVIDIA GPU (Linux)

Use an x86_64 Linux host with an NVIDIA GPU, a driver compatible with CUDA 12.8, Docker Engine
with Compose, and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
Follow NVIDIA's installation instructions for your distribution, including configuring the
Docker runtime with `sudo nvidia-ctk runtime configure --runtime=docker` and restarting Docker.
Confirm that `nvidia-smi` works on the host before proceeding.

Build and start the GPU deployment from this repository:

```bash
cp .env.example .env  # fill in HF_TOKEN and your language-model connection
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs -f dzomdu
```

The override supplies CUDA 12.8 and cuDNN 9, matching CUDA-enabled PyTorch, and gives the
container GPU access using [Compose device reservations](https://docs.docker.com/compose/how-tos/gpu-support/).
[faster-whisper requires CUDA 12 cuBLAS and cuDNN 9](https://github.com/SYSTRAN/faster-whisper#gpu);
installing only a CUDA PyTorch wheel is insufficient. PyTorch, torchaudio and TorchCodec
versions are paired in `docker/constraints.txt`. Audio decoding and RNNoise run on CPU;
transcription, diarization and voice embeddings run on GPU. Live previews retain the same
utterance-based update behavior as the Mac installation.

On startup the GPU deployment checks PyTorch and CTranslate2 GPU visibility, the CUDA/cuDNN
libraries, and a real CUDA kernel. It stops with an explanation if these checks fail. To run
the checks again after installation:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec dzomdu python /app/docker/check_gpu.py
```

Hardware settings are reapplied at every container start: `DZOMDU_ASR_DEVICE=cuda`,
`DZOMDU_ASR_COMPUTE_TYPE=float16` and `DZOMDU_DIARIZATION_DEVICE=cuda`. This supports existing
CPU installations without replacing their saved models, vault, API keys or summary instructions.
For less transcription VRAM, set `DZOMDU_ASR_COMPUTE_TYPE=int8_float16` in `.env` and recreate
the service with the same `up -d` command. Only compute types supported by the GPU are accepted.
The app uses the first visible GPU; exposing several GPUs does not distribute one meeting
across them.

For a local LLM in the same deployment, set `LLM_BASE_URL=http://ollama:11434` in `.env`
before the first start, then:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile local-llm up -d --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec ollama ollama pull qwen3:14b
```

Ollama also receives GPU access. Its model shares GPU memory with transcription and Pyannote;
choose an LLM that fits alongside them. Existing installations can change the LLM URL in
Settings. A separate LLM server or a hosted endpoint also works.

The app remains bound to the server's loopback interface. From another computer, use a tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 user@your-linux-server
```

Open `http://localhost:8765` on your computer. This also allows microphone recording through
the browser's localhost secure-context exception. For access without a tunnel, use an HTTPS
reverse proxy with authentication; the app itself has no login. Keep its WebSocket connections
enabled for live audio and progress updates.

### Moving from the native Mac installation

Copy your vault into `./vault` while both installations are stopped, or export a portable
Open Knowledge Format bundle as described above. Start with a fresh app-data volume for the
Linux installation. Existing Mac databases can contain absolute paths to recordings, notes
and voice clips, so copying the app-data directory alone is not a complete migration. Keep
your Mac data backed up at `~/Library/Application Support/dzomdu`; the Docker deployment
does not move or delete it. Do not copy the Apple MLX model cache.
Start with a new Docker-generated `/config/config.toml`, then set your LLM and models in
Settings. A copied Mac config can select incompatible Parakeet, MLX Whisper, MLX Qwen or
Nemotron diarization models; the GPU startup check rejects these with migration guidance.
Use Whisper Turbo (CPU / CUDA) and Pyannote on Linux. Nemotron-3-Diarization remains available
for testing in the native Apple Silicon installation.

### Deployment validation

Both Compose configurations can be checked without starting any service:

```bash
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --quiet
```

The repository's `Linux containers` workflow builds CPU and CUDA images on Linux and tests
audio decoding, Python imports and native RNNoise processing without downloading model weights.
These smoke checks do not replace a real transcription test on the target GPU. A deployment's
first model download still needs network access and the Pyannote token/accepted terms.

## Troubleshooting

- **"Needs attention" on Speaker recognition:** `HF_TOKEN` is missing, or the model terms were
  not accepted with the same Hugging Face account. Fix `.env`, then
  `docker compose up -d --force-recreate`.
- **"Needs attention" on Summaries:** open Settings and use *Test connection*. For Ollama on
  the host, check it is running; on Linux it must listen on `0.0.0.0`.
- **First recording is slow to start:** the speech and speaker models download on first use
  and are then cached in the `dzomdu-models` volume. Use Settings → Model library to download
  them before starting a meeting.
- **GPU deployment cannot start:** check `nvidia-smi` and Container Toolkit configuration.
  A CPU-only PyTorch image or missing GPU reservation cannot run the GPU deployment. Use both
  Compose files consistently for build, start, restart, logs and exec commands.
- **CUDA out of memory:** use `int8_float16` for transcription, unload the local LLM or choose
  a smaller LLM. The application runs one meeting-processing worker per installation.
- **Permission errors on `./vault`:** set `user: "${UID}:${GID}"` on the `dzomdu` service
  (Linux), or make the folder writable for your user.
