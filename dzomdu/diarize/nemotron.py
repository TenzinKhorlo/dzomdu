"""Experimental eight-slot diarization on MLX; reuses the existing Pyannote voiceprints."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..audio import Audio
from ..config import DiarizationConfig
from ..models import SpeakerSegment
from . import Diarizer
from .pyannote import PyannoteDiarizer


class NemotronDiarizer(Diarizer):
    name = "nemotron-mlx"

    def __init__(self, cfg: DiarizationConfig):
        self.cfg = cfg
        self._model: Any = None
        self.voice = PyannoteDiarizer(device=cfg.device, token_env=cfg.hf_token_env)

    @property
    def model_id(self) -> str:
        return f"nemotron-mlx:{self.cfg.model}"

    @property
    def embedding_id(self) -> str:
        return self.voice.embedding_id

    def diarize(self, audio: Audio, num_speakers=None, min_speakers=None, max_speakers=None):
        if any(n is not None and n > 8 for n in (num_speakers, min_speakers, max_speakers)):
            raise ValueError("Nemotron supports at most 8 speakers. Use Pyannote for 15+ people.")
        if self._model is None:
            from mlx_audio.vad import load

            self._model = load(self.cfg.model, strict=True)
        result = self._model.generate(audio.samples, sample_rate=audio.sample_rate)
        # The application's alignment contract is exclusive. Choose the strongest active
        # voice per frame, rather than assigning overlapping segments arbitrarily.
        probs = np.asarray(result.speaker_probs)
        if not len(probs):
            return []
        limit = num_speakers or max_speakers or 8
        if limit < probs.shape[1]:
            activity = np.where(probs >= 0.5, probs, 0.0).sum(axis=0)
            keep = np.argsort(activity)[-limit:]
            probs = np.where(np.isin(np.arange(probs.shape[1]), keep), probs, 0.0)
        labels = probs.argmax(axis=1)
        labels[probs.max(axis=1) < 0.5] = -1
        # Nemotron emits one frame every 10 ms.
        boundaries = np.flatnonzero(np.r_[True, labels[1:] != labels[:-1], True])
        return [
            SpeakerSegment(
                start=float(a * 0.01),
                end=min(float(b * 0.01), audio.duration),
                speaker=f"SPEAKER_{int(labels[a]):02d}",
            )
            for a, b in zip(boundaries[:-1], boundaries[1:], strict=True)
            if labels[a] >= 0 and a * 0.01 < audio.duration
        ]

    def embed(self, waveforms: list[np.ndarray], sample_rate: int) -> np.ndarray:
        return self.voice.embed(waveforms, sample_rate)
