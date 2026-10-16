"""What the LLM extracts from a meeting. Templates only lay this data out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Cited(BaseModel):
    source_turns: list[str] = Field(
        default_factory=list, description="Ids of the transcript turns this is based on, e.g. t12"
    )


class Topic(Cited):
    title: str
    points: list[str] = Field(default_factory=list, description="Key points discussed")

    @model_validator(mode="before")
    @classmethod
    def normalise_cited_points(cls, data: Any) -> Any:
        """Some models cite individual bullet objects instead of the topic itself.

        Keep their text and promote the citations to the topic, which is how our layouts
        represent them. Other malformed values still go through normal validation.
        """
        if not isinstance(data, dict) or not isinstance(data.get("points"), list):
            return data
        sources = data.get("source_turns", [])
        if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
            return data
        sources = list(sources)
        points = []
        for point in data["points"]:
            if isinstance(point, dict) and isinstance(point.get("text"), str):
                refs = point.get("source_turns", [])
                if isinstance(refs, list) and all(isinstance(s, str) for s in refs):
                    points.append(point["text"])
                    sources.extend(refs)
                    continue
            points.append(point)
        return {**data, "points": points, "source_turns": list(dict.fromkeys(sources))}


class Decision(Cited):
    decision: str


class ActionItem(Cited):
    task: str = Field(min_length=1, description="The specific work agreed in the transcript")
    owner: str | None = Field(None, description="Person responsible, only if stated")
    due: str | None = Field(None, description="Due date as said; YYYY-MM-DD if a date is clear")

    @field_validator("task")
    @classmethod
    def require_task_text(cls, task: str) -> str:
        task = task.strip()
        if not task:
            raise ValueError("Task must describe the agreed work")
        return task

    @model_validator(mode="before")
    @classmethod
    def normalise_task_name(cls, data: Any) -> Any:
        """Accept a clearly named task under a common alternate key, without inventing one."""
        if not isinstance(data, dict) or "task" in data:
            return data
        candidates = {
            data[key].strip()
            for key in ("action", "action_item", "description", "text")
            if isinstance(data.get(key), str) and data[key].strip()
        }
        if len(candidates) == 1:
            return {**data, "task": candidates.pop()}
        return data


SECTION_TYPES = ("text", "list", "items")


@dataclass
class SectionSpec:
    """An extra thing a minutes format asks the AI to extract, beyond the standard notes.
    text = a short passage, list = bullet strings, items = a list of {title, text}."""

    key: str
    title: str
    type: str = "text"
    description: str = ""


class MeetingNotes(BaseModel):
    title: str | None = Field(
        None,
        description="A concise title based on the discussion, at most 120 characters",
    )
    summary: str = Field(description="Concise summary of the meeting")
    topics: list[Topic] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_meeting: str | None = None
    # values for the extra sections a format declares, by section key
    extra: dict[str, Any] = Field(default_factory=dict)

    def normalise_extra(self, sections: list[SectionSpec]) -> None:
        """Keep exactly the declared sections, each in its declared shape, so a layout can
        rely on them even when the model left one out or got the shape wrong."""
        clean: dict[str, Any] = {}
        for sec in sections:
            raw = self.extra.get(sec.key)
            if sec.type == "list":
                items = raw if isinstance(raw, list) else ([raw] if raw else [])
                clean[sec.key] = [str(x).strip() for x in items if str(x).strip()]
            elif sec.type == "items":
                items = raw if isinstance(raw, list) else []
                pairs = [
                    x for x in items if isinstance(x, dict) and (x.get("title") or x.get("text"))
                ]
                clean[sec.key] = [
                    {
                        "title": str(x.get("title") or "").strip(),
                        "text": str(x.get("text") or "").strip(),
                    }
                    for x in pairs
                ]
            else:
                clean[sec.key] = str(raw).strip() if raw else ""
        self.extra = clean

    def cited_items(self) -> list[Cited]:
        return [*self.topics, *self.decisions, *self.action_items]


def _section_schema(sec: SectionSpec) -> dict[str, Any]:
    if sec.type == "list":
        shape: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
    elif sec.type == "items":
        shape = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
                "required": ["title", "text"],
            },
        }
    else:
        shape = {"type": "string"}
    return {**shape, "description": sec.description or sec.title}


def notes_schema(sections: list[SectionSpec] | None = None) -> dict[str, Any]:
    schema = MeetingNotes.model_json_schema()
    if sections:
        schema["properties"]["extra"] = {
            "type": "object",
            "properties": {s.key: _section_schema(s) for s in sections},
            "required": [s.key for s in sections],
        }
    return schema
