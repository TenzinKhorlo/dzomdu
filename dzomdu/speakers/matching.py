"""Turn anonymous diarization clusters into known people."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..audio import Audio
from ..diarize import Diarizer, l2_normalize
from ..models import SpeakerAssignment, SpeakerSegment


@dataclass
class ClusterVoice:
    """Embeddings for one diarization cluster in one meeting."""

    cluster: str
    embedding: np.ndarray | None  # L2-normalised mean of the segment embeddings
    segment_embeddings: np.ndarray  # (k, dim)
    clip: tuple[float, float] | None  # best reference clip (start, end) in the meeting
    speech_seconds: float = 0.0
    segments_used: list[tuple[float, float]] = field(default_factory=list)


def cluster_voices(
    audio: Audio,
    segments: list[SpeakerSegment],
    diarizer: Diarizer,
    min_duration: float = 1.5,
    max_segments: int = 12,
    clip_duration: float = 8.0,
) -> dict[str, ClusterVoice]:
    """Embed the longest clean segments of each cluster and average them."""
    by_cluster: dict[str, list[SpeakerSegment]] = {}
    for seg in segments:
        by_cluster.setdefault(seg.speaker, []).append(seg)

    voices: dict[str, ClusterVoice] = {}
    for cluster, segs in by_cluster.items():
        total = sum(s.duration for s in segs)
        candidates = sorted(segs, key=lambda s: s.duration, reverse=True)
        chosen = [s for s in candidates if s.duration >= min_duration][:max_segments]
        if not chosen:  # a speaker who only said short things: use what there is
            chosen = candidates[:max_segments]
        # cap very long segments so one monologue doesn't dominate the average
        spans = [(s.start, min(s.end, s.start + 20.0)) for s in chosen]
        waves = [audio.slice(a, b) for a, b in spans]
        embs = diarizer.embed(waves, audio.sample_rate) if waves else np.zeros((0, 1))
        ok = np.all(np.isfinite(embs), axis=1) if embs.size else np.zeros(0, dtype=bool)
        embs = embs[ok]
        used = [span for span, good in zip(spans, ok, strict=True) if good]
        mean = l2_normalize(embs.mean(axis=0)) if len(embs) else None
        longest = chosen[0]
        clip = (longest.start, min(longest.end, longest.start + clip_duration))
        voices[cluster] = ClusterVoice(
            cluster=cluster,
            embedding=mean,
            segment_embeddings=embs,
            clip=clip,
            speech_seconds=total,
            segments_used=used,
        )
    return voices


def similarity(query: np.ndarray, references: np.ndarray, top_k: int = 3) -> float:
    """Score a cluster against one person's stored embeddings: the mean of the top-k cosine
    similarities. Robust to a few stored samples being from a bad mic or a cold."""
    sims = references @ query
    k = min(top_k, len(sims))
    return float(np.sort(sims)[-k:].mean())


@dataclass
class LibraryEntry:
    speaker_id: int
    name: str
    embeddings: np.ndarray


def match_clusters(
    voices: dict[str, ClusterVoice],
    library: list[LibraryEntry],
    accept_threshold: float,
    suggest_threshold: float,
    first_seen_order: list[str] | None = None,
) -> dict[str, SpeakerAssignment]:
    """Assign each cluster to at most one person and each person to at most one cluster
    (greedy on similarity), then label by threshold: auto / suggested / unknown."""
    clusters = first_seen_order or list(voices)
    pairs: list[tuple[float, str, LibraryEntry]] = []
    for cluster in clusters:
        voice = voices.get(cluster)
        if voice is None or voice.embedding is None:
            continue
        for entry in library:
            if len(entry.embeddings):
                pairs.append((similarity(voice.embedding, entry.embeddings), cluster, entry))
    pairs.sort(key=lambda p: p[0], reverse=True)

    assignments: dict[str, SpeakerAssignment] = {}
    taken: set[int] = set()
    best_score: dict[str, float] = {}
    for score, cluster, entry in pairs:
        best_score.setdefault(cluster, score)
        if cluster in assignments or entry.speaker_id in taken or score < suggest_threshold:
            continue
        auto = score >= accept_threshold
        assignments[cluster] = SpeakerAssignment(
            cluster=cluster,
            name=entry.name if auto else None,
            speaker_id=entry.speaker_id,
            score=round(score, 4),
            status="auto" if auto else "suggested",
            suggestion=None if auto else entry.name,
        )
        taken.add(entry.speaker_id)

    # Every cluster that isn't auto-identified gets a stable "Unknown speaker N" label, used
    # if a suggestion is rejected. Numbered in order of first appearance.
    unknown_n = 0
    for cluster in clusters:
        current = assignments.get(cluster)
        if current is not None and current.status == "auto":
            continue
        unknown_n += 1
        label = f"Unknown speaker {unknown_n}"
        if current is None:
            assignments[cluster] = SpeakerAssignment(
                cluster=cluster,
                score=round(best_score[cluster], 4) if cluster in best_score else None,
                status="unknown",
                unknown_label=label,
            )
        else:
            current.unknown_label = label
    return assignments
