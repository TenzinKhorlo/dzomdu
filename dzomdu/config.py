"""Configuration: a single TOML file, with sensible defaults for an Apple Silicon Mac."""

from __future__ import annotations

import importlib.util
import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


def default_config_path() -> Path:
    if env := os.environ.get("DZOMDU_CONFIG"):
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "dzomdu" / "config.toml"


def default_data_dir() -> Path:
    """App data (voiceprints, caches) lives outside the vault so it is never synced or shared."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dzomdu"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "dzomdu"


@dataclass
class ASRConfig:
    # parakeet (Apple Silicon, English) | mlx-whisper (Apple Silicon) | faster-whisper (CPU/CUDA)
    backend: str = "parakeet"
    model: str | None = None  # None = the backend's default model
    language: str = "en"
    chunk_duration: float = 120.0  # seconds; long files are transcribed in overlapping chunks
    # Re-transcribe stretches where speech was detected but the full pass returned no words
    # (speech engines sometimes drop the last sentence of a recording, or a short reply).
    recover_missing: bool = True


@dataclass
class DiarizationConfig:
    backend: str = "pyannote"
    model: str = "pyannote/speaker-diarization-community-1"
    device: str = "auto"  # auto | mps | cuda | cpu
    hf_token_env: str = "HF_TOKEN"  # only needed for the one-time model download


@dataclass
class SpeakerConfig:
    # Cosine-similarity thresholds. These are starting points: calibrate them on your own
    # recordings with `dzomdu bench speaker-id` (Phase 0).
    accept_threshold: float = 0.60  # >= this: labelled automatically
    suggest_threshold: float = 0.45  # >= this: suggested, asks for confirmation
    max_embeddings_per_speaker: int = 20
    min_segment_duration: float = 1.5  # shorter segments make unreliable embeddings
    max_segments_per_cluster: int = 12
    clip_duration: float = 8.0  # length of the reference clip kept per confirmed sample
    # Split a diarization cluster when short windows of it clearly hold different voices
    # (two similar voices merged into one speaker). See dzomdu/speakers/refine.py.
    split_mixed_clusters: bool = True
    same_voice_threshold: float = 0.50  # windows/voices at least this similar are one person
    min_voice_seconds: float = 3.0  # speech a voice needs before a cluster is split for it


@dataclass
class LLMConfig:
    # "ollama" uses Ollama's native API (lets us set the context window, which the
    # OpenAI-compatible endpoint cannot). "openai" works with mlx-lm, LM Studio, vLLM, etc.
    api: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:14b"
    api_key: str = ""
    temperature: float = 0.2
    num_ctx: int = 16384
    max_chunk_tokens: int = 6000  # transcript tokens per map-reduce chunk
    timeout: float = 900.0
    keep_alive: str = "2m"
    think: bool | None = False  # disable "thinking" on reasoning models; None = don't send


@dataclass
class Config:
    vault: Path = field(default_factory=lambda: Path.home() / "DzomduVault")
    data_dir: Path = field(default_factory=default_data_dir)
    default_template: str = "standard"
    asr: ASRConfig = field(default_factory=ASRConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    speakers: SpeakerConfig = field(default_factory=SpeakerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "dzomdu.sqlite"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def clips_dir(self) -> Path:
        return self.data_dir / "voiceprints"

    @property
    def meetings_dir(self) -> Path:
        return self.data_dir / "meetings"


_SECTIONS = {
    "asr": ASRConfig,
    "diarization": DiarizationConfig,
    "speakers": SpeakerConfig,
    "llm": LLMConfig,
}


def _build(cls: type, data: dict[str, Any]) -> Any:
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} option(s): {', '.join(sorted(unknown))}")
    return cls(**data)


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.exists():
        return Config()
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _SECTIONS:
            kwargs[key] = _build(_SECTIONS[key], value)
        elif key in ("vault", "data_dir"):
            kwargs[key] = Path(value).expanduser()
        elif key == "default_template":
            kwargs[key] = value
        else:
            raise ValueError(f"Unknown config key: {key}")
    return Config(**kwargs)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_config(cfg: Config) -> str:
    lines = [
        "# Dzomdu configuration",
        f"vault = {_toml_value(cfg.vault)}",
        f"data_dir = {_toml_value(cfg.data_dir)}",
        f"default_template = {_toml_value(cfg.default_template)}",
    ]
    for name in _SECTIONS:
        lines += ["", f"[{name}]"]
        for key, value in asdict(getattr(cfg, name)).items():
            if value is None:
                lines.append(f"# {key} = ")
            else:
                lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def is_installed(module: str) -> bool:
    """True if `module` can be imported (find_spec raises when a parent package is missing)."""
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


ASR_PACKAGES = {
    "parakeet": "parakeet_mlx",
    "mlx-whisper": "mlx_whisper",
    "faster-whisper": "faster_whisper",
}
