"""Plain data types shared across the pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

AssignmentStatus = Literal["auto", "suggested", "unknown", "confirmed"]


@dataclass
class Word:
    text: str
    start: float
    end: float
    confidence: float | None = None


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker: str  # anonymous diarization label, e.g. SPEAKER_00

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Turn:
    id: str  # short stable id used for citations, e.g. "t12"
    speaker: str  # diarization label
    start: float
    end: float
    text: str


@dataclass
class SpeakerAssignment:
    cluster: str
    name: str | None = None  # person name, None while unknown
    speaker_id: int | None = None
    score: float | None = None
    status: AssignmentStatus = "unknown"
    unknown_label: str = "Unknown speaker"
    suggestion: str | None = None  # likely person when status == "suggested"

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.suggestion:
            return f"{self.suggestion}?"
        return self.unknown_label

    @property
    def is_known(self) -> bool:
        return self.name is not None


@dataclass
class MeetingRecord:
    """Everything known about one processed meeting. Saved as JSON so notes can be regenerated."""

    id: str
    title: str
    date: str  # ISO 8601 with UTC offset; legacy records may contain local wall time
    source_audio: str
    audio_sha: str
    duration: float
    project: str | None
    turns: list[Turn]
    assignments: dict[str, SpeakerAssignment]
    asr_model: str
    diarization_model: str
    attendees: list[str] = field(default_factory=list)
    note_path: str | None = None
    title_pending: bool = False  # a fallback name awaiting successful note generation

    def name_for(self, cluster: str) -> str:
        assignment = self.assignments.get(cluster)
        return assignment.display_name if assignment else cluster

    def speaking_time(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for turn in self.turns:
            totals[turn.speaker] = totals.get(turn.speaker, 0.0) + (turn.end - turn.start)
        return totals

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetingRecord:
        data = dict(data)
        data["turns"] = [Turn(**t) for t in data["turns"]]
        data["assignments"] = {k: SpeakerAssignment(**v) for k, v in data["assignments"].items()}
        return cls(**data)


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(round(seconds))}s"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes}m"
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}m"
