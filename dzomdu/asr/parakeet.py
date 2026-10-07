"""NVIDIA Parakeet TDT on Apple Silicon via parakeet-mlx (English, word timestamps)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..audio import Audio
from ..models import Word
from . import ASRBackend


class ParakeetMLXBackend(ASRBackend):
    name = "parakeet"
    default_model = "mlx-community/parakeet-tdt-0.6b-v2"

    def __init__(
        self, model: str | None = None, chunk_duration: float = 120.0, overlap: float = 15.0
    ):
        self._model_id = model or self.default_model
        self.chunk_duration = chunk_duration
        self.overlap = overlap
        self._model: Any = None

    @property
    def model_id(self) -> str:
        return self._model_id

    def _load(self) -> Any:
        if self._model is None:
            try:
                from parakeet_mlx import from_pretrained
            except ImportError as exc:  # pragma: no cover - depends on platform
                raise RuntimeError(
                    "parakeet-mlx is not installed. On an Apple Silicon Mac run: "
                    "pip install -e '.[mac]'"
                ) from exc
            self._model = from_pretrained(self._model_id)
        return self._model

    def transcribe(self, audio: Audio) -> list[Word]:
        model = self._load()
        chunk = self.chunk_duration if audio.duration > self.chunk_duration else None
        result = model.transcribe(
            str(audio.path), chunk_duration=chunk, overlap_duration=self.overlap
        )
        tokens = [token for sentence in result.sentences for token in sentence.tokens]
        return tokens_to_words(tokens)


def tokens_to_words(tokens: Iterable[Any]) -> list[Word]:
    """Merge sub-word tokens into words.

    parakeet-mlx decodes SentencePiece pieces with "▁" replaced by a space, so a token whose
    text starts with a space begins a new word; other tokens continue the current word.
    """
    words: list[Word] = []
    confidences: list[list[float]] = []
    for tok in tokens:
        text: str = tok.text
        if not text:
            continue
        start = float(tok.start)
        end = float(getattr(tok, "end", 0.0) or start + float(getattr(tok, "duration", 0.0)))
        conf = float(getattr(tok, "confidence", 1.0))
        if not words or text[0].isspace():
            stripped = text.strip()
            if not stripped:
                continue
            words.append(Word(text=stripped, start=start, end=end))
            confidences.append([conf])
        else:
            words[-1].text += text
            words[-1].end = max(words[-1].end, end)
            confidences[-1].append(conf)
    for word, confs in zip(words, confidences, strict=True):
        word.confidence = round(min(confs), 4)
    return words
