"""pyannote.audio 4 with the `speaker-diarization-community-1` pipeline.

The model is downloaded once from Hugging Face (accept its terms at
https://huggingface.co/pyannote/speaker-diarization-community-1 and run `hf auth login`), then
runs fully offline from the local cache.
"""

from __future__ import annotations

import os
import warnings
from typing import Any

import numpy as np

from ..audio import Audio
from ..models import SpeakerSegment
from . import Diarizer, l2_normalize


def access_problem(model: str, token: str | None = None) -> str | None:
    """Ask Hugging Face whether this account may download `model`. Returns a plain-language
    explanation of what to fix, or None when access is fine (or can't be checked)."""
    try:
        from huggingface_hub import auth_check, get_token
        from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError
    except ImportError:
        return None
    if not (token or get_token()):
        return (
            "No Hugging Face token found. With the virtual environment active, run "
            "`hf auth login` and paste a Read token from https://huggingface.co/settings/tokens."
        )
    # HF_TOKEN in the environment silently overrides the token saved by `hf auth login`
    env_note = (
        " Note: the HF_TOKEN environment variable is set, and it takes priority over "
        "`hf auth login`. If it is old or a placeholder, run `unset HF_TOKEN` (and remove it "
        "from ~/.zshrc if you added it there)."
        if os.environ.get("HF_TOKEN")
        else ""
    )
    rejected = (
        "Hugging Face did not accept your login (the token may be mistyped, expired or "
        "deleted). Create a new Read token at https://huggingface.co/settings/tokens and run "
        "`hf auth login` again." + env_note
    )
    try:
        auth_check(model, token=token)
    except GatedRepoError as exc:
        # 401 = not authenticated at all; 403 = authenticated but no access to this model
        if getattr(getattr(exc, "response", None), "status_code", None) == 401:
            return rejected
        return (
            f"Your Hugging Face account has not been given access to {model}. Open "
            f"https://huggingface.co/{model} while logged in as the account your token belongs "
            "to, and accept the conditions. If your token is fine-grained, edit it and tick "
            "'Read access to contents of all public gated repos you can access' (or create a "
            "classic Read token and run `hf auth login` again)." + env_note
        )
    except RepositoryNotFoundError:
        return rejected
    except Exception as exc:  # network problems, proxies, outages
        return f"Could not reach huggingface.co to check access ({exc.__class__.__name__}: {exc})"
    return None


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
        self._load_error: str | None = None

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
                    "pyannote.audio is not installed. Run: pip install -e '.[diarize]'"
                ) from exc
            if self._load_error:  # don't retry the download on every live chunk
                raise RuntimeError(self._load_error)
            token = os.environ.get(self.token_env) or None
            try:
                pipeline = Pipeline.from_pretrained(self.model, token=token)
                if pipeline is None:
                    raise RuntimeError("the pipeline could not be loaded")
            except Exception as exc:
                reason = access_problem(self.model, token) or f"{exc.__class__.__name__}: {exc}"
                self._load_error = (
                    f"Cannot download the speaker model {self.model}. {reason} Then restart Dzomdu."
                )
                raise RuntimeError(self._load_error) from exc
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
