"""Fail clearly at GPU deployment startup; never silently run on CPU."""

from __future__ import annotations

import ctypes
import sys

from dzomdu.config import load_config


def check() -> str:
    import ctranslate2
    import torch

    if not torch.cuda.is_available() or ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError(
            "No NVIDIA GPU is accessible. Check the Linux NVIDIA driver and Container Toolkit, "
            "and start with both docker-compose.yml and docker-compose.gpu.yml."
        )
    # CTranslate2 uses system libraries, separately from PyTorch's bundled CUDA runtime.
    ctypes.CDLL("libcublas.so.12")
    ctypes.CDLL("libcudnn.so.9")
    torch.ones(1, device="cuda").sum().item()  # verify an actual kernel, not just enumeration
    cfg = load_config()
    if cfg.asr.backend in ("parakeet", "mlx-whisper", "mlx-audio") or (
        cfg.diarization.backend == "nemotron-mlx"
    ):
        raise RuntimeError(
            "This configuration selects an Apple Silicon model. Use faster-whisper and "
            "Pyannote on Linux; see DOCKER.md for migrating from a Mac."
        )
    supported = ctranslate2.get_supported_compute_types("cuda")
    if cfg.asr.backend == "faster-whisper" and cfg.asr.compute_type != "auto" and (
        cfg.asr.compute_type not in supported
    ):
        raise RuntimeError(
            f"ASR compute type {cfg.asr.compute_type!r} is not supported by this GPU. "
            f"Set DZOMDU_ASR_COMPUTE_TYPE to one of: {', '.join(sorted(supported))}."
        )
    return f"NVIDIA GPU ready: {torch.cuda.get_device_name(0)}"


if __name__ == "__main__":
    try:
        print(check(), flush=True)
    except (RuntimeError, OSError, ImportError) as exc:
        print(f"GPU deployment cannot start: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
