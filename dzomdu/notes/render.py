"""Render a meeting into an Obsidian-friendly Markdown note.

Transcript turns end with a block id (`^t12`), and citations link to them
(`[[#^t12|00:14:32]]`), so every decision and action item can be checked against what was
actually said with one click.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import jinja2
import yaml

from ..llm.schema import ActionItem, Cited, MeetingNotes, SectionSpec
from ..models import MeetingRecord, format_duration, format_timestamp
from ..okf import knowledge_metadata
from ..vault import dump_frontmatter
from .templates import MinutesTemplate

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def retitle_note(text: str, title: str) -> str:
    """Edit only the title metadata and opening heading; retain user-written contents."""
    newline = "\r\n" if "\r\n" in text else "\n"
    entry = "title: " + json.dumps(title, ensure_ascii=False) + newline
    match = re.match(r"\A---\r?\n(.*?)^---[ \t]*(?:\r?\n|$)", text, re.S | re.M)
    if match:
        metadata = match[1]
        try:
            node = yaml.compose(metadata, Loader=yaml.SafeLoader)
        except yaml.YAMLError as exc:
            raise ValueError("Fix this note's frontmatter before renaming it") from exc
        if node is not None and (not isinstance(node, yaml.MappingNode) or node.flow_style):
            raise ValueError("This note needs a block of frontmatter fields before renaming it")
        titles = [(key, value) for key, value in node.value if key.value == "title"] if node else []
        if len(titles) > 1:
            raise ValueError("Remove duplicate title fields from this note before renaming it")
        lines = metadata.splitlines(keepends=True)
        if titles:
            key, value = titles[0]
            end = value.end_mark.line + bool(value.end_mark.column)
            lines[key.start_mark.line : end] = [entry]
        else:
            lines.insert(0, entry)
        header = text[: match.start(1)] + "".join(lines) + text[match.end(1) : match.end()]
        body = text[match.end() :]
    else:
        header, body = f"---{newline}{entry}---{newline}", text
    body = re.sub(r"\A((?:[ \t]*\r?\n)*)# [^\r\n]*", lambda m: m[1] + "# " + title, body, count=1)
    return header + body


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
    def __init__(
        self,
        record: MeetingRecord,
        known_people: list[str] | None = None,
        roles: dict[str, str] | None = None,
    ):
        self.roles = {k.casefold(): v for k, v in (roles or {}).items()}
        self.turn_start = {t.id: t.start for t in record.turns}
        # anyone known (in the vault or with a voiceprint) is linked, e.g. an owner who was absent
        self.people = (
            {name.casefold(): name for name in known_people or []}
            | {a.name.casefold(): a.name for a in record.assignments.values() if a.name}
            | {name.casefold(): name for name in record.attendees}
        )

    def cite(self, item: Cited, wrap: bool = True) -> str:
        links = [
            f"[[#^{tid}|{format_timestamp(self.turn_start[tid])}]]"
            for tid in item.source_turns
            if tid in self.turn_start
        ]
        if not links:
            return ""
        return f"({', '.join(links)})" if wrap else ", ".join(links)

    def role(self, name: str | None) -> str:
        return self.roles.get((name or "").strip().casefold(), "")

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
    when = datetime.fromisoformat(record.date)
    return {
        "title": record.title,
        "date": record.date,
        "date_long": f"{when:%B} {when.day}, {when.year}",
        "duration": format_duration(record.duration),
        "minutes": max(1, round(record.duration / 60)),
        "project": record.project,
        "attendees": known,
        "unknown_speakers": unknown,
    }


def render_note(
    record: MeetingRecord,
    notes: MeetingNotes | None,
    template: MinutesTemplate | None,
    llm_model: str | None = None,
    known_people: list[str] | None = None,
    roles: dict[str, str] | None = None,
) -> str:
    ctx = meeting_context(record)
    meta: dict[str, Any] = {
        "type": "meeting",
        "title": record.title,
        **knowledge_metadata(record, notes.summary if notes else None),
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
        notes = notes.model_copy(deep=True)
        notes.normalise_extra(template.sections)  # every declared field exists, in its shape
        helpers = _Helpers(record, known_people, roles)
        body = (
            _env()
            .from_string(template.body)
            .render(
                notes=notes,
                meeting=ctx,
                cite=helpers.cite,
                person=helpers.person,
                role=helpers.role,
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


def _sample_extra(sections: list[SectionSpec]) -> dict:
    out: dict = {}
    for sec in sections:
        if sec.type == "list":
            out[sec.key] = ["First point", "Second point"]
        elif sec.type == "items":
            out[sec.key] = [{"title": "A headline", "text": "A sentence about it."}]
        else:
            out[sec.key] = "Some text"
    return out


def check_template_body(body: str, sections: list[SectionSpec] | None = None) -> None:
    """Render a layout with made-up notes so mistakes surface when it is saved, not when a real
    meeting is processed. Raises jinja2.TemplateError."""
    from ..llm.schema import Decision, Topic

    notes = MeetingNotes(
        title="Sample",
        summary="A short summary.",
        topics=[Topic(title="Budget", points=["One point", "Another point"], source_turns=["t1"])],
        decisions=[Decision(decision="Approve the plan", source_turns=["t1"])],
        action_items=[ActionItem(task="Send the draft", owner="Alice", due="2026-01-31")],
        open_questions=["Who owns the rollout?"],
        next_meeting="Next week",
        extra=_sample_extra(sections or []),
    )
    ctx = {
        "title": "Sample meeting",
        "date": "2026-01-01T10:00:00",
        "date_long": "January 1, 2026",
        "duration": "30m",
        "minutes": 30,
        "project": "Sample project",
        "attendees": ["Alice", "Bob"],
        "unknown_speakers": [],
    }
    _env().from_string(body).render(
        notes=notes,
        meeting=ctx,
        cite=lambda item, wrap=True: "([[#^t1|00:00:05]])",
        person=lambda name: f"[[{name}]]" if name else "",
        role=lambda name: "Role",
        task=lambda item: item.task,
    )
