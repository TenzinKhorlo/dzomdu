# Run Dzomdu with Docker

The quickest way to try Dzomdu on any computer (Mac, Windows, Linux). You need
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with the
Compose plugin) and about 8 GB of free disk space.

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

These values are read **once**, when the config file is first created. After that, change the
language model, vault folder, minutes formats and summary instructions on the **Settings**
page in the app. The vault path you enter there is a path *inside the container*; leave it as
`/vault` and move the folder by changing the `./vault:/vault` line in `docker-compose.yml`.

## What runs where

| In the container | Kept in | Holds |
|---|---|---|
| `/vault` | `./vault` (a normal folder) | meeting notes, people, projects, formats |
| `/config` | Docker volume `dzomdu-config` | `config.toml` (includes any API key) |
| `/data` | Docker volume `dzomdu-data` | voiceprints, recordings, caches |
| `/models` | Docker volume `dzomdu-models` | downloaded speech and speaker models |

Everything stays on your computer except what you send to a hosted language model.
The port is published on `127.0.0.1` only. The app has **no login**, so do not expose it to a
network without putting something in front of it that authenticates.

## Differences from the Mac install

- Docker runs Linux, so the Apple-only speech models (Parakeet, MLX Whisper) are not used.
  The container uses **faster-whisper** on the CPU, which is slower. The default model is
  `small`; set `DZOMDU_ASR_MODEL=large-v3-turbo` in `.env` (before first start) for better
  accuracy if you have the CPU time and 8 GB+ of memory for Docker.
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

## NVIDIA GPU (Linux)

Build with CUDA PyTorch and give the container the GPU:

```bash
docker compose build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu126
```

and add to the `dzomdu` service in `docker-compose.yml`:

```yaml
    deploy:
      resources:
        reservations:
          devices: [{ driver: nvidia, count: all, capabilities: [gpu] }]
```

## Troubleshooting

- **"Needs attention" on Speaker recognition:** `HF_TOKEN` is missing, or the model terms were
  not accepted with the same Hugging Face account. Fix `.env`, then
  `docker compose up -d --force-recreate`.
- **"Needs attention" on Summaries:** open Settings and use *Test connection*. For Ollama on
  the host, check it is running; on Linux it must listen on `0.0.0.0`.
- **First recording is slow to start:** the speech and speaker models download on first use
  (about 1 GB) and are then cached in the `dzomdu-models` volume.
- **Permission errors on `./vault`:** set `user: "${UID}:${GID}"` on the `dzomdu` service
  (Linux), or make the folder writable for your user.
