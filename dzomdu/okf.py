"""Open Knowledge Format v0.2 metadata and portable, local-only bundle exports.

The live vault keeps Obsidian conveniences. Exports use ordinary Markdown links
and footnotes, with separate transcript concepts so other OKF consumers can follow
the evidence without Dzomdu, Obsidian, a database or a model server.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import Config
from .models import MeetingRecord, format_timestamp
from .vault import Vault, dump_frontmatter, safe_filename, split_frontmatter

OKF_VERSION = "0.2"


def actor() -> str:
    try:
        return "dzomdu/" + version("dzomdu")
    except PackageNotFoundError:
        return "process:dzomdu"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def meeting_date(date: str) -> str:
    when = datetime.fromisoformat(date)
    # Older records contain local wall time. Interpret it in this installation's
    # timezone; new records retain the explicit offset supplied at capture time.
    if when.tzinfo is None:
        when = when.astimezone()
    return when.isoformat(timespec="minutes")


def knowledge_metadata(record: MeetingRecord, summary: str | None = None) -> dict[str, Any]:
    """Metadata for a newly rendered meeting document; never imply human verification."""
    source = (
        Path(record.source_audio).expanduser().absolute().as_uri()
        if record.source_audio
        else f"Recorded audio for meeting {record.id}"
    )
    return {
        "description": " ".join(summary.split())
        if summary
        else "Speaker-attributed meeting transcript.",
        "date": meeting_date(record.date),
        "status": "draft",
        "generated": {"by": actor(), "at": now_iso()},
        "sources": [{"id": "audio", "resource": source, "title": "Original meeting recording"}],
        "audio_sha256": record.audio_sha,
    }


def _label(text: str) -> str:
    return re.sub(r"([\\`*{}_\[\]<>])", r"\\\1", " ".join(text.split()))


def _url(path: Path) -> str:
    return "/" + quote(path.as_posix(), safe="/")


def _stem(value: str) -> str:
    # A digest prevents distinct names/ids that sanitize alike from overwriting
    # each other; a prefix prevents the reserved index.md/log.md concept names.
    return safe_filename(value)[:80] + "-" + hashlib.sha256(value.encode()).hexdigest()[:12]


_WIKI = re.compile(r"\[\[([^\]\n]+)\]\]")


def _portable_body(body: str, links: dict[str, str], record: MeetingRecord | None = None) -> str:
    used: dict[str, str] = {}
    turns = {t.id: t for t in record.turns} if record else {}

    def replace(match: re.Match) -> str:
        target, _, label = match[1].replace("\\|", "|").partition("|")
        label = label or target
        if target.startswith("#^") and target[2:] in turns:
            tid = target[2:]
            used[tid] = format_timestamp(turns[tid].start)
            return f"[^{tid}]"
        if target in links:
            return f"[{_label(label)}]({links[target]})"
        return _label(label)

    body = _WIKI.sub(replace, body)
    if used and record:
        transcript = _url(Path("transcripts") / f"{_stem(record.id)}.md")
        body = (
            body.rstrip()
            + "\n\n"
            + "\n".join(
                f"[^{tid}]: [{timestamp}]({transcript}#turn-{quote(tid, safe='')})"
                for tid, timestamp in used.items()
            )
            + "\n"
        )
    return body


def export_bundle(cfg: Config, destination: Path) -> int:
    """Export all saved meetings without modifying the vault, records or recordings.

    Build beside the destination and rename only after all reads and writes
    succeed. Require a new destination so exports cannot erase existing data.
    """
    from .dashboard import meeting_tasks
    from .llm.schema import MeetingNotes
    from .notes.render import render_note
    from .notes.templates import load_template

    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Choose a new export folder; the destination already exists")
    vault = Vault(cfg.vault)
    profiles: list[tuple[Path, Path, str]] = []
    links: dict[str, str] = {}
    for path in sorted(vault.people_dir.glob("*.md")):
        target = Path("people") / f"person-{_stem(path.stem)}.md"
        profiles.append((path, target, "person"))
        links[path.stem] = _url(target)
    for folder in sorted(vault.projects_dir.glob("*")):
        path = folder / f"{folder.name}.md"
        if folder.name.startswith(".") or not path.is_file():
            continue
        target = Path("projects") / f"project-{_stem(folder.name)}.md"
        profiles.append((path, target, "project"))
        links[folder.name] = _url(target)
        links[f"Projects/{folder.name}/{folder.name}"] = _url(target)
        links[f"Projects/{folder.name}/{folder.name}.md"] = _url(target)

    records = []
    seen: set[str] = set()
    for path in sorted(cfg.meetings_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        record = MeetingRecord.from_dict({k: v for k, v in data.items() if not k.startswith("_")})
        if record.id in seen:
            raise ValueError(f"Duplicate meeting id: {record.id}")
        seen.add(record.id)
        records.append((record, data))
        if record.note_path:
            note = Path(record.note_path)
            target = _url(Path("meetings") / f"{_stem(record.id)}.md")
            links[note.stem] = target
            if note.is_relative_to(vault.root):
                relative = note.relative_to(vault.root).as_posix()
                links[relative] = target
                links[relative.removesuffix(".md")] = target

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dzomdu-okf-", dir=destination.parent))
    groups: dict[str, list[str]] = {}

    def write(target: Path, meta: dict[str, Any], body: str) -> None:
        path = staging / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_frontmatter(meta) + "\n" + body.strip() + "\n", encoding="utf-8")
        groups.setdefault(target.parts[0], []).append(
            f"* [{_label(str(meta['title']))}]({quote(target.as_posix(), safe='/')})"
            + (f" - {_label(str(meta['description']))}" if meta.get("description") else "")
        )

    try:
        for source, target, kind in profiles:
            meta, body = split_frontmatter(source.read_text(encoding="utf-8"))
            meta.setdefault("type", kind)
            meta.setdefault("title", source.stem)
            if kind == "project":
                members = vault.project_members(source.parent.name)
                if members:
                    meta["team"] = members
            if meta.get("status") not in (None, "draft", "stable", "deprecated"):
                meta[kind + "_status"] = meta.pop("status")
            write(target, meta, _portable_body(body, links))

        for record, data in records:
            transcript_path = Path("transcripts") / f"{_stem(record.id)}.md"
            note_path = Path("meetings") / f"{_stem(record.id)}.md"
            transcript_url = _url(transcript_path)
            transcript_meta = {
                "type": "Meeting Transcript",
                "title": record.title or "Untitled meeting",
                **knowledge_metadata(record),
                "tags": ["meeting", "transcript"],
                "dzomdu_id": record.id,
                "models": {"asr": record.asr_model, "diarization": record.diarization_model},
            }
            # A scope descriptor is legal OKF provenance. Do not expose machine-
            # specific paths or include recordings/biometric data in the export.
            transcript_meta["sources"] = [
                {
                    "id": "audio",
                    "resource": f"Recorded audio with SHA-256 {record.audio_sha}",
                    "title": "Original meeting recording (not included)",
                }
            ]
            transcript = [
                f"# {_label(record.title or 'Untitled meeting')}",
                f"Meeting notes: [{_label(record.title or 'Untitled meeting')}]({_url(note_path)})",
            ]
            for turn in record.turns:
                who = record.name_for(turn.speaker)
                speaker = f"[{_label(who)}]({links[who]})" if who in links else _label(who)
                transcript.extend(
                    [
                        f'<a id="turn-{html.escape(quote(turn.id, safe=""), quote=True)}"></a>',
                        f"**{speaker}** `{format_timestamp(turn.start)}` {turn.text}",
                    ]
                )
            write(transcript_path, transcript_meta, "\n\n".join(transcript))

            source = Path(record.note_path) if record.note_path else None
            if source and source.is_file():
                original = source.read_bytes()
                text = original.decode("utf-8").replace("\r\n", "\n")
                meta, body = split_frontmatter(text)
                if data.get("_note_sha") != hashlib.sha256(original).hexdigest():
                    # Keep an edited note's content, but its old generation and
                    # verification claims may not describe the current version.
                    meta.pop("generated", None)
                    meta.pop("verified", None)
            else:
                notes = MeetingNotes.model_validate(data["_notes"]) if data.get("_notes") else None
                template = (
                    load_template(cfg.default_template, vault.templates_dir) if notes else None
                )
                meta, body = split_frontmatter(render_note(record, notes, template))
            meta["type"] = "Meeting Notes" if data.get("_notes") else "Meeting"
            meta["title"] = record.title or "Untitled meeting"
            meta["date"] = meeting_date(record.date)
            meta.setdefault("description", "Meeting notes and speaker-attributed transcript.")
            meta.setdefault("status", "draft")
            if meta["status"] not in ("draft", "stable", "deprecated"):
                meta["meeting_status"] = meta["status"]
                meta["status"] = "draft"
            meta.pop("audio", None)
            meta["exported"] = {"by": "process:dzomdu-okf-export", "at": now_iso()}
            other_sources = [
                source
                for source in meta.get("sources", [])
                if source.get("id") not in {"audio", "transcript", *(t.id for t in record.turns)}
            ]
            meta["sources"] = [
                {
                    "id": "transcript",
                    "resource": transcript_url,
                    "title": "Speaker-attributed meeting transcript",
                }
            ]
            for turn in record.turns:
                meta["sources"].append(
                    {
                        "id": turn.id,
                        "resource": f"{transcript_url}#turn-{quote(turn.id, safe='')}",
                        "title": (
                            f"{record.name_for(turn.speaker)} at {format_timestamp(turn.start)}"
                        ),
                    }
                )
            meta["sources"].extend(other_sources)
            for key in ("project", "attendees"):
                if isinstance(meta.get(key), str):
                    meta[key] = _portable_body(meta[key], links)
                elif isinstance(meta.get(key), list):
                    meta[key] = [_portable_body(str(value), links) for value in meta[key]]
            # Keep custom/edited sections, including any inline transcript. Its
            # Obsidian block markers become real Markdown HTML fragment anchors.
            body = re.sub(
                r" \^(t\d+)(?=\s*$)", lambda m: f'\n\n<a id="{m[1]}"></a>', body, flags=re.MULTILINE
            )
            write(note_path, meta, _portable_body(body, links, record))
            for task in meeting_tasks(data):
                if not task.id:
                    continue
                task_meta = {
                    "type": "Task",
                    "title": task.text,
                    "status": "draft",
                    "task_status": "completed" if task.done else "open",
                    "reminder_date": task.reminder_date,
                    "due": task.due,
                    "owner": task.owner,
                    "project": record.project,
                    "sources": [
                        {
                            "id": "meeting",
                            "resource": _url(note_path),
                            "title": record.title or "Untitled meeting",
                        }
                    ],
                }
                task_body = f"# {_label(task.text)}\n\n"
                task_body += f"- [{'x' if task.done else ' '}] {_label(task.text)}\n\n"
                task_body += (
                    f"Source: [{_label(record.title or 'Untitled meeting')}]({_url(note_path)})\n"
                )
                if record.project and record.project in links:
                    task_body += f"\nProject: [{_label(record.project)}]({links[record.project]})\n"
                write(Path("tasks") / f"{task.id}.md", task_meta, task_body)

        index = dump_frontmatter({"okf_version": OKF_VERSION}) + "\n"
        index += "# Dzomdu knowledge bundle\n\n"
        index += (
            "Recordings and voiceprints are not included. "
            "Machine-generated content is unverified.\n\n"
        )
        for group, entries in groups.items():
            index += f"# {group.title()}\n\n" + "\n".join(entries) + "\n\n"
        (staging / "index.md").write_text(index, encoding="utf-8")
        if destination.exists() or destination.is_symlink():
            raise ValueError(
                "The destination was created during export; choose a new export folder"
            )
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return len(records)
