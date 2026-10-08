"""The Markdown vault: an Obsidian-compatible folder that is the source of truth for notes,
people and projects."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

_INVALID = re.compile(r'[\\/:*?"<>|#^\[\]]')
PLACEHOLDER = re.compile(r"^_.*_$")


def safe_filename(name: str) -> str:
    cleaned = _INVALID.sub("-", name).strip().strip(".")
    return re.sub(r"\s+", " ", cleaned) or "Untitled"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            meta = yaml.safe_load(text[4:end]) or {}
            body = text[end + 4 :].lstrip("\n")
            return (meta if isinstance(meta, dict) else {}), body
    return {}, text


def atomic_write_text(path: Path, text: str) -> None:
    """Write a file so a reader sees either the old content or the new, never a half-written
    one (the dashboard and the API read these files while the pipeline is still saving)."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def dump_frontmatter(meta: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{dumped}---\n"


def section(body: str, heading: str) -> str:
    """Text under `## heading` up to the next heading of the same or higher level, with
    placeholder lines (`_like this_`) removed."""
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", body, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    rest = body[match.end() :]
    nxt = re.search(r"^#{1,2}\s", rest, re.MULTILINE)
    text = rest[: nxt.start()] if nxt else rest
    lines = [ln for ln in text.strip().splitlines() if not PLACEHOLDER.match(ln.strip())]
    return "\n".join(lines).strip()


PERSON_STUB = """# {name}

## Bio

_Role, responsibilities and background. Dzomdu passes this to the LLM as context._
"""

PROJECT_STUB = """# {name}

## Overview

_Goals, scope, team and status. Dzomdu passes this to the LLM as context._

## Glossary

_Names, acronyms and terms used in this project, one per line._
"""


class Vault:
    def __init__(self, root: Path):
        self.root = root

    @property
    def people_dir(self) -> Path:
        return self.root / "People"

    @property
    def projects_dir(self) -> Path:
        return self.root / "Projects"

    @property
    def meetings_dir(self) -> Path:
        return self.root / "Meetings"

    @property
    def templates_dir(self) -> Path:
        return self.root / "Templates" / "Minutes"

    def init(self) -> None:
        for d in (self.people_dir, self.projects_dir, self.meetings_dir, self.templates_dir):
            d.mkdir(parents=True, exist_ok=True)
        defaults = resources.files("dzomdu.notes") / "templates"
        for item in defaults.iterdir():
            if item.name.endswith(".md"):
                target = self.templates_dir / item.name
                if not target.exists():
                    with resources.as_file(item) as src:
                        shutil.copyfile(src, target)

    # -- people -----------------------------------------------------------------------------

    def person_path(self, name: str) -> Path:
        return self.people_dir / f"{safe_filename(name)}.md"

    def ensure_person(
        self,
        name: str,
        role: str | None = None,
        organisation: str | None = None,
        bio: str | None = None,
    ) -> Path:
        path = self.person_path(name)
        if path.exists():
            if role or organisation or bio:
                self.update_person(name, role=role, organisation=organisation, bio=bio)
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "type": "person",
            "role": role or "",
            "organisation": organisation or "",
            "email": "",
            "tags": ["person"],
        }
        body = PERSON_STUB.format(name=name)
        if bio:
            body = body.replace(
                "_Role, responsibilities and background. Dzomdu passes this to the LLM as "
                "context._",
                bio.strip(),
            )
        path.write_text(dump_frontmatter(meta) + "\n" + body, encoding="utf-8")
        return path

    def update_person(
        self,
        name: str,
        role: str | None = None,
        organisation: str | None = None,
        bio: str | None = None,
    ) -> None:
        path = self.person_path(name)
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        if role:
            meta["role"] = role
        if organisation:
            meta["organisation"] = organisation
        if bio:
            if re.search(r"^## Bio\s*$", body, re.MULTILINE):
                body = re.sub(
                    r"(^## Bio\s*$\n)(.*?)(?=^#{1,2}\s|\Z)",
                    lambda m: m.group(1) + "\n" + bio.strip() + "\n\n",
                    body,
                    count=1,
                    flags=re.MULTILINE | re.DOTALL,
                )
            else:
                body = body.rstrip() + f"\n\n## Bio\n\n{bio.strip()}\n"
        path.write_text(dump_frontmatter(meta) + "\n" + body, encoding="utf-8")

    def rename_person(self, old: str, new: str) -> None:
        src, dst = self.person_path(old), self.person_path(new)
        if src.exists() and not dst.exists():
            text = src.read_text(encoding="utf-8").replace(f"# {old}\n", f"# {new}\n", 1)
            dst.write_text(text, encoding="utf-8")
            src.unlink()

    def person_profile(self, name: str) -> dict[str, str]:
        path = self.person_path(name)
        if not path.exists():
            return {"role": "", "organisation": "", "bio": ""}
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        return {
            "role": str(meta.get("role") or ""),
            "organisation": str(meta.get("organisation") or ""),
            "bio": section(body, "Bio"),
        }

    def person_context(self, name: str) -> str:
        path = self.person_path(name)
        if not path.exists():
            return ""
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        role = ", ".join(str(meta[k]) for k in ("role", "organisation") if meta.get(k))
        bio = section(body, "Bio")
        parts = [p for p in (role, bio[:400]) if p]
        return f"- {name}: " + ". ".join(parts) if parts else ""

    # -- projects ---------------------------------------------------------------------------

    def project_dir(self, name: str) -> Path:
        return self.projects_dir / safe_filename(name)

    def ensure_project(self, name: str) -> Path:
        path = self.project_dir(name) / f"{safe_filename(name)}.md"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            meta = {"type": "project", "status": "active", "tags": ["project"]}
            path.write_text(
                dump_frontmatter(meta) + "\n" + PROJECT_STUB.format(name=name), encoding="utf-8"
            )
        return path

    def project_context(self, name: str) -> str:
        path = self.project_dir(name) / f"{safe_filename(name)}.md"
        if not path.exists():
            return ""
        _meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        parts = []
        if overview := section(body, "Overview"):
            parts.append(overview[:1500])
        if glossary := section(body, "Glossary"):
            parts.append("Glossary:\n" + glossary[:1000])
        return "\n\n".join(parts)

    # -- meetings ---------------------------------------------------------------------------

    def meeting_path(self, when: datetime, title: str, project: str | None) -> Path:
        folder = self.project_dir(project) / "Meetings" if project else self.meetings_dir
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{when:%Y-%m-%d} {safe_filename(title)}"
        path = folder / f"{stem}.md"
        n = 2
        while path.exists():
            path = folder / f"{stem} ({n}).md"
            n += 1
        return path
