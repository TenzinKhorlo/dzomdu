"""Human transcript corrections; model outputs and voiceprints stay separate."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from .models import MeetingRecord, SpeakerAssignment
from .notes.render import render_transcript
from .persistence import meeting_locked
from .vault import atomic_write_text


class TranscriptConflict(ValueError):
    pass


class TranscriptEdit(BaseModel):
    model_config = {"extra": "forbid"}

    turn_ids: list[str] = Field(default_factory=list, max_length=1000)
    speaker: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, max_length=120)
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    rename_speaker: bool = False


class TranscriptUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    revision: int = Field(ge=0)
    edits: list[TranscriptEdit] = Field(min_length=1, max_length=1000)


class LiveSpeakerEdit(BaseModel):
    model_config = {"extra": "forbid"}

    segment_ids: list[int] = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=120)
    rename_speaker: bool = False
    revisions: dict[int, int] = Field(default_factory=dict)


def clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name or len(name) > 120 or any(c in name for c in "[]|^#"):
        raise ValueError("Enter a speaker name without note-link characters")
    return name


def apply_edit(record: MeetingRecord, edit: TranscriptEdit) -> None:
    turns = {turn.id: turn for turn in record.turns}
    if any(tid not in turns for tid in edit.turn_ids):
        raise ValueError("One of these transcript turns no longer exists")
    if edit.speaker is not None and edit.speaker not in record.assignments:
        raise ValueError("This speaker no longer exists")
    if edit.rename_speaker:
        if edit.speaker is None or edit.name is None or edit.text is not None:
            raise ValueError("Choose a speaker and a name to rename this voice")
        assignment = record.assignments[edit.speaker]
        assignment.name = clean_name(edit.name) if edit.name.strip() else None
        assignment.suggestion = assignment.speaker_id = assignment.score = None
        assignment.status = "confirmed" if assignment.name else "unknown"
        return
    if not edit.turn_ids or (edit.name is None and edit.speaker is None and edit.text is None):
        raise ValueError("Choose a turn and a correction")
    if edit.text is not None and (len(edit.turn_ids) != 1 or not edit.text.strip()):
        raise ValueError("Correct one nonempty transcript turn at a time")
    target = edit.speaker
    if edit.name is not None:
        name = clean_name(edit.name)
        target = next((key for key, a in record.assignments.items() if a.name == name), None)
        if target is None:
            target = f"MANUAL_{len(record.assignments)}"
            while target in record.assignments:
                target += "_"
            record.assignments[target] = SpeakerAssignment(
                cluster=target, name=name, status="confirmed", unknown_label="Unidentified speaker"
            )
    for tid in edit.turn_ids:
        if target is not None:
            turns[tid].speaker = target
        if edit.text is not None:
            turns[tid].text = edit.text.strip()


def replace_note_transcript(text: str, record: MeetingRecord) -> str:
    """Replace only the transcript section; retain summaries, checked tasks and user prose."""
    match = re.search(r"^## Transcript[ \t]*\r?$", text, re.MULTILINE)
    if match is None:
        return text.rstrip() + "\n\n## Transcript\n\n" + render_transcript(record) + "\n"
    rest = text[match.end() :]
    next_heading = re.search(r"^#{1,2} ", rest, re.MULTILINE)
    suffix = rest[next_heading.start() :] if next_heading else ""
    return text[: match.end()].rstrip("\r") + "\n\n" + render_transcript(record) + "\n\n" + suffix


@meeting_locked
def save_corrections(cfg, meeting_id: str, update: TranscriptUpdate) -> MeetingRecord:
    # Resolve identity from the configured directory, never interpolate a request path.
    path = next(
        (p for p in cfg.meetings_dir.glob("*.json") if not p.is_symlink() and p.stem == meeting_id),
        None,
    )
    if path is None:
        raise FileNotFoundError("This meeting no longer exists")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("transcript_revision", 0) != update.revision:
        raise TranscriptConflict("The transcript changed elsewhere. Reload before saving.")
    record = MeetingRecord.from_dict({k: v for k, v in data.items() if not k.startswith("_")})
    original_record = copy.deepcopy(record.to_dict())
    for edit in update.edits:
        apply_edit(record, edit)
    if record.to_dict() == original_record:
        return record
    used = {turn.speaker for turn in record.turns}
    record.assignments = {key: a for key, a in record.assignments.items() if key in used}
    record.transcript_revision += 1
    record.notes_stale = True
    original_note = None
    note = Path(record.note_path) if record.note_path else None
    if note is not None:
        if note.is_symlink() or not note.resolve().is_relative_to(cfg.vault.resolve()):
            raise ValueError("Move this meeting note into the current vault before editing it")
        if note.exists():
            original_note = note.read_text(encoding="utf-8")
            corrected = replace_note_transcript(original_note, record)
            # Retain the protection for user-edited summaries when the automatic rewrite starts.
            if data.get("_note_sha") == hashlib.sha256(original_note.encode()).hexdigest():
                data["_note_sha"] = hashlib.sha256(corrected.encode()).hexdigest()
            atomic_write_text(note, corrected)
    data.update(record.to_dict())
    try:
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
    except OSError:
        if original_note is not None and note is not None:
            atomic_write_text(note, original_note)
        raise
    return record
