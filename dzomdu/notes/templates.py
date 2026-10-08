"""Minutes templates: Markdown files with YAML frontmatter and a Jinja2 body.

Frontmatter keys:
  name          display name
  description   one line shown in `dzomdu templates`
  instructions  style guidance passed to the LLM (tone, length, audience)
  sections      optional extra things to extract, as a mapping of key -> {title, type,
                description}. type is text, list or items ({title, text} pairs). The values
                are available in the body as notes.extra.<key>.

The body lays out the extracted notes. Available in the body:
  notes            the MeetingNotes (summary, topics, decisions, action_items, open_questions,
                   next_meeting)
  meeting          title, date, date_long (January 14, 2026), duration, minutes, project,
                   attendees, unknown_speakers
  role(name)       the role written in that person's profile, or ""
  cite(item)       timestamp links to the transcript turns an item came from
                   (cite(item, wrap=False) omits the parentheses)
  person(name)     [[wikilink]] for known people, plain text otherwise
  task(item)       an action item formatted for the Obsidian Tasks plugin
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from ..llm.schema import SECTION_TYPES, SectionSpec
from ..vault import dump_frontmatter, split_frontmatter


@dataclass
class MinutesTemplate:
    key: str
    name: str
    description: str
    instructions: str
    body: str
    source: str
    sections: list[SectionSpec] = field(default_factory=list)


def _parse_sections(raw: object) -> list[SectionSpec]:
    """Tolerant: a malformed entry is skipped so one typo can't hide the whole template."""
    out: list[SectionSpec] = []
    if not isinstance(raw, dict):
        return out
    for key, spec in raw.items():
        spec = spec if isinstance(spec, dict) else {}
        kind = str(spec.get("type", "text"))
        out.append(
            SectionSpec(
                key=str(key),
                title=str(spec.get("title") or key),
                type=kind if kind in SECTION_TYPES else "text",
                description=str(spec.get("description", "")).strip(),
            )
        )
    return out


def parse_template(key: str, text: str, source: str) -> MinutesTemplate:
    meta, body = split_frontmatter(text)
    return MinutesTemplate(
        key=key,
        name=str(meta.get("name", key)),
        description=str(meta.get("description", "")),
        instructions=str(meta.get("instructions", "")).strip(),
        body=body,
        source=source,
        sections=_parse_sections(meta.get("sections")),
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


def builtin_text(key: str) -> str | None:
    """The shipped version of a built-in template, or None for a custom one."""
    path = _builtin_dir() / f"{key}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def template_key(name: str) -> str:
    """A file-name-safe key for a new template, e.g. 'Weekly Sync!' -> 'weekly-sync'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def section_key(title: str) -> str:
    """A name usable in a layout, e.g. 'Key takeaways' -> 'key_takeaways'."""
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40]


def template_text(
    name: str,
    description: str,
    instructions: str,
    body: str,
    sections: list[SectionSpec] | None = None,
) -> str:
    meta: dict = {"name": name.strip(), "description": description.strip()}
    if instructions.strip():
        meta["instructions"] = instructions.strip()
    if sections:
        meta["sections"] = {
            s.key: {"title": s.title, "type": s.type, "description": s.description}
            for s in sections
        }
    return dump_frontmatter(meta) + body.strip("\n") + "\n"
