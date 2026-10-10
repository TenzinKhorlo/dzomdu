"""Image smoke check without GPU hardware, model downloads, or personal data."""

from pathlib import Path
from tempfile import TemporaryDirectory

import moonshine_voice  # noqa: F401
import numpy as np
import torch
from faster_whisper import WhisperModel  # noqa: F401
from pyannote.audio import Pipeline  # noqa: F401
from torchcodec.decoders import AudioDecoder

from dzomdu.audio import write_wav
from dzomdu.noise import NoiseSuppressor
from dzomdu.server.app import create_app  # noqa: F401

assert torch.__version__.split("+")[0] == "2.10.0"
with TemporaryDirectory() as folder:
    audio = Path(folder) / "test.wav"
    write_wav(audio, np.zeros(16000, dtype=np.float32))
    assert AudioDecoder(str(audio)).get_all_samples().data.numel() == 16000
noise = NoiseSuppressor()
noise.feed(np.zeros(1600, dtype=np.float32))
noise.finish()
noise.close()
print("Linux image audio runtimes ready")
