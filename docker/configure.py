"""Write the first-run config for the Docker image from environment variables.

Model choices and personal settings are initialized once. Explicit deployment hardware
variables are applied at every start, so switching a CPU deployment to CUDA works with its
existing persistent configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

from dzomdu.config import ASRConfig, Config, LLMConfig, load_config, save_config

env = os.environ.get


def main() -> None:
    path = Path(env("DZOMDU_CONFIG", "/config/config.toml"))
    if path.exists():
        cfg = load_config(path)
        changed = False
        for section, key, variable in (
            (cfg.asr, "device", "DZOMDU_ASR_DEVICE"),
            (cfg.asr, "compute_type", "DZOMDU_ASR_COMPUTE_TYPE"),
            (cfg.diarization, "device", "DZOMDU_DIARIZATION_DEVICE"),
        ):
            if (value := env(variable)) and getattr(section, key) != value:
                setattr(section, key, value)
                changed = True
        cfg.asr.__post_init__()
        if changed:
            save_config(cfg, path)
        return
    cfg = Config(
        vault=Path(env("DZOMDU_VAULT", "/vault")),
        data_dir=Path(env("DZOMDU_DATA_DIR", "/data")),
        asr=ASRConfig(
            # parakeet and mlx-whisper need an Apple Silicon Mac, so a Linux container uses
            # faster-whisper, which runs on any CPU (or an NVIDIA GPU)
            backend=env("DZOMDU_ASR_BACKEND", "faster-whisper"),
            model=env("DZOMDU_ASR_MODEL") or "dropbox-dash/faster-whisper-large-v3-turbo",
            language=env("DZOMDU_ASR_LANGUAGE", "en"),
            device=env("DZOMDU_ASR_DEVICE", "auto"),
            compute_type=env("DZOMDU_ASR_COMPUTE_TYPE", "auto"),
        ),
        llm=LLMConfig(
            api=env("LLM_API", "ollama"),
            base_url=env("LLM_BASE_URL", "http://host.docker.internal:11434"),
            model=env("LLM_MODEL", "qwen3:14b"),
            api_key=env("LLM_API_KEY", ""),
        ),
    )
    cfg.diarization.device = env("DZOMDU_DIARIZATION_DEVICE", "auto")
    save_config(cfg, path)
    print(f"Wrote first-run config to {path}")


if __name__ == "__main__":
    main()
