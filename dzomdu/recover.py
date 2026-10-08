"""Find speech the full transcription missed, and transcribe it on its own.

Speech engines occasionally return nothing for a stretch that clearly contains speech: most
often the last sentence of a recording (Stop pressed straight after someone spoke), or a short
reply between two long turns. Two independent detectors say where speech is: the diarization
segments and a simple energy-based voice detector. Any stretch of a second or more that they
mark as speech but that has no words is transcribed again in isolation, with a little silence
around it, and the words are merged back in.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from .asr import ASRBackend
from .audio import Audio, write_wav
from .live import Segmenter
from .models import SpeakerSegment, Word

PAD = 0.5  # seconds of silence around a re-transcribed stretch


def _merge(spans: list[tuple[float, float]], gap: float = 0.3) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def speech_regions(audio: Audio, segments: list[SpeakerSegment]) -> list[tuple[float, float]]:
    """Where there is speech: diarization segments plus energy-detected utterances."""
    regions = [(s.start, s.end) for s in segments]
    seg = Segmenter(audio.sample_rate, min_silence=0.5, max_utterance=30.0)
    utts = seg.feed(audio.samples) + seg.flush()
    # an utterance carries a little lead-in and the closing silence; keep only the speech
    regions += [(u.start + 0.2, u.end - 0.5) for u in utts if u.end - u.start > 0.9]
    return _merge([(a, b) for a, b in regions if b > a])


def missing_spans(
    words: list[Word], regions: list[tuple[float, float]], min_gap: float = 1.0
) -> list[tuple[float, float]]:
    """Stretches of at least `min_gap` seconds inside speech regions with no words."""
    words = sorted(words, key=lambda w: w.start)
    spans: list[tuple[float, float]] = []
    for a, b in regions:
        cursor = a
        for w in words:
            if w.end <= a or w.start >= b:
                continue
            if w.start - cursor >= min_gap:
                spans.append((cursor, w.start))
            cursor = max(cursor, w.end)
        if b - cursor >= min_gap:
            spans.append((cursor, b))
    return _merge(spans, gap=0.0)


def recover_words(
    audio: Audio,
    words: list[Word],
    segments: list[SpeakerSegment],
    asr: ASRBackend,
    work: Path,
    progress: Callable[[str], None] | None = None,
    max_spans: int = 60,
) -> list[Word]:
    """Return `words` plus anything found in stretches the full pass left empty."""
    spans = missing_spans(words, speech_regions(audio, segments))[:max_spans]
    if not spans:
        return words
    if progress:
        progress(f"Re-checking {len(spans)} stretch{'es' if len(spans) != 1 else ''} with no words")
    found: list[Word] = []
    silence = np.zeros(int(PAD * audio.sample_rate), np.float32)
    for i, (a, b) in enumerate(spans):
        start = max(0.0, a - 0.25)
        end = min(audio.duration, b + 0.25)
        samples = np.concatenate([silence, audio.slice(start, end), silence])
        path = work / f"recover-{i}.wav"
        try:
            write_wav(path, samples, audio.sample_rate)
            got = asr.transcribe(Audio(samples, audio.sample_rate, path))
        except Exception:  # a second look is a bonus; it must never break the meeting
            continue
        finally:
            path.unlink(missing_ok=True)
        offset = start - PAD
        for w in got:
            ws, we = round(w.start + offset, 3), round(w.end + offset, 3)
            if start <= (ws + we) / 2 <= end:
                found.append(Word(w.text, max(start, ws), min(end, we), w.confidence))
    if not found:
        return words
    # keep only words that don't overlap ones the full pass already had
    taken = sorted((w.start, w.end) for w in words)
    keep = [w for w in found if not any(min(w.end, e) - max(w.start, s) > 0.05 for s, e in taken)]
    return sorted(words + keep, key=lambda w: (w.start, w.end))
