# syntax=docker/dockerfile:1

# ---- 1. build the web dashboard (static files) -----------------------------------------
FROM node:22-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- 2. the app -------------------------------------------------------------------------
FROM python:3.12-slim

# ffmpeg decodes uploaded audio and video, libsndfile reads WAV files
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch for CPU only: the default wheel pulls in several GB of CUDA libraries.
# Build with --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu126 for an NVIDIA GPU.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch torchaudio --index-url ${TORCH_INDEX}

# Python extras: diarize = speaker recognition (pyannote), whisper = speech to text.
# The Mac-only speech models (parakeet, mlx-whisper) are not installed: they need Apple Silicon.
ARG EXTRAS=diarize,whisper
COPY pyproject.toml README.md LICENSE ./
COPY dzomdu ./dzomdu
RUN pip install --no-cache-dir ".[${EXTRAS}]"

COPY --from=web /web/out /app/web
COPY docker /app/docker

# One directory per kind of data, writable by any user so `user:` in compose just works.
#   /config  config.toml          /vault   meeting notes (open in Obsidian)
#   /data    voiceprints, caches  /models  downloaded speech and speaker models
RUN mkdir -p /config /vault /data /models && chmod 777 /config /vault /data /models
ENV DZOMDU_WEB_DIR=/app/web \
    DZOMDU_CONFIG=/config/config.toml \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch \
    XDG_CACHE_HOME=/data/cache \
    HOME=/data/home \
    PYTHONUNBUFFERED=1

EXPOSE 8765
VOLUME ["/config", "/vault", "/data", "/models"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/settings', timeout=4)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["dzomdu", "ui", "--host", "0.0.0.0", "--port", "8765", "--no-open"]
