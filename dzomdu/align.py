"""Combine ASR words with diarization segments into speaker turns."""

from __future__ import annotations

import bisect
import re

from .models import SpeakerSegment, Turn, Word


def assign_speakers(
    words: list[Word], segments: list[SpeakerSegment], max_distance: float = 1.0
) -> list[str | None]:
    """Give each word the speaker whose segment overlaps it most.

    Words that fall in a gap (common with exclusive diarization) take the nearest segment
    within `max_distance` seconds; otherwise None.
    """
    segments = sorted(segments, key=lambda s: s.start)
    starts = [s.start for s in segments]
    labels: list[str | None] = []
    for word in words:
        idx = bisect.bisect_right(starts, word.end)
        best: str | None = None
        best_overlap = 0.0
        nearest: str | None = None
        nearest_dist = max_distance
        # segments are sorted by start; scan backwards over those starting before word end
        for j in range(idx - 1, max(-1, idx - 8), -1):
            seg = segments[j]
            overlap = min(seg.end, word.end) - max(seg.start, word.start)
            if overlap > best_overlap:
                best, best_overlap = seg.speaker, overlap
            dist = max(0.0, word.start - seg.end, seg.start - word.end)
            if dist < nearest_dist:
                nearest, nearest_dist = seg.speaker, dist
        if best is None and idx < len(segments):  # next segment may start just after the word
            dist = segments[idx].start - word.end
            if dist < nearest_dist:
                nearest = segments[idx].speaker
        labels.append(best if best is not None else nearest)
    return labels


def smooth_labels(
    words: list[Word], labels: list[str | None], max_island: float = 0.6
) -> list[str | None]:
    """Remove short label "islands": a brief run of another speaker inside one speaker's turn
    is almost always a diarization boundary error, so it is reassigned to the surrounding
    speaker. Unlabelled words inherit the previous label."""
    out = list(labels)
    for i, label in enumerate(out):
        if label is None and i > 0:
            out[i] = out[i - 1]
    if out and out[0] is None:
        first = next((lab for lab in out if lab is not None), None)
        out = [first if lab is None else lab for lab in out]

    i = 0
    while i < len(out):
        j = i
        while j + 1 < len(out) and out[j + 1] == out[i]:
            j += 1
        if 0 < i and j < len(out) - 1 and out[i - 1] == out[j + 1] != out[i]:
            island = words[j].end - words[i].start
            if island <= max_island:
                for k in range(i, j + 1):
                    out[k] = out[i - 1]
                # re-scan from the start of the merged run
                i = max(0, i - 1)
                while i > 0 and out[i - 1] == out[i]:
                    i -= 1
                continue
        i = j + 1
    return out


_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?%)\]}])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[{])\s+")


def join_words(texts: list[str]) -> str:
    text = " ".join(t.strip() for t in texts if t.strip())
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _SPACE_AFTER_OPEN.sub(r"\1", text)


def build_turns(
    words: list[Word], labels: list[str | None], max_pause: float = 4.0, max_turn: float = 90.0
) -> list[Turn]:
    """Group consecutive words of the same speaker into turns. A long pause or a very long
    monologue starts a new turn (a new paragraph) so citations stay precise."""
    turns: list[Turn] = []
    current: list[Word] = []
    current_label: str | None = None

    def flush() -> None:
        if current:
            turns.append(
                Turn(
                    id=f"t{len(turns) + 1}",
                    speaker=current_label or "UNKNOWN",
                    start=round(current[0].start, 2),
                    end=round(current[-1].end, 2),
                    text=join_words([w.text for w in current]),
                )
            )

    for word, label in zip(words, labels, strict=True):
        if current:
            pause = word.start - current[-1].end
            too_long = word.end - current[0].start > max_turn and _ends_sentence(current[-1])
            if label != current_label or pause > max_pause or too_long:
                flush()
                current = []
        if not current:
            current_label = label
        current.append(word)
    flush()
    return turns


def _ends_sentence(word: Word) -> bool:
    return word.text.rstrip().endswith((".", "?", "!"))


def align(words: list[Word], segments: list[SpeakerSegment]) -> list[Turn]:
    labels = smooth_labels(words, assign_speakers(words, segments))
    return build_turns(words, labels)
