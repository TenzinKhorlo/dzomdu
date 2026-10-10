"""Speaker diarization ("who spoke when") and speaker embeddings ("whose voice is this")."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

import numpy as np

from ..audio import Audio
from ..config import DiarizationConfig
from ..models import SpeakerSegment


class Diarizer(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifies the embedding space. Voiceprints from different ids are not comparable."""

    @property
    def embedding_id(self) -> str:
        """Identity of the voice embedding model, independent of speaker segmentation."""
        return self.model_id

    @abstractmethod
    def diarize(
        self,
        audio: Audio,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[SpeakerSegment]:
        """Return non-overlapping ("exclusive") speaker segments sorted by start time."""

    @abstractmethod
    def embed(self, waveforms: list[np.ndarray], sample_rate: int) -> np.ndarray:
        """Return one L2-normalised embedding per waveform, shape (n, dim). Rows may be NaN
        when a waveform is too short to embed."""


def _pyannote(cfg: DiarizationConfig) -> Diarizer:
    from .pyannote import PyannoteDiarizer

    return PyannoteDiarizer(model=cfg.model, device=cfg.device, token_env=cfg.hf_token_env)


def _nemotron(cfg: DiarizationConfig) -> Diarizer:
    from .nemotron import NemotronDiarizer

    return NemotronDiarizer(cfg)


BACKENDS: dict[str, Callable[[DiarizationConfig], Diarizer]] = {
    "pyannote": _pyannote,
    "nemotron-mlx": _nemotron,
}


def get_diarizer(cfg: DiarizationConfig) -> Diarizer:
    try:
        factory = BACKENDS[cfg.backend]
    except KeyError:
        raise ValueError(
            f"Unknown diarization backend {cfg.backend!r}. Available: {', '.join(BACKENDS)}"
        ) from None
    return factory(cfg)


def l2_normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return x / norms
