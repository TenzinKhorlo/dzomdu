"""Write the first-run config for the Docker image from environment variables.

Only runs when no config file exists yet. After that the config lives in the /config volume and
is changed from the Settings page (or by editing the file), so restarts never overwrite it.
"""

from __future__ import annotations

import os
from pathlib import Path

from dzomdu.config import ASRConfig, Config, LLMConfig, save_config

env = os.environ.get


def main() -> None:
    path = Path(env("DZOMDU_CONFIG", "/config/config.toml"))
    if path.exists():
        return
    cfg = Config(
        vault=Path(env("DZOMDU_VAULT", "/vault")),
        data_dir=Path(env("DZOMDU_DATA_DIR", "/data")),
        asr=ASRConfig(
            # parakeet and mlx-whisper need an Apple Silicon Mac, so a Linux container uses
            # faster-whisper, which runs on any CPU (or an NVIDIA GPU)
            backend=env("DZOMDU_ASR_BACKEND", "faster-whisper"),
            model=env("DZOMDU_ASR_MODEL") or "small",
            language=env("DZOMDU_ASR_LANGUAGE", "en"),
        ),
        llm=LLMConfig(
            api=env("LLM_API", "ollama"),
            base_url=env("LLM_BASE_URL", "http://host.docker.internal:11434"),
            model=env("LLM_MODEL", "qwen3:14b"),
            api_key=env("LLM_API_KEY", ""),
        ),
    )
    save_config(cfg, path)
    print(f"Wrote first-run config to {path}")


if __name__ == "__main__":
    main()
