"""Optional Mac speech engines. Final transcripts use real word alignment, not guessed times."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from ..audio import Audio, write_wav
from ..config import ASRConfig
from ..models import Word
from . import ASRBackend
from .parakeet import tokens_to_words


class MLXAudioBackend(ASRBackend):
    name = "mlx-audio"

    def __init__(self, cfg: ASRConfig):
        self.cfg = cfg
        self._model: Any = None
        self._aligner: Any = None

    @property
    def model_id(self) -> str:
        return self.cfg.model or "mlx-community/Qwen3-ASR-0.6B-8bit"

    def _load(self):
        if self._model is None:
            from huggingface_hub import snapshot_download
            from huggingface_hub.errors import LocalEntryNotFoundError
            from mlx_audio.stt import load

            # Load installed weights directly: preview retries must not query/download
            # the same repository for every utterance (or fail when working offline).
            try:
                source = Path(snapshot_download(self.model_id, local_files_only=True))
            except LocalEntryNotFoundError:
                source = self.model_id
            self._model = load(source)
        return self._model

    def _generate(self, path: Path):
        kwargs: dict[str, Any] = {"verbose": False}
        if "Qwen3-ASR" in self.model_id:
            kwargs["language"] = {"en": "English", "ne": "Nepali"}.get(self.cfg.language, None)
        return self._load().generate(str(path), **kwargs)

    def transcribe_preview(self, audio: Audio) -> list[Word]:
        text = self._generate(audio.path).text.strip()
        return [Word(text, 0.0, audio.duration)] if text else []

    def transcribe(self, audio: Audio) -> list[Word]:
        # A 30-second bound keeps forced alignment and generative models within memory.
        words: list[Word] = []
        step = audio.sample_rate * 30
        for start in range(0, len(audio.samples), step):
            samples = audio.samples[start : start + step]
            offset = start / audio.sample_rate
            path = audio.path.with_name(f"{audio.path.stem}.alternative-{start}.wav")
            try:
                write_wav(path, samples, audio.sample_rate)
                result = self._generate(path)
                if hasattr(result, "sentences"):
                    aligned = tokens_to_words(
                        token for sentence in result.sentences for token in sentence.tokens
                    )
                elif result.text.strip():
                    if self._aligner is None:
                        from mlx_audio.stt import load

                        self._aligner = load(self.cfg.aligner_model)
                    alignment = self._aligner.generate(
                        audio=str(path), text=result.text, language="English"
                    )
                    aligned = [
                        Word(item.text, item.start_time, item.end_time) for item in alignment.items
                    ]
                    # The aligner strips punctuation. Keep ASR spelling and punctuation when
                    # its word boundaries agree, without guessing any timestamps.
                    original = result.text.split()
                    if len(original) == len(aligned) and all(
                        re.sub(r"[^\w']", "", text).casefold()
                        == re.sub(r"[^\w']", "", word.text).casefold()
                        for text, word in zip(original, aligned, strict=True)
                    ):
                        for text, word in zip(original, aligned, strict=True):
                            word.text = text
                else:
                    aligned = []
                duration = len(samples) / audio.sample_rate
                for word in aligned:
                    word.start = max(0.0, min(word.start, duration)) + offset
                    word.end = max(word.start, min(word.end, duration) + offset)
                    words.append(word)
            finally:
                path.unlink(missing_ok=True)
        return words


class MoonshineBackend(ASRBackend):
    name = "moonshine"

    def __init__(self, model: str | None):
        self.model = model or "medium-streaming"
        self._model: Any = None

    @property
    def model_id(self) -> str:
        return f"moonshine/{self.model}"

    def _load(self):
        if self._model is None:
            from moonshine_voice import ModelArch, Transcriber
            from moonshine_voice.download import get_model_for_language

            arch = getattr(ModelArch, self.model.upper().replace("-", "_"))
            path, arch = get_model_for_language("en", arch, include_word_timestamps=True)
            self._model = Transcriber(path, arch, options={"word_timestamps": "true"})
        return self._model

    def transcribe(self, audio: Audio) -> list[Word]:
        result = self._load().transcribe_without_streaming(
            np.asarray(audio.samples, dtype=np.float32).tolist(), audio.sample_rate
        )
        words = [
            Word(w.word.strip(), float(w.start), float(w.end), float(w.confidence))
            for line in result.lines
            for w in (line.words or [])
            if w.word.strip()
        ]
        if any(line.text.strip() and not line.words for line in result.lines):
            raise RuntimeError("Moonshine did not return word timestamps. Re-download its model.")
        return words

    def close(self):
        if self._model is not None:
            self._model.close()
            self._model = None
