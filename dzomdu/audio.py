"""Audio decoding and storage. Everything is normalised to 16 kHz mono float32."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000


@dataclass
class Audio:
    samples: np.ndarray  # float32, mono, [-1, 1]
    sample_rate: int
    path: Path  # normalised 16 kHz mono WAV on disk (backends that want a file use this)

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate

    def slice(self, start: float, end: float) -> np.ndarray:
        a = max(0, int(start * self.sample_rate))
        b = min(len(self.samples), int(end * self.sample_rate))
        return self.samples[a:b]


def decode(path: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode any audio/video file with ffmpeg. Falls back to the stdlib for plain WAV files."""
    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path)]
        cmd += f"-f f32le -acodec pcm_f32le -ac 1 -ar {sample_rate} -".split()
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg could not decode {path}: {proc.stderr.decode().strip()}")
        return np.frombuffer(proc.stdout, dtype=np.float32).copy()
    samples, sr = read_wav(path)
    if sr != sample_rate:
        raise RuntimeError(f"{path} is {sr} Hz and ffmpeg is not installed to resample it")
    return samples


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise RuntimeError(f"{path}: only 16-bit PCM WAV can be read without ffmpeg")
        frames = wf.readframes(wf.getnframes())
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        channels = wf.getnchannels()
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        return data, wf.getframerate()


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def prepare_audio(source: Path, work_dir: Path) -> Audio:
    """Decode `source` once and keep a normalised WAV copy in `work_dir`."""
    wav_path = work_dir / "audio.wav"
    if wav_path.exists():
        samples, sr = read_wav(wav_path)
        return Audio(samples=samples, sample_rate=sr, path=wav_path)
    samples = decode(source)
    if samples.size == 0:
        raise RuntimeError(f"{source} contains no audio")
    write_wav(wav_path, samples)
    return Audio(samples=samples, sample_rate=SAMPLE_RATE, path=wav_path)
