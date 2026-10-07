"""Pass 1: a live transcript while recording.

Incoming audio is cut into utterances at pauses (a simple energy-based voice activity
detector), each utterance is transcribed, and a provisional speaker label is given by
matching its voice against known people and against the voices heard so far in this meeting.

The live transcript is a preview. When recording stops, the full pipeline (pass 2) runs on
the complete recording and its result is the one that is kept.
"""

from __future__ import annotations

import collections
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .align import join_words
from .asr import ASRBackend
from .audio import SAMPLE_RATE, Audio, write_wav
from .diarize import Diarizer, l2_normalize
from .speakers.matching import LibraryEntry, similarity

FRAME_SECONDS = 0.03


@dataclass
class Utterance:
    start: float
    end: float
    samples: np.ndarray


class Segmenter:
    """Energy-based voice activity detection with an adaptive noise floor."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        min_silence: float = 0.6,
        max_utterance: float = 12.0,
        min_speech: float = 0.4,
        snr: float = 3.0,
        abs_floor: float = 0.004,
        preroll: float = 0.2,
    ):
        self.sr = sample_rate
        self.frame = int(FRAME_SECONDS * sample_rate)
        self.min_silence = min_silence
        self.max_utterance = max_utterance
        self.min_speech = min_speech
        self.snr = snr
        self.abs_floor = abs_floor
        self._preroll: collections.deque[np.ndarray] = collections.deque(
            maxlen=max(1, int(preroll / FRAME_SECONDS))
        )
        self._buf = np.zeros(0, dtype=np.float32)
        self._t = 0.0  # start time of the next frame
        self._noise: float | None = None
        self._utt: list[np.ndarray] = []
        self._utt_start: float | None = None
        self._silence = 0.0
        self._speech = 0.0

    def feed(self, samples: np.ndarray) -> list[Utterance]:
        self._buf = np.concatenate([self._buf, samples.astype(np.float32, copy=False)])
        out: list[Utterance] = []
        n = len(self._buf) // self.frame
        for i in range(n):
            utt = self._frame(self._buf[i * self.frame : (i + 1) * self.frame])
            if utt is not None:
                out.append(utt)
        self._buf = self._buf[n * self.frame :]
        return out

    def flush(self) -> list[Utterance]:
        utt = self._close() if self._utt_start is not None else None
        return [utt] if utt is not None else []

    def _frame(self, frame: np.ndarray) -> Utterance | None:
        dur = len(frame) / self.sr
        t0 = self._t
        self._t += dur
        rms = float(np.sqrt(np.mean(frame**2))) + 1e-9
        if self._noise is None:
            # assume a quiet room, so a recording that starts mid-sentence is still heard;
            # the floor then adapts to the actual background noise
            self._noise = self.abs_floor
        if rms < self._noise:
            self._noise = 0.9 * self._noise + 0.1 * rms  # falls quickly
        else:
            self._noise *= 1.002  # rises slowly, so speech doesn't become "noise"
        speech = rms > max(self.abs_floor, self._noise * self.snr)

        if self._utt_start is None:
            if not speech:
                self._preroll.append(frame)
                return None
            self._utt = list(self._preroll)
            self._utt_start = t0 - len(self._preroll) * FRAME_SECONDS
            self._preroll.clear()
            self._silence = self._speech = 0.0
        self._utt.append(frame)
        if speech:
            self._silence = 0.0
            self._speech += dur
        else:
            self._silence += dur
        length = self._t - self._utt_start
        if self._silence >= self.min_silence or length >= self.max_utterance:
            return self._close()
        return None

    def _close(self) -> Utterance | None:
        samples = np.concatenate(self._utt) if self._utt else np.zeros(0, dtype=np.float32)
        start = max(0.0, self._utt_start or 0.0)
        enough = self._speech >= self.min_speech
        self._utt, self._utt_start = [], None
        self._silence = self._speech = 0.0
        if not enough:
            return None
        return Utterance(round(start, 3), round(start + len(samples) / self.sr, 3), samples)


class LiveSpeakerTracker:
    """Provisional labels: a known person if the voice matches one, otherwise "Speaker N"
    for voices heard earlier in this meeting (simple online clustering)."""

    def __init__(
        self, library: list[LibraryEntry], match_threshold: float, cluster_threshold: float = 0.55
    ):
        self.library = library
        self.match_threshold = match_threshold
        self.cluster_threshold = cluster_threshold
        self._clusters: list[tuple[np.ndarray, str]] = []  # (sum of embeddings, label)

    def label(self, embedding: np.ndarray | None) -> str | None:
        if embedding is None or not np.all(np.isfinite(embedding)):
            return None
        best_name, best = None, self.match_threshold
        for entry in self.library:
            score = similarity(embedding, entry.embeddings)
            if score >= best:
                best_name, best = entry.name, score
        if best_name:
            return best_name
        best_i, best = None, self.cluster_threshold
        for i, (total, _) in enumerate(self._clusters):
            score = float(l2_normalize(total) @ embedding)
            if score >= best:
                best_i, best = i, score
        if best_i is None:
            label = f"Speaker {len(self._clusters) + 1}"
            self._clusters.append((embedding.copy(), label))
            return label
        total, label = self._clusters[best_i]
        self._clusters[best_i] = (total + embedding, label)
        return label


class LiveTranscriber:
    """Feeds audio to the segmenter and schedules transcription of each utterance on the
    model worker (`run`), so model calls never overlap with other pipeline work."""

    def __init__(
        self,
        asr: ASRBackend,
        embedder: Diarizer | None,
        tracker: LiveSpeakerTracker,
        work_dir: Path,
        run: Callable[[Callable[[], None]], Future[Any]],
        on_segment: Callable[[dict[str, Any]], None],
        on_error: Callable[[str], None] | None = None,
        sample_rate: int = SAMPLE_RATE,
        min_embed_seconds: float = 1.5,
    ):
        self.asr = asr
        self.embedder = embedder
        self.tracker = tracker
        self.work_dir = work_dir
        self.run = run
        self.on_segment = on_segment
        self.on_error = on_error or (lambda _msg: None)
        self.sr = sample_rate
        self.min_embed = min_embed_seconds
        # short chunks keep the preview responsive and its speaker labels finer-grained
        self.segmenter = Segmenter(sample_rate, min_silence=0.45, max_utterance=8.0)
        self._futures: list[Future[Any]] = []
        self._n = 0

    def feed(self, samples: np.ndarray) -> None:
        for utt in self.segmenter.feed(samples):
            self._submit(utt)

    def finish(self) -> None:
        for utt in self.segmenter.flush():
            self._submit(utt)

    def cancel(self) -> None:
        """Drop utterances not yet transcribed (the full pass will cover them)."""
        for fut in self._futures:
            fut.cancel()

    def _submit(self, utt: Utterance) -> None:
        self._n += 1
        n = self._n
        self._futures = [f for f in self._futures if not f.done()]
        self._futures.append(self.run(lambda: self._process(n, utt)))

    def _process(self, n: int, utt: Utterance) -> None:
        path = self.work_dir / f"live-{n}.wav"
        try:
            write_wav(path, utt.samples, self.sr)
            words = self.asr.transcribe(Audio(utt.samples, self.sr, path))
            text = join_words([w.text for w in words])
            if not text:
                return
            speaker = None
            if self.embedder is not None and utt.end - utt.start >= self.min_embed:
                try:
                    speaker = self.tracker.label(self.embedder.embed([utt.samples], self.sr)[0])
                except Exception:  # a preview label is optional; never break the transcript
                    speaker = None
            self.on_segment(
                {"id": n, "start": utt.start, "end": utt.end, "speaker": speaker, "text": text}
            )
        except Exception as exc:
            self.on_error(f"Live transcription failed: {exc}")
        finally:
            path.unlink(missing_ok=True)
