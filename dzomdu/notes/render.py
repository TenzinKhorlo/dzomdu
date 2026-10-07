"""Render a meeting into an Obsidian-friendly Markdown note.

Transcript turns end with a block id (`^t12`), and citations link to them
(`[[#^t12|00:14:32]]`), so every decision and action item can be checked against what was
actually said with one click.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import jinja2

from ..llm.schema import ActionItem, Cited, MeetingNotes
from ..models import MeetingRecord, format_duration, format_timestamp
from ..vault import dump_frontmatter
from .templates import MinutesTemplate

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _env() -> jinja2.Environment:
    return jinja2.Environment(
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def wikilink(name: str) -> str:
    return f"[[{name}]]"


class _Helpers:
    def __init__(self, record: MeetingRecord):
        self.turn_start = {t.id: t.start for t in record.turns}
        self.people = {a.name.casefold(): a.name for a in record.assignments.values() if a.name} | {
            name.casefold(): name for name in record.attendees
        }

    def cite(self, item: Cited, wrap: bool = True) -> str:
        links = [
            f"[[#^{tid}|{format_timestamp(self.turn_start[tid])}]]"
            for tid in item.source_turns
            if tid in self.turn_start
        ]
        if not links:
            return ""
        return f"({', '.join(links)})" if wrap else ", ".join(links)

    def person(self, name: str | None) -> str:
        if not name:
            return ""
        known = self.people.get(name.strip().casefold())
        return wikilink(known) if known else name

    def task(self, item: ActionItem) -> str:
        parts = []
        if item.owner:
            parts.append(self.person(item.owner))
        parts.append(item.task.strip())
        if item.due:
            due = item.due.strip()
            parts.append(f"📅 {due}" if _ISO_DATE.match(due) else f"(due: {due})")
        if cite := self.cite(item):
            parts.append(cite)
        return " ".join(parts)


def render_transcript(record: MeetingRecord) -> str:
    lines = []
    for turn in record.turns:
        assignment = record.assignments.get(turn.speaker)
        who = (
            wikilink(assignment.name)
            if assignment and assignment.name
            else record.name_for(turn.speaker)
        )
        lines.append(f"**{who}** `{format_timestamp(turn.start)}` {turn.text} ^{turn.id}")
    return "\n\n".join(lines)


def meeting_context(record: MeetingRecord) -> dict[str, Any]:
    known = sorted({a.name for a in record.assignments.values() if a.name} | set(record.attendees))
    unknown = sorted({a.display_name for a in record.assignments.values() if not a.name})
    return {
        "title": record.title,
        "date": record.date,
        "duration": format_duration(record.duration),
        "project": record.project,
        "attendees": known,
        "unknown_speakers": unknown,
    }


def render_note(
    record: MeetingRecord,
    notes: MeetingNotes | None,
    template: MinutesTemplate | None,
    llm_model: str | None = None,
) -> str:
    ctx = meeting_context(record)
    when = datetime.fromisoformat(record.date)
    meta: dict[str, Any] = {
        "type": "meeting",
        "title": record.title,
        "date": when.strftime("%Y-%m-%dT%H:%M"),
        "duration": ctx["duration"],
    }
    if record.project:
        meta["project"] = wikilink(record.project)
    meta["attendees"] = [wikilink(n) for n in ctx["attendees"]]
    if ctx["unknown_speakers"]:
        meta["unidentified_speakers"] = ctx["unknown_speakers"]
    if template and notes:
        meta["template"] = template.key
    meta["audio"] = record.source_audio
    meta["dzomdu_id"] = record.id
    meta["models"] = {
        k: v
        for k, v in (
            ("asr", record.asr_model),
            ("diarization", record.diarization_model),
            ("llm", llm_model if notes else None),
        )
        if v
    }
    tags = ["meeting"]
    if record.project:
        tags.append(re.sub(r"[^\w-]+", "-", record.project.lower()).strip("-"))
    meta["tags"] = tags

    parts = [dump_frontmatter(meta), f"# {record.title}\n"]
    if notes and template:
        helpers = _Helpers(record)
        body = (
            _env()
            .from_string(template.body)
            .render(
                notes=notes,
                meeting=ctx,
                cite=helpers.cite,
                person=helpers.person,
                task=helpers.task,
            )
        )
        parts.append(re.sub(r"\n{3,}", "\n\n", body).strip() + "\n")
    else:
        parts.append(
            "## Summary\n\n_Not generated yet. Run `dzomdu regenerate "
            f"{record.id}` once the LLM is available._\n"
        )
    parts.append("## Transcript\n\n" + render_transcript(record) + "\n")
    return "\n".join(parts)
