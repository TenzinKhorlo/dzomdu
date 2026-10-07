"""What the LLM extracts from a meeting. Templates only lay this data out."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Cited(BaseModel):
    source_turns: list[str] = Field(
        default_factory=list, description="Ids of the transcript turns this is based on, e.g. t12"
    )


class Topic(Cited):
    title: str
    points: list[str] = Field(default_factory=list, description="Key points discussed")


class Decision(Cited):
    decision: str


class ActionItem(Cited):
    task: str
    owner: str | None = Field(None, description="Person responsible, only if stated")
    due: str | None = Field(None, description="Due date as said; YYYY-MM-DD if a date is clear")


class MeetingNotes(BaseModel):
    title: str | None = Field(None, description="Short meeting title if the topic is clear")
    summary: str = Field(description="Concise summary of the meeting")
    topics: list[Topic] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_meeting: str | None = None

    def cited_items(self) -> list[Cited]:
        return [*self.topics, *self.decisions, *self.action_items]


def notes_schema() -> dict[str, Any]:
    return MeetingNotes.model_json_schema()
