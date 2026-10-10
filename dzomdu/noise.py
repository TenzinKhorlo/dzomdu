"""Optional, local RNNoise suppression. Never selects or gates a particular speaker.

The pinned runtime bundles its BSD model. Original audio remains the source for
diarization and voiceprints; only transcription receives the enhanced copy.
"""

from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path

import numpy as np

from .audio import SAMPLE_RATE, Audio, read_wav, write_wav
from .config import NoiseConfig

MODEL_ID = "rnnoise-0.4.3-fir61-v1"
INSTALL_COMMAND = "python -m pip install -e '.[denoise]'"


class NoiseSuppressor:
    """Stateful 16 kHz mono stream, with resampling and model delay compensated.

    Native RNNoise v0.2 delays two 480-sample frames at 48 kHz. The two
    61-tap FIR resamplers add 60 samples. Output is therefore delayed by
    340 samples at 16 kHz (21.25 ms), plus frame buffering and compute.
    Returned dry samples have exactly the same timeline as returned wet samples.
    """

    delay_samples = 340
    frame_samples = 160

    def __init__(self, strength: float = 0.5):
        NoiseConfig(strength=strength)
        try:
            from pyrnnoise.rnnoise import FRAME_SIZE, create, destroy, lib
            from scipy.signal import firwin, lfilter
        except (ImportError, OSError) as exc:
            raise RuntimeError(f"Noise suppression setup needed: {INSTALL_COMMAND}") from exc
        if FRAME_SIZE != 480:
            raise RuntimeError("Unexpected RNNoise frame size")
        self.strength = strength
        self._destroy = destroy
        self._lib = lib
        self._state = create()
        if not self._state:
            raise RuntimeError("Could not initialise RNNoise")
        self._lfilter = lfilter
        self._taps = firwin(61, 1 / 3).astype(np.float32)
        self._up_state = np.zeros(60, np.float32)
        self._down_state = np.zeros(60, np.float32)
        self._pending = np.zeros(0, np.float32)
        self._dry = np.zeros(0, np.float32)
        self._skip = self.delay_samples
        self._finished = False

    def feed(self, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self._finished:
            raise RuntimeError("Noise suppressor has finished")
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise ValueError("Expected finite mono audio samples")
        self._dry = np.concatenate([self._dry, samples])
        return self._process(samples)

    def _process(self, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        empty = np.zeros(0, np.float32)
        if not len(samples):
            return empty, empty
        up = np.zeros(len(samples) * 3, np.float32)
        up[::3] = samples
        up, self._up_state = self._lfilter(self._taps * 3, [1.0], up, zi=self._up_state)
        self._pending = np.concatenate([self._pending, up])
        blocks = []
        count = len(self._pending) // 480
        for i in range(count):
            frame = np.ascontiguousarray(
                self._pending[i * 480 : (i + 1) * 480] * 32768, dtype=np.float32
            )
            ptr = frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            # Ignore the VAD probability: it must never mute a quiet participant.
            self._lib.rnnoise_process_frame(self._state, ptr, ptr)
            down, self._down_state = self._lfilter(
                self._taps, [1.0], frame / 32768, zi=self._down_state
            )
            blocks.append(down[::3])
        self._pending = self._pending[count * 480 :]
        if not blocks:
            return empty, empty
        wet = np.concatenate(blocks)
        skip = min(len(wet), self._skip)
        self._skip -= skip
        wet = wet[skip:]
        count = min(len(wet), len(self._dry))
        dry, self._dry = self._dry[:count].copy(), self._dry[count:]
        wet = wet[:count]
        # Mix aligned signals. A maximum 75% wet setting retains 25% original.
        clean = (self.strength * wet + (1 - self.strength) * dry).astype(np.float32)
        return clean, dry

    def finish(self) -> tuple[np.ndarray, np.ndarray]:
        if self._finished:
            return np.zeros(0, np.float32), np.zeros(0, np.float32)
        # Drain FIR history, native model lookahead and any partial input frame.
        result = self._process(np.zeros(len(self._dry) + self.delay_samples + 160, np.float32))
        self._finished = True
        self.close()
        return result

    def close(self):
        if getattr(self, "_state", None):
            self._destroy(self._state)
            self._state = None
        self._finished = True

    def __del__(self):
        self.close()


def enhance_audio(audio: Audio, work: Path, cfg: NoiseConfig) -> Audio:
    """Cache a separate, duration-preserving WAV; never overwrite the original."""
    if not cfg.enabled or cfg.strength == 0:
        return audio
    if audio.sample_rate != SAMPLE_RATE:
        raise ValueError("Noise suppression expects 16 kHz audio")
    key = hashlib.sha256(f"{MODEL_ID}|{cfg.strength}".encode()).hexdigest()[:12]
    path = work / f"audio-clean-{key}.wav"
    if path.exists():
        samples, sr = read_wav(path)
        if sr == audio.sample_rate and len(samples) == len(audio.samples):
            return Audio(samples, sr, path)
    suppressor = NoiseSuppressor(cfg.strength)
    try:
        blocks = [
            suppressor.feed(audio.samples[i : i + SAMPLE_RATE])[0]
            for i in range(0, len(audio.samples), SAMPLE_RATE)
        ]
        blocks.append(suppressor.finish()[0])
        samples = np.concatenate(blocks)
        if len(samples) != len(audio.samples):
            raise RuntimeError("Noise suppression changed the audio duration")
        temporary = path.with_suffix(".tmp.wav")
        write_wav(temporary, samples, audio.sample_rate)
        temporary.replace(path)
        return Audio(samples, audio.sample_rate, path)
    finally:
        suppressor.close()
