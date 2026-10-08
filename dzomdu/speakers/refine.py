"""A second opinion on diarization: split clusters that contain clearly different voices.

The diarization model groups the whole recording into speakers at once. Two people with
similar voices sometimes end up in one cluster, and then no later step can tell them apart:
the meeting shows one speaker where there were two. The live preview does not have this
problem, because it labels every utterance on its own (against known people, then against the
voices heard so far).

This module applies that same per-utterance view after diarization. Each cluster is cut into
short windows, every window gets a voiceprint and a label (a known person, or "voice N" within
the cluster), and a cluster is split only when it holds at least two distinct voices with
enough speech each. Splitting too eagerly is the cheaper mistake: two halves of one person can
be given the same name on the review screen (they are merged), but one cluster with two people
cannot be fixed there.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..audio import Audio
from ..diarize import Diarizer, l2_normalize
from ..models import SpeakerSegment
from .matching import LibraryEntry, similarity


@dataclass
class _Window:
    start: float
    end: float
    seg: int  # index of the diarization segment it came from
    emb: np.ndarray | None = None
    label: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


def _windows(segments: list[tuple[int, SpeakerSegment]], size: float, min_size: float):
    """Cut segments into windows of about `size` seconds; a short tail joins the last one."""
    out: list[_Window] = []
    for i, seg in segments:
        if seg.duration < min_size:
            continue
        n = max(1, int(seg.duration // size))
        step = seg.duration / n
        for k in range(n):
            out.append(_Window(seg.start + k * step, seg.start + (k + 1) * step, i))
    return out


def _label(
    emb: np.ndarray,
    library: list[LibraryEntry],
    accept: float,
    voices: list[list],
    same_voice: float,
) -> str:
    """A known person if the voice clearly matches one; otherwise the closest voice heard
    earlier in this cluster, or a new one."""
    best_name, best = None, accept
    for entry in library:
        if len(entry.embeddings):
            score = similarity(emb, entry.embeddings)
            if score >= best:
                best_name, best = entry.name, score
    if best_name:
        return f"person:{best_name}"
    best_i, best = None, -1.0
    for i, (total, _) in enumerate(voices):
        score = float(l2_normalize(total) @ emb)
        if score > best:
            best_i, best = i, score
    if best_i is not None and best >= same_voice:
        voices[best_i][0] = voices[best_i][0] + emb
        return voices[best_i][1]
    label = f"voice:{len(voices) + 1}"
    voices.append([emb.copy(), label])
    return label


def refine_clusters(
    audio: Audio,
    segments: list[SpeakerSegment],
    diarizer: Diarizer,
    library: list[LibraryEntry],
    *,
    accept_threshold: float = 0.6,
    window: float = 3.0,
    min_window: float = 1.2,
    min_voice_seconds: float = 3.0,
    same_voice: float = 0.5,
    progress: Callable[[str], None] | None = None,
) -> list[SpeakerSegment]:
    """Return the segments with mixed clusters split. Unchanged clusters keep their segments
    exactly as they were. `same_voice` is the cosine similarity above which two windows (or
    two voices) are taken to be the same person."""
    by_cluster: dict[str, list[tuple[int, SpeakerSegment]]] = {}
    for i, seg in enumerate(segments):
        by_cluster.setdefault(seg.speaker, []).append((i, seg))

    taken = set(by_cluster)
    out: list[SpeakerSegment] = []
    for cluster, segs in by_cluster.items():
        parts = _split(
            audio,
            cluster,
            segs,
            diarizer,
            library,
            accept_threshold,
            window,
            min_window,
            min_voice_seconds,
            same_voice,
        )
        if parts is None:
            out.extend(seg for _, seg in segs)
            continue
        # the voice heard first keeps the original cluster id
        names: dict[str, str] = {}
        for seg in sorted(parts, key=lambda s: s.start):
            if seg.speaker not in names:
                if not names:
                    names[seg.speaker] = cluster
                else:
                    k = 2
                    while f"{cluster}_{k}" in taken:
                        k += 1
                    names[seg.speaker] = f"{cluster}_{k}"
                    taken.add(names[seg.speaker])
        out.extend(SpeakerSegment(s.start, s.end, names[s.speaker]) for s in parts)
        if progress:
            progress(f"Found {len(names)} different voices in one speaker group; separated them")
    return sorted(out, key=lambda s: (s.start, s.end))


def _split(
    audio: Audio,
    cluster: str,
    segs: list[tuple[int, SpeakerSegment]],
    diarizer: Diarizer,
    library: list[LibraryEntry],
    accept: float,
    window: float,
    min_window: float,
    min_voice_seconds: float,
    same_voice: float,
) -> list[SpeakerSegment] | None:
    total = sum(s.duration for _, s in segs)
    if total < 2 * min_voice_seconds:
        return None  # not enough speech for two voices
    wins = _windows(segs, window, min_window)
    if len(wins) < 2:
        return None
    embs = diarizer.embed([audio.slice(w.start, w.end) for w in wins], audio.sample_rate)
    good = [w for w, e in zip(wins, embs, strict=True) if np.all(np.isfinite(e))]
    for w, e in zip(wins, embs, strict=True):
        w.emb = e if np.all(np.isfinite(e)) else None
    if len(good) < 2:
        return None

    voices: list[list] = []
    for w in good:
        w.label = _label(w.emb, library, accept, voices, same_voice)

    # voices with enough speech to count; the rest are noise that rejoins its nearest voice
    groups: dict[str, list[_Window]] = {}
    for w in good:
        groups.setdefault(w.label, []).append(w)
    major = {k: v for k, v in groups.items() if sum(w.duration for w in v) >= min_voice_seconds}
    if len(major) < 2:
        return None

    def centroid(ws: list[_Window]) -> np.ndarray:
        return l2_normalize(np.mean([w.emb for w in ws], axis=0))

    # merge voices that are close, unless they are two different known people
    while len(major) >= 2:
        keys = list(major)
        best, pair = -1.0, None
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                ka, kb = keys[a], keys[b]
                if ka.startswith("person:") and kb.startswith("person:"):
                    continue
                score = float(centroid(major[ka]) @ centroid(major[kb]))
                if score > best:
                    best, pair = score, (ka, kb)
        if pair is None or best < same_voice:
            break
        ka, kb = pair
        keep, drop = (ka, kb) if not kb.startswith("person:") else (kb, ka)
        major[keep] = major[keep] + major.pop(drop)
    if len(major) < 2:
        return None

    # every window joins the closest voice; a lone window between two of another voice in
    # the same segment is almost always noise, so it follows its neighbours
    cents = {k: centroid(v) for k, v in major.items()}
    for w in good:
        w.label = max(cents, key=lambda k: float(cents[k] @ w.emb))
    for i in range(1, len(good) - 1):
        a, w, b = good[i - 1], good[i], good[i + 1]
        if a.seg == w.seg == b.seg and a.label == b.label != w.label:
            w.label = a.label
    # windows without a usable voiceprint take the label of the closest one in time
    for w in wins:
        if w.label is None or w.emb is None:
            w.label = min(good, key=lambda g: abs(g.start - w.start)).label

    # rebuild segments: windowed segments from their windows, short ones from the nearest
    # window in time (a short reply belongs with whoever spoke around it)
    by_seg: dict[int, list[_Window]] = {}
    for w in wins:
        by_seg.setdefault(w.seg, []).append(w)
    parts: list[SpeakerSegment] = []
    for i, seg in segs:
        ws = by_seg.get(i)
        if ws:
            for w in ws:
                if parts and parts[-1].speaker == w.label and abs(parts[-1].end - w.start) < 1e-6:
                    parts[-1] = SpeakerSegment(parts[-1].start, w.end, w.label)
                else:
                    parts.append(SpeakerSegment(w.start, w.end, w.label))
            continue
        mid = (seg.start + seg.end) / 2
        nearest = min(good, key=lambda w: abs((w.start + w.end) / 2 - mid))
        parts.append(SpeakerSegment(seg.start, seg.end, nearest.label))
    return parts
