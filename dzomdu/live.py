"""Pass 1: a live transcript while recording.

Incoming audio is cut into utterances at pauses (a simple energy-based voice activity
detector), each utterance is transcribed, and a provisional speaker label is given by
matching its voice against known people and against the voices heard so far in this meeting.

So words appear while someone is still talking, the utterance in progress is re-transcribed
every ~0.7 s and sent as an interim ("partial") segment. It is replaced by the final segment,
with the same id, once the speaker pauses. A final segment is sent as soon as its text is
known and sent again once its speaker label is known, because the voice match takes longer.

The live transcript is a preview. When recording stops, the full pipeline (pass 2) runs on
the complete recording and its result is the one that is kept.
"""

from __future__ import annotations

import collections
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from .align import join_words
from .asr import ASRBackend
from .audio import SAMPLE_RATE, Audio, write_wav
from .diarize import Diarizer, l2_normalize
from .noise import NoiseSuppressor
from .speakers.matching import LibraryEntry, similarity

FRAME_SECONDS = 0.03


@dataclass
class Utterance:
    start: float
    end: float
    samples: np.ndarray
    original_samples: np.ndarray | None = None


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

    def current(self) -> Utterance | None:
        """The utterance in progress so far, once it contains enough speech to transcribe."""
        if self._utt_start is None or self._speech < self.min_speech:
            return None
        samples = np.concatenate(self._utt)
        start = max(0.0, self._utt_start)
        return Utterance(round(start, 3), round(start + len(samples) / self.sr, 3), samples)

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

    def label(self, embedding: np.ndarray | None, learn: bool = True) -> str | None:
        """`learn=False` only looks: an interim guess must not add a voice to the meeting."""
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
        if not learn:
            return self._clusters[best_i][1] if best_i is not None else None
        if best_i is None:
            label = f"Speaker {len(self._clusters) + 1}"
            self._clusters.append((embedding.copy(), label))
            return label
        total, label = self._clusters[best_i]
        self._clusters[best_i] = (total + embedding, label)
        return label


class LiveTranscriber:
    """Feeds audio to the segmenter and schedules transcription of each utterance on the
    model worker (`run`), so model calls never overlap with other pipeline work.

    Segments are reported through `on_segment` as dicts with an `id`. The same id is reported
    again whenever it improves: interim text → final text → final text with a speaker.
    """

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
        partial_every: float | None = 0.7,
        noise: NoiseSuppressor | None = None,
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
        self.partial_every = partial_every
        # short chunks keep the preview responsive and its speaker labels finer-grained
        self.segmenter = Segmenter(sample_rate, min_silence=0.45, max_utterance=8.0)
        self._futures: list[Future[Any]] = []
        self._n = 0
        self._open_id: int | None = None  # id given to the utterance in progress
        self._partial_len = 0.0  # its length when it was last sent for an interim transcript
        self._partial: Future[Any] | None = None
        self._guess: dict[int, str] = {}  # interim speaker guesses, by segment id
        self._shown: set[int] = set()  # ids whose interim text is on screen
        self.noise = noise
        self._raw = np.zeros(0, np.float32)
        self._raw_start = 0
        self._output_samples = 0

    def feed(self, samples: np.ndarray) -> None:
        self._raw = np.concatenate([self._raw, samples])
        if self.noise is not None:
            try:
                samples, _ = self.noise.feed(samples)
            except Exception as exc:
                self.on_error(f"Noise suppression stopped; using original audio: {exc}")
                self.noise.close()
                self.noise = None
                # Feed everything not emitted yet, without a gap or timestamp jump.
                samples = self._raw[self._output_samples - self._raw_start :].copy()
        self._feed_clean(samples)
        # Keep enough raw history for the longest utterance, including pre-roll.
        keep_from = max(self._raw_start, self._output_samples - int(12 * self.sr))
        self._raw = self._raw[keep_from - self._raw_start :]
        self._raw_start = keep_from

    def _feed_clean(self, samples: np.ndarray) -> None:
        self._output_samples += len(samples)
        for utt in self.segmenter.feed(samples):
            self._submit(utt)
        self._maybe_partial()

    def finish(self) -> None:
        if self.noise is not None:
            try:
                samples = self.noise.finish()[0]
            except Exception as exc:
                self.on_error(f"Noise suppression stopped; using original audio: {exc}")
                samples = self._raw[self._output_samples - self._raw_start :].copy()
            finally:
                self.noise.close()
                self.noise = None
            self._feed_clean(samples)
        for utt in self.segmenter.flush():
            self._submit(utt)

    def cancel(self) -> None:
        """Drop utterances not yet transcribed (the full pass will cover them)."""
        for fut in self._futures:
            fut.cancel()
        if self.noise is not None:
            self.noise.close()

    def _with_original(self, utt: Utterance) -> Utterance:
        start = max(0, round(utt.start * self.sr) - self._raw_start)
        original = self._raw[start : start + len(utt.samples)].copy()
        return replace(utt, original_samples=original)

    def _schedule(self, job: Callable[[], None]) -> Future[Any]:
        self._futures = [f for f in self._futures if not f.done()]
        fut = self.run(job)
        self._futures.append(fut)
        return fut

    def _submit(self, utt: Utterance) -> None:
        utt = self._with_original(utt)
        if self._open_id is None:
            self._n += 1
            n = self._n
        else:
            n, self._open_id = self._open_id, None
        self._partial_len = 0.0
        self._schedule(lambda: self._process(n, utt))

    def _maybe_partial(self) -> None:
        if not self.partial_every:
            return
        utt = self.segmenter.current()
        if utt is None or utt.end - utt.start - self._partial_len < self.partial_every:
            return
        if self._partial is not None and not self._partial.done():
            return  # the worker is behind: skip this one rather than queue up stale work
        if self._open_id is None:
            self._n += 1
            self._open_id = self._n
        n = self._open_id
        self._partial_len = utt.end - utt.start
        utt = self._with_original(utt)
        self._partial = self._schedule(lambda: self._process(n, utt, final=False))

    def _transcribe(self, n: int, utt: Utterance, tag: str) -> str:
        path = self.work_dir / f"live-{n}-{tag}.wav"
        try:
            write_wav(path, utt.samples, self.sr)
            return join_words(
                [w.text for w in self.asr.transcribe_preview(Audio(utt.samples, self.sr, path))]
            )
        finally:
            path.unlink(missing_ok=True)

    def _embed(self, utt: Utterance) -> np.ndarray | None:
        if self.embedder is None or utt.end - utt.start < self.min_embed:
            return None
        try:
            samples = utt.original_samples if utt.original_samples is not None else utt.samples
            return self.embedder.embed([samples], self.sr)[0]
        except Exception:  # a preview label is optional; never break the transcript
            return None

    def _process(self, n: int, utt: Utterance, final: bool = True) -> None:
        seg: dict[str, Any] = {"id": n, "start": utt.start, "end": utt.end, "partial": not final}
        try:
            text = self._transcribe(n, utt, "final" if final else "partial")
            if not final:
                if not text:
                    return
                if n not in self._guess:
                    guess = self.tracker.label(self._embed(utt), learn=False)
                    if guess:
                        self._guess[n] = guess
                self._shown.add(n)
                self.on_segment(seg | {"speaker": self._guess.get(n), "text": text})
                return
            if not text:
                if n in self._shown:  # interim words turned out to be nothing: take them back
                    self.on_segment(seg | {"speaker": None, "text": ""})
                return
            # the words first; the voice match takes longer
            guess = self._guess.pop(n, None)
            self.on_segment(seg | {"speaker": guess, "text": text})
            speaker = self.tracker.label(self._embed(utt))
            if speaker != guess:
                self.on_segment(seg | {"speaker": speaker, "text": text})
        except Exception as exc:
            self.on_error(f"Live transcription failed: {exc}")
        finally:
            if final:
                self._shown.discard(n)
