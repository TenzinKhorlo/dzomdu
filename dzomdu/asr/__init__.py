"""Speech-to-text backends. Every backend returns a flat list of timestamped words."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from ..audio import Audio
from ..config import ASRConfig
from ..models import Word


class ASRBackend(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    def transcribe(self, audio: Audio) -> list[Word]: ...


def _parakeet(cfg: ASRConfig) -> ASRBackend:
    from .parakeet import ParakeetMLXBackend

    return ParakeetMLXBackend(model=cfg.model, chunk_duration=cfg.chunk_duration)


def _mlx_whisper(cfg: ASRConfig) -> ASRBackend:
    from .whisper import MLXWhisperBackend

    return MLXWhisperBackend(model=cfg.model, language=cfg.language)


def _faster_whisper(cfg: ASRConfig) -> ASRBackend:
    from .whisper import FasterWhisperBackend

    return FasterWhisperBackend(model=cfg.model, language=cfg.language)


# name -> factory. Tests and plug-ins (e.g. a future Dzongkha model) register here.
BACKENDS: dict[str, Callable[[ASRConfig], ASRBackend]] = {
    "parakeet": _parakeet,
    "mlx-whisper": _mlx_whisper,
    "faster-whisper": _faster_whisper,
}


def get_asr_backend(cfg: ASRConfig) -> ASRBackend:
    try:
        factory = BACKENDS[cfg.backend]
    except KeyError:
        raise ValueError(
            f"Unknown ASR backend {cfg.backend!r}. Available: {', '.join(BACKENDS)}"
        ) from None
    return factory(cfg)
