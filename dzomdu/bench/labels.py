"""Reference labels for benchmarking.

Speaker labels can be an RTTM file or an Audacity label export (start<TAB>end<TAB>Name),
which is the easiest way to hand-label a recording: in Audacity select each stretch of
speech, press Ctrl/Cmd+B, type the speaker's name, then File > Export > Labels.
"""

from __future__ import annotations

from pathlib import Path

from ..models import SpeakerSegment


def read_rttm(path: Path) -> list[SpeakerSegment]:
    segments = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0] == "SPEAKER":
            start, dur = float(parts[3]), float(parts[4])
            segments.append(SpeakerSegment(start, start + dur, parts[7]))
    return sorted(segments, key=lambda s: s.start)


def read_audacity(path: Path) -> list[SpeakerSegment]:
    segments = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        # Audacity adds frequency rows starting with "\" for spectral labels; skip them
        if len(parts) >= 3 and not parts[0].startswith("\\"):
            start, end, name = float(parts[0]), float(parts[1]), parts[2].strip()
            if end > start and name:
                segments.append(SpeakerSegment(start, end, name))
    return sorted(segments, key=lambda s: s.start)


def read_speaker_labels(path: Path) -> list[SpeakerSegment]:
    if path.suffix.lower() == ".rttm":
        return read_rttm(path)
    return read_audacity(path)


def write_rttm(path: Path, file_id: str, segments: list[SpeakerSegment]) -> None:
    lines = [
        f"SPEAKER {file_id} 1 {s.start:.3f} {s.duration:.3f} <NA> <NA> "
        f"{s.speaker.replace(' ', '_')} <NA> <NA>"
        for s in segments
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
