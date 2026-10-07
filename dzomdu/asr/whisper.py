"""Whisper backends: mlx-whisper (Apple Silicon) and faster-whisper (CPU / CUDA)."""

from __future__ import annotations

from typing import Any

from ..audio import Audio
from ..models import Word
from . import ASRBackend


def _clean(words: list[Word]) -> list[Word]:
    return [w for w in words if w.text and w.end >= w.start]


class MLXWhisperBackend(ASRBackend):
    name = "mlx-whisper"
    default_model = "mlx-community/whisper-large-v3-turbo"

    def __init__(self, model: str | None = None, language: str | None = "en"):
        self._model_id = model or self.default_model
        self.language = language

    @property
    def model_id(self) -> str:
        return self._model_id

    def transcribe(self, audio: Audio) -> list[Word]:
        try:
            import mlx_whisper
        except ImportError as exc:  # pragma: no cover - depends on platform
            raise RuntimeError(
                "mlx-whisper is not installed. On an Apple Silicon Mac run: pip install -e '.[mac]'"
            ) from exc
        result = mlx_whisper.transcribe(
            str(audio.path),
            path_or_hf_repo=self._model_id,
            word_timestamps=True,
            language=self.language,
            condition_on_previous_text=False,  # reduces repetition loops on long audio
        )
        words = [
            Word(
                text=w["word"].strip(),
                start=float(w["start"]),
                end=float(w["end"]),
                confidence=float(w.get("probability", 1.0)),
            )
            for seg in result.get("segments", [])
            for w in seg.get("words", [])
        ]
        return _clean(words)


class FasterWhisperBackend(ASRBackend):
    name = "faster-whisper"
    default_model = "large-v3-turbo"

    def __init__(self, model: str | None = None, language: str | None = "en"):
        self._model_id = model or self.default_model
        self.language = language
        self._model: Any = None

    @property
    def model_id(self) -> str:
        return f"faster-whisper/{self._model_id}"

    def transcribe(self, audio: Audio) -> list[Word]:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed. Run: pip install -e '.[whisper]'"
                ) from exc
            self._model = WhisperModel(self._model_id, device="auto", compute_type="default")
        segments, _info = self._model.transcribe(
            str(audio.path),
            language=self.language,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        words = [
            Word(text=w.word.strip(), start=w.start, end=w.end, confidence=w.probability)
            for seg in segments
            for w in (seg.words or [])
        ]
        return _clean(words)
