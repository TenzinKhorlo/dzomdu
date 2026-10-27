"""Cactus Whistle on the CPU via cactus-needle (English and six European languages)."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np

from ..audio import SAMPLE_RATE, Audio
from ..config import ASRConfig
from ..models import Word
from . import ASRBackend

# Dzomdu works offline, so cactus-needle's usage counts stay off unless the user enables them.
os.environ.setdefault("NEEDLE_TELEMETRY", "0")

REPO = "Cactus-Compute/whistle"
# The engine holds one model per process and is not thread-safe (live preview and the final
# transcript can overlap).
_lock = threading.Lock()


def download() -> list[Path]:
    """Fetch the weights and the shared Needle engine into cactus-needle's cache."""
    import needle
    from needle.agent import fetch

    return [Path(fetch.fetch_weights(fetch.WHISTLE)), Path(needle._library_path(3))]


class WhistleBackend(ASRBackend):
    name = "whistle"

    def __init__(self, cfg: ASRConfig):
        # `model` is the library repo (the published weights) or a path to a tuned .cact file.
        self.weights = None if cfg.model in (None, REPO) else cfg.model
        self.language = None if cfg.language == "auto" else cfg.language
        self._model: Any = None

    @property
    def model_id(self) -> str:
        return self.weights or REPO

    def _load(self) -> Any:
        if self._model is None:
            try:
                from needle.agent import fetch
                from needle.agent.whistle import LANGUAGES, Whistle
            except ImportError as exc:
                raise RuntimeError(
                    "cactus-needle is not installed. Run: pip install -e '.[whistle]'"
                ) from exc
            if self.language and self.language not in LANGUAGES:
                raise RuntimeError(
                    f"Whistle does not support language {self.language!r}. "
                    f"Use one of {', '.join(LANGUAGES)} or auto."
                )
            weights = self.weights
            if weights is None:
                # Load cached weights directly: cactus-needle's own lookup pings the Hub on
                # every load, which stalls or fails when working offline.
                cached = Path(fetch.cache_dir(fetch.WHISTLE)) / fetch.base_weights(fetch.WHISTLE)
                weights = cached if cached.is_file() else download()[0]
            self._model = Whistle(weights=weights)
        return self._model

    def _transcribe(self, audio: Audio, word_timestamps: bool) -> dict:
        if audio.sample_rate != SAMPLE_RATE:
            raise ValueError(f"Whistle needs {SAMPLE_RATE} Hz audio, got {audio.sample_rate} Hz")
        samples = np.asarray(audio.samples, dtype=np.float32)
        with _lock:
            return self._load().transcribe(
                samples, language=self.language, word_timestamps=word_timestamps
            )

    def transcribe_preview(self, audio: Audio) -> list[Word]:
        text = self._transcribe(audio, word_timestamps=False)["text"].strip()
        return [Word(text, 0.0, audio.duration)] if text else []

    def transcribe(self, audio: Audio) -> list[Word]:
        result = self._transcribe(audio, word_timestamps=True)
        return [
            Word(
                w["word"].strip(),
                float(w["start"]),
                max(float(w["start"]), float(w["end"])),
                round(float(w["probability"]), 4),
            )
            for w in result.get("words", [])
            if w["word"].strip()
        ]
