# syntax=docker/dockerfile:1
ARG RUNTIME_IMAGE=python:3.12-slim-bookworm

# ---- 1. build the web dashboard (static files) -----------------------------------------
FROM node:22-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build -- --webpack

# ---- 2. the app -------------------------------------------------------------------------
FROM ${RUNTIME_IMAGE}

# ffmpeg decodes uploaded audio and video, libsndfile reads WAV files
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 python3-venv ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Ubuntu CUDA images have Python 3.12 via apt; the CPU image already includes it.
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app

# PyTorch for CPU only: the default wheel pulls in several GB of CUDA libraries.
# docker-compose.gpu.yml pairs CUDA PyTorch with CUDA 12 + cuDNN 9 runtime libraries.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
COPY docker/constraints.txt /app/docker/constraints.txt
RUN pip install --no-cache-dir -c /app/docker/constraints.txt torch torchaudio --index-url ${TORCH_INDEX} \
 && pip install --no-cache-dir -c /app/docker/constraints.txt torchcodec --index-url https://download.pytorch.org/whl/cpu

# Python extras: diarize = speaker recognition (pyannote), whisper = speech to text.
# The Mac-only speech models (parakeet, mlx-whisper) are not installed: they need Apple Silicon.
ARG EXTRAS=diarize,whisper,denoise,moonshine
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY dzomdu ./dzomdu
RUN pip install --no-cache-dir -c /app/docker/constraints.txt ".[${EXTRAS}]" \
 && pip check

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
