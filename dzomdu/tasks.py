"""Tasks derive from saved action items; scheduling lives in their meeting record."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import dashboard
from .config import Config
from .persistence import meeting_locked
from .vault import atomic_write_text, safe_filename


class TaskConflict(ValueError):
    pass


class TaskManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def sync(self, record: dict) -> dict:
        if dashboard.sync_task_state(record):
            self.save(record)
        return record

    def save(self, record: dict) -> None:
        # Only paths discovered under meetings_dir are used, never an id from a
        # request or an arbitrary record field as a filesystem path.
        for path in self.cfg.meetings_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data["id"] == record["id"]:
                atomic_write_text(path, json.dumps(record, ensure_ascii=False, indent=1))
                return
        raise FileNotFoundError("The meeting was deleted")

    @staticmethod
    def row(record: dict, task: dashboard.Task) -> dict[str, Any]:
        return asdict(task) | {
            "meeting_id": record["id"],
            "meeting_title": record.get("title") or "Untitled",
            "project": safe_filename(record["project"]) if record.get("project") else None,
            "date": record.get("date"),
        }

    @meeting_locked
    def list(self) -> list[dict[str, Any]]:
        rows = []
        for record in dashboard.load_records(self.cfg.meetings_dir):
            self.sync(record)
            rows.extend(self.row(record, task) for task in dashboard.meeting_tasks(record))
        rows.sort(key=lambda row: (row["done"], row["reminder_date"] or "", row["id"]))
        return rows

    @meeting_locked
    def update(
        self, task_id: str, *, done: bool | None = None, reminder_date: str | None = None
    ) -> dict[str, Any]:
        for record in dashboard.load_records(self.cfg.meetings_dir):
            self.sync(record)
            for task in dashboard.meeting_tasks(record):
                if task.id != task_id:
                    continue
                state = next(state for state in record["_tasks"] if state["id"] == task_id)
                note, original = None, None
                if done is not None:
                    if task.editable:
                        note = Path(record["note_path"])
                        if note.is_symlink():
                            raise TaskConflict(
                                "This note is a symbolic link and cannot be updated here"
                            )
                        if not note.resolve().is_relative_to(self.cfg.vault.resolve()):
                            raise TaskConflict(
                                "Move this meeting note into the current vault first"
                            )
                        original = note.read_bytes()
                        current_sha = hashlib.sha256(original).hexdigest()
                        text = dashboard.set_task_done(note, task.line, done)
                        # Keep edit protection for changes made outside Dzomdu.
                        if record.get("_note_sha") == current_sha:
                            record["_note_sha"] = hashlib.sha256(text.encode()).hexdigest()
                    state["done"] = done
                if reminder_date is not None:
                    state["reminder_date"] = reminder_date
                try:
                    self.save(record)
                except OSError:
                    if note is not None and original is not None:
                        atomic_write_text(note, original.decode("utf-8"))
                    raise
                updated = next(
                    task for task in dashboard.meeting_tasks(record) if task.id == task_id
                )
                return self.row(record, updated)
        raise FileNotFoundError("This task no longer exists; refresh the task list")
