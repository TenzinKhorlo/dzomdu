"""Minutes templates: Markdown files with YAML frontmatter and a Jinja2 body.

Frontmatter keys:
  name          display name
  description   one line shown in `dzomdu templates`
  instructions  style guidance passed to the LLM (tone, length, audience)

The body lays out the extracted notes. Available in the body:
  notes            the MeetingNotes (summary, topics, decisions, action_items, open_questions,
                   next_meeting)
  meeting          title, date, duration, project, attendees, unknown_speakers
  cite(item)       timestamp links to the transcript turns an item came from
                   (cite(item, wrap=False) omits the parentheses)
  person(name)     [[wikilink]] for known people, plain text otherwise
  task(item)       an action item formatted for the Obsidian Tasks plugin
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ..vault import split_frontmatter


@dataclass
class MinutesTemplate:
    key: str
    name: str
    description: str
    instructions: str
    body: str
    source: str


def parse_template(key: str, text: str, source: str) -> MinutesTemplate:
    meta, body = split_frontmatter(text)
    return MinutesTemplate(
        key=key,
        name=str(meta.get("name", key)),
        description=str(meta.get("description", "")),
        instructions=str(meta.get("instructions", "")).strip(),
        body=body,
        source=source,
    )


def _builtin_dir():
    return resources.files("dzomdu.notes") / "templates"


def list_templates(vault_templates: Path | None) -> list[MinutesTemplate]:
    found: dict[str, MinutesTemplate] = {}
    for item in _builtin_dir().iterdir():
        if item.name.endswith(".md"):
            key = item.name[:-3]
            found[key] = parse_template(key, item.read_text(encoding="utf-8"), "built-in")
    if vault_templates and vault_templates.is_dir():
        for path in sorted(vault_templates.glob("*.md")):
            found[path.stem] = parse_template(
                path.stem, path.read_text(encoding="utf-8"), str(path)
            )
    return sorted(found.values(), key=lambda t: t.key)


def load_template(key: str, vault_templates: Path | None) -> MinutesTemplate:
    """Vault templates (editable in Obsidian) override the built-in ones of the same name."""
    if vault_templates:
        path = vault_templates / f"{key}.md"
        if path.exists():
            return parse_template(key, path.read_text(encoding="utf-8"), str(path))
    builtin = _builtin_dir() / f"{key}.md"
    if builtin.is_file():
        return parse_template(key, builtin.read_text(encoding="utf-8"), "built-in")
    available = ", ".join(t.key for t in list_templates(vault_templates))
    raise KeyError(f"No template called {key!r}. Available: {available}")
