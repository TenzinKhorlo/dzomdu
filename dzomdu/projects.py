"""Project mutations across the vault, meeting records and app-owned recordings."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from yaml import YAMLError

from . import dashboard
from .chat import ChatStore
from .config import Config
from .persistence import meeting_locked
from .tasks import TaskManager
from .vault import Vault, atomic_write_text, safe_filename

log = logging.getLogger(__name__)


class ProjectConflict(ValueError):
    pass


class ProjectManager:
    def __init__(
        self, cfg: Config, vault: Vault, recordings_dir: Path, chats: ChatStore | None = None
    ):
        self.cfg, self.vault, self.recordings_dir = cfg, vault, recordings_dir
        self.chats = chats

    def folder(self, name: str) -> Path:
        if not name.strip() or name != safe_filename(name):
            raise ValueError("Invalid project name")
        folder = self.vault.project_dir(name)
        if folder.is_symlink():
            raise ProjectConflict(
                "This project folder is a symbolic link and cannot be changed here"
            )
        return folder

    def records(self, name: str) -> list[tuple[Path, dict[str, Any]]]:
        records = []
        for path in self.cfg.meetings_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("project") and safe_filename(data["project"]) == name:
                records.append((path, data))
        return records

    def details(self, name: str) -> dict[str, Any]:
        folder, records = self.folder(name), self.records(name)
        if not folder.is_dir() and not records:
            raise FileNotFoundError("This project no longer exists")
        return {
            "name": name,
            "meetings": len(records),
            "meeting_ids": sorted(r["id"] for _, r in records),
        }

    @meeting_locked
    def set_members(self, name: str, requested: list[str]) -> list[str]:
        self.details(name)
        members, seen = [], set()
        for raw in requested:
            member = " ".join(raw.split())
            if not member or len(member) > 100:
                raise ValueError("Each team member needs a name of up to 100 characters")
            if member.casefold() not in seen:
                members.append(member)
                seen.add(member.casefold())
        self.vault.project_members(name)  # Validate existing metadata before replacing it.
        self.vault.ensure_project(name)
        path = self.folder(name) / ".dzomdu-project.json"
        metadata = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        atomic_write_text(
            path, json.dumps(metadata | {"members": members}, ensure_ascii=False, indent=2)
        )
        return members

    @meeting_locked
    def overview(self, name: str, tasks: TaskManager) -> dict[str, Any]:
        details = self.details(name)
        members = self.vault.project_members(name)
        task_rows = [
            task | {"project": name}
            for task in tasks.list()
            if task["project"] and safe_filename(task["project"]) == name
        ]
        records = sorted(
            (record for _, record in self.records(name)),
            key=lambda record: record.get("date") or "",
            reverse=True,
        )
        names = {member.casefold(): member for member in members}

        def person_name(value: str | None) -> str | None:
            clean = " ".join(value.split()) if value else ""
            return names.setdefault(clean.casefold(), clean) if clean else None

        attendance: dict[str, int] = {}
        for record in records:
            people = {
                assignment["name"]
                for assignment in record.get("assignments", {}).values()
                if assignment.get("name")
            } | {person for person in record.get("attendees", []) if person}
            for person in {person_name(value) for value in people} - {None}:
                attendance[person] = attendance.get(person, 0) + 1
        task_rows = [task | {"owner": person_name(task["owner"])} for task in task_rows]
        remaining = [task for task in task_rows if not task["done"]]
        owners = {task["owner"] for task in task_rows if task["owner"]}
        team = []
        for person in sorted(set(members) | set(attendance) | owners, key=str.casefold):
            try:
                profile = self.vault.person_profile(person)
            except (OSError, ValueError, YAMLError):
                profile = {"role": "", "organisation": ""}
            team.append(
                {
                    "name": person,
                    "role": profile["role"],
                    "organisation": profile["organisation"],
                    "assigned": person in members,
                    "meetings": attendance.get(person, 0),
                    "open_tasks": sum(task["owner"] == person for task in remaining),
                }
            )
        meeting_rows = []
        for record in records:
            row = dashboard.meeting_row(record)
            row["project"] = name
            row["people"] = sorted(
                {person_name(person) for person in row["people"]} - {None}, key=str.casefold
            )
            meeting_rows.append(row)
        return {
            "name": name,
            "meetings": len(records),
            "minutes": round(sum(record.get("duration") or 0 for record in records) / 60, 1),
            "last": records[0].get("date") if records else None,
            "overview": self.vault.project_context(name),
            "meeting_ids": details["meeting_ids"],
            "meeting_rows": meeting_rows,
            "members": members,
            "team": sorted(
                team, key=lambda person: (not person["assigned"], person["name"].casefold())
            ),
            "open_tasks": remaining,
            "completed_tasks": len(task_rows) - len(remaining),
            "unassigned_tasks": sum(not task["owner"] for task in remaining),
        }

    def _note(self, path: Path) -> None:
        if path.is_symlink():
            raise ProjectConflict("A meeting note is a symbolic link and cannot be changed here")
        if not path.resolve().is_relative_to(self.vault.root.resolve()):
            raise ProjectConflict(
                "A meeting note is outside the current vault. Move it into the vault first"
            )

    @meeting_locked
    def rename(self, old: str, requested: str) -> dict[str, Any]:
        if not requested.strip() or len(safe_filename(requested)) > 100:
            raise ValueError("Give the project a name of up to 100 characters")
        new = safe_filename(requested)
        details = self.details(old)
        if new == old:
            return details
        src, dst = self.folder(old), self.folder(new)
        records = self.records(old)
        if dst.exists() and not (src.exists() and src.samefile(dst)):
            raise ProjectConflict("A project with that name already exists")
        for _, data in self.records(new):
            if safe_filename(data["project"]) != old:
                raise ProjectConflict("A project with that name already exists")
        existing_overview = src / f"{new}.md"
        old_overview = src / f"{old}.md"
        if existing_overview.exists() and not (
            old_overview.exists() and old_overview.samefile(existing_overview)
        ):
            raise ProjectConflict("A note with the new project name already exists in this folder")

        def moved(path: Path) -> Path:
            return dst / path.relative_to(src) if path.is_relative_to(src) else path

        def rename_links(text: str, meeting: bool) -> str:
            text = re.sub(
                r"\[\[" + re.escape(old) + r"(?=[\]|#])",
                lambda _: "[[" + new,
                text,
            )
            text = re.sub(
                r"\[\[Projects/"
                + re.escape(old)
                + "/"
                + re.escape(old)
                + r"(?=(?:\.md)?(?:[|#]|\]\]))",
                lambda _: f"[[Projects/{new}/{new}",
                text,
            )
            text = text.replace(f"Projects/{old}/", f"Projects/{new}/")
            text = text.replace(str(src / f"{old}.md"), str(dst / f"{new}.md"))
            text = text.replace(str(src) + "/", str(dst) + "/")
            text = text.replace(
                (src / f"{old}.md").absolute().as_uri(),
                (dst / f"{new}.md").absolute().as_uri(),
            )
            text = text.replace(src.absolute().as_uri() + "/", dst.absolute().as_uri() + "/")
            # Set the project property without rewriting the user's other YAML properties.
            # JSON quoting is valid YAML and also handles apostrophes and Unicode names.
            opening = re.match(r"^---\r?\n", text)
            if opening and meeting:
                closing = re.search(r"(?m)^---\r?$", text[opening.end() :])
                if closing:
                    end = opening.end() + closing.start()
                    header = re.sub(
                        r"^project:[^\r\n]*",
                        lambda _: "project: " + json.dumps(f"[[{new}]]", ensure_ascii=False),
                        text[:end],
                        flags=re.MULTILINE,
                    )
                    text = header + text[end:]
            return text

        paths = set(src.rglob("*.md")) if src.is_dir() else set()
        meeting_notes = set()
        for _, record in records:
            if record.get("note_path"):
                path = Path(record["note_path"])
                self._note(path)
                meeting_notes.add(path)
                if path.is_file():
                    paths.add(path)
        # Prepare every edit before moving anything; a read error leaves the project intact.
        edits: dict[Path, tuple[Path, str, str]] = {}
        for path in paths:
            self._note(path)
            before = path.read_bytes().decode("utf-8")
            after = rename_links(before, path in meeting_notes)
            destination = moved(path)
            if path == src / f"{old}.md":
                destination = dst / f"{new}.md"
                after = re.sub(
                    r"(?m)^# " + re.escape(old) + r"(\r?)$",
                    lambda match: f"# {new}" + match[1],
                    after,
                    count=1,
                )
            edits[path] = (destination, before, after)
        for path, data in records:
            before = path.read_bytes().decode("utf-8")
            data["project"] = new
            for key in ("note_path", "source_audio"):
                if data.get(key):
                    data[key] = str(moved(Path(data[key])))
            original = json.loads(before)
            note = Path(original["note_path"]) if original.get("note_path") else None
            if note in edits:
                _, previous, updated = edits[note]
                if original.get("_note_sha") == hashlib.sha256(previous.encode()).hexdigest():
                    data["_note_sha"] = hashlib.sha256(updated.encode()).hexdigest()
            edits[path] = (path, before, json.dumps(data, ensure_ascii=False, indent=1))

        folder_moved, folder_created, overview_moved = False, False, False
        overview_src, overview_dst = dst / f"{old}.md", dst / f"{new}.md"
        try:
            if src.is_dir():
                src.rename(dst)
                folder_moved = True
                if overview_src.exists():
                    overview_src.rename(overview_dst)
                    overview_moved = True
            else:
                self.vault.ensure_project(new)
                folder_created = True
            for destination, _, after in edits.values():
                atomic_write_text(destination, after)
            if self.chats:
                self.chats.relink_project(old, new)
        except (OSError, sqlite3.Error):
            # Put the original bytes and paths back if any write fails.
            for original, (destination, before, _) in edits.items():
                restored = destination if folder_moved else original
                if folder_moved and original == old_overview and not overview_moved:
                    restored = moved(original)
                atomic_write_text(restored, before)
            if overview_moved:
                overview_dst.rename(overview_src)
            if folder_moved:
                dst.rename(src)
            if folder_created:
                shutil.rmtree(dst)
            raise
        return {**details, "name": new}

    @meeting_locked
    def delete(self, name: str, expected_meeting_ids: list[str]) -> dict[str, Any]:
        details = self.details(name)
        if set(expected_meeting_ids) != set(details["meeting_ids"]):
            raise ProjectConflict(
                "This project's meetings changed. Review and confirm deletion again"
            )
        folder = self.folder(name)
        targets = {folder} if folder.is_dir() else set()
        for path, record in self.records(name):
            targets.add(path)
            if record.get("note_path"):
                note = Path(record["note_path"])
                self._note(note)
                if note.is_file() and not note.is_relative_to(folder):
                    targets.add(note)
            audio = Path(record.get("source_audio") or "")
            if audio.is_file() and audio.resolve().parent == self.recordings_dir.resolve():
                targets.add(audio)
        # Stage on each file's own filesystem. Until all moves succeed they can all be restored.
        staged = []
        try:
            for path in sorted(targets, key=str):
                backup = path.with_name(f".dzomdu-delete-{uuid.uuid4().hex}")
                path.rename(backup)
                staged.append((path, backup))
            if self.chats:
                self.chats.relink_project(name, None)
        except (OSError, sqlite3.Error):
            for original, backup in reversed(staged):
                backup.rename(original)
            raise
        for _, backup in staged:
            try:
                shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
            except OSError:
                log.warning("Could not remove staged project data: %s", backup)
        return {
            "deleted": True,
            "meetings": details["meetings"],
            "meeting_ids": details["meeting_ids"],
        }
