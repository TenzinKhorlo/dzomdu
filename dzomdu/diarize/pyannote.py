"""pyannote.audio 4 with the `speaker-diarization-community-1` pipeline.

The model is downloaded once from Hugging Face (accept its terms at
https://huggingface.co/pyannote/speaker-diarization-community-1 and set HF_TOKEN), then runs
fully offline from the local cache.
"""

from __future__ import annotations

import os
import warnings
from typing import Any

import numpy as np

from ..audio import Audio
from ..models import SpeakerSegment
from . import Diarizer, l2_normalize


class PyannoteDiarizer(Diarizer):
    name = "pyannote"

    def __init__(
        self,
        model: str = "pyannote/speaker-diarization-community-1",
        device: str = "auto",
        token_env: str = "HF_TOKEN",
    ):
        self.model = model
        self.device = device
        self.token_env = token_env
        self._pipeline: Any = None
        self._device: Any = None

    @property
    def model_id(self) -> str:
        return f"pyannote:{self.model}"

    def _torch_device(self) -> Any:
        import torch

        if self.device != "auto":
            return torch.device(self.device)
        if torch.backends.mps.is_available():
            return torch.device("mps")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    def _load(self) -> Any:
        if self._pipeline is None:
            try:
                from pyannote.audio import Pipeline
            except ImportError as exc:
                raise RuntimeError(
                    "pyannote.audio is not installed. Run: uv sync --extra diarize"
                ) from exc
            token = os.environ.get(self.token_env) or None
            pipeline = Pipeline.from_pretrained(self.model, token=token)
            if pipeline is None:
                raise RuntimeError(
                    f"Could not load {self.model}. Accept the model terms on Hugging Face and "
                    f"set {self.token_env} for the first download."
                )
            self._device = self._torch_device()
            pipeline.to(self._device)
            self._pipeline = pipeline
        return self._pipeline

    def diarize(
        self,
        audio: Audio,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[SpeakerSegment]:
        import torch

        pipeline = self._load()
        # Passing the waveform in memory avoids a second decode (and torchcodec/ffmpeg issues).
        file = {
            "waveform": torch.from_numpy(audio.samples).unsqueeze(0),
            "sample_rate": audio.sample_rate,
        }
        kwargs = dict(
            num_speakers=num_speakers, min_speakers=min_speakers, max_speakers=max_speakers
        )
        try:
            output = pipeline(file, **kwargs)
        except (RuntimeError, NotImplementedError) as exc:
            # Some PyTorch ops are missing or buggy on Apple's GPU (MPS); CPU always works.
            if self._device is None or self._device.type != "mps":
                raise
            warnings.warn(f"pyannote failed on MPS ({exc}); retrying on CPU", stacklevel=2)
            self._device = torch.device("cpu")
            pipeline.to(self._device)
            output = pipeline(file, **kwargs)
        # pyannote 4 returns DiarizeOutput; prefer the exclusive (non-overlapping) version,
        # which is designed for aligning with transcripts.
        annotation = getattr(output, "exclusive_speaker_diarization", None)
        if annotation is None:
            annotation = getattr(output, "speaker_diarization", output)
        segments = [
            SpeakerSegment(start=float(seg.start), end=float(seg.end), speaker=str(label))
            for seg, _track, label in annotation.itertracks(yield_label=True)
        ]
        return sorted(segments, key=lambda s: (s.start, s.end))

    def embed(self, waveforms: list[np.ndarray], sample_rate: int) -> np.ndarray:
        import torch

        pipeline = self._load()
        embedding = pipeline._embedding  # the pipeline's own model -> same space as clustering
        expected_sr = getattr(embedding, "sample_rate", sample_rate)
        if expected_sr != sample_rate:
            raise RuntimeError(f"Embedding model expects {expected_sr} Hz, got {sample_rate} Hz")
        rows = []
        for wav in waveforms:
            tensor = torch.from_numpy(np.ascontiguousarray(wav, dtype=np.float32))[None, None]
            rows.append(np.asarray(embedding(tensor))[0])
        if not rows:
            return np.zeros((0, getattr(embedding, "dimension", 256)), dtype=np.float32)
        return l2_normalize(np.stack(rows).astype(np.float32))
