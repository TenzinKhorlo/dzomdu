"""Aggregations for the web dashboard.

Built from the saved meeting records plus the meeting notes in the vault. Action items are read
from the notes themselves (Obsidian Tasks lines), so ticking a task in Obsidian shows up here and
ticking it in the dashboard edits the note.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .vault import atomic_write_text, safe_filename

_TASK = re.compile(r"^(\s*)- \[( |x|X)\] (.+)$")
_OWNER = re.compile(r"^\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*")
_DUE = re.compile(r"\s*(?:📅\s*(\d{4}-\d{2}-\d{2})|\(due: ([^)]+)\))")
_CITE = re.compile(r"\s*\((?:\[\[#\^t\d+(?:\\?\|[^\]]*)?\]\](?:,\s*)?)+\)")
_TURN = re.compile(r"\[\[#\^(t\d+)")


@dataclass
class Task:
    line: int  # 0-based line number in the note, used to tick it
    done: bool
    text: str
    owner: str | None = None
    due: str | None = None
    turn: str | None = None  # transcript turn it was cited from
    editable: bool = True
    id: str | None = None
    reminder_date: str | None = None


def parse_tasks(markdown: str) -> list[Task]:
    """Obsidian Tasks lines (`- [ ] [[Owner]] Do x 📅 2026-10-14 ([[#^t3|00:01:02]])`) above
    the transcript."""
    tasks = []
    for i, line in enumerate(markdown.splitlines()):
        if line.startswith("## Transcript"):
            break
        m = _TASK.match(line)
        if not m:
            continue
        body = m.group(3)
        turn = _TURN.search(body)
        body = _CITE.sub("", body)
        owner = None
        if om := _OWNER.match(body):
            owner, body = om.group(1), body[om.end() :]
        due = None
        if dm := _DUE.search(body):
            due = dm.group(1) or dm.group(2)
            body = body[: dm.start()] + body[dm.end() :]
        text = body.strip()
        if text:
            tasks.append(
                Task(
                    i, m.group(2).lower() == "x", text, owner, due, turn.group(1) if turn else None
                )
            )
    return tasks


def set_task_done(note: Path, line: int, done: bool) -> str:
    """Tick or untick one task line in a note; returns the new note text."""
    lines = note.read_text(encoding="utf-8").split("\n")
    if not 0 <= line < len(lines) or not _TASK.match(lines[line]):
        raise ValueError("That line is not a task (the note may have been edited)")
    lines[line] = re.sub(r"- \[( |x|X)\]", f"- [{'x' if done else ' '}]", lines[line], count=1)
    text = "\n".join(lines)
    atomic_write_text(note, text)
    return text


# -- records ------------------------------------------------------------------------------------


def load_records(meetings_dir: Path) -> list[dict[str, Any]]:
    records = []
    if not meetings_dir.is_dir():
        return records
    for path in meetings_dir.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    records.sort(key=lambda r: r.get("date") or "", reverse=True)
    return records


def speaking_by_name(record: dict[str, Any]) -> dict[str, float]:
    """Seconds spoken per identified person in one meeting."""
    names = {k: a.get("name") for k, a in record.get("assignments", {}).items()}
    out: dict[str, float] = defaultdict(float)
    for t in record.get("turns", []):
        if name := names.get(t["speaker"]):
            out[name] += t["end"] - t["start"]
    return dict(out)


def _source_tasks(record: dict[str, Any]) -> list[Task]:
    """Tasks from the note; if the note has none (e.g. a table-style template), fall back to
    the extracted action items, read-only."""
    items = (record.get("_notes") or {}).get("action_items", [])
    note = record.get("note_path")
    if note and Path(note).exists():
        tasks = parse_tasks(Path(note).read_text(encoding="utf-8"))
        if tasks:
            # An owner without a person profile is plain text in the note. Strip
            # that prefix using the original action item so identities match
            # both checkbox and table layouts.
            for task in tasks:
                for item in items:
                    owner = item.get("owner")
                    if owner and task.owner is None and task.text == f"{owner} {item['task']}":
                        task.text, task.owner = item["task"], owner
                        break
            return tasks
    return [
        Task(
            -1,
            False,
            a["task"],
            a.get("owner"),
            a.get("due"),
            next(iter(a.get("source_turns", [])), None),
            editable=False,
        )
        for a in items
    ]


def task_keys(tasks: list[Task]) -> list[str]:
    counts: Counter[str] = Counter()
    keys = []
    for task in tasks:
        signature = json.dumps([" ".join(task.text.split()), task.owner], ensure_ascii=False)
        counts[signature] += 1
        keys.append(hashlib.sha256(f"{signature}:{counts[signature]}".encode()).hexdigest())
    return keys


def sync_task_state(record: dict[str, Any], today: date | None = None) -> bool:
    """Assign stable task ids and a reminder once, retaining dates across reordering."""
    today = today or date.today()
    previous = {state["key"]: state for state in record.get("_tasks", [])}
    tasks = _source_tasks(record)
    states = []
    for key, task in zip(task_keys(tasks), tasks, strict=True):
        state = dict(
            previous.get(key)
            or {
                "key": key,
                "id": hashlib.sha256(f"{record['id']}:{key}".encode()).hexdigest()[:32],
                "reminder_date": (today + timedelta(days=7)).isoformat(),
                "created_date": today.isoformat(),
                "done": task.done,
            }
        )
        if task.editable:
            state["done"] = task.done
        states.append(state)
    changed = record.get("_tasks") != states
    record["_tasks"] = states
    return changed


def meeting_tasks(record: dict[str, Any]) -> list[Task]:
    tasks = _source_tasks(record)
    states = {state["key"]: state for state in record.get("_tasks", [])}
    for key, task in zip(task_keys(tasks), tasks, strict=True):
        if state := states.get(key):
            task.id, task.reminder_date = state["id"], state["reminder_date"]
            if not task.editable:
                task.done = state["done"]
    return tasks


def carry_task_completion(text: str, previous: dict[str, Any]) -> str:
    previous_tasks = meeting_tasks(previous)
    completed = {
        key
        for key, task in zip(task_keys(previous_tasks), previous_tasks, strict=True)
        if task.done
    }
    tasks = _source_tasks(previous | {"note_path": None})
    # Use the rendered lines for locations, but use the same canonical owner/text
    # rules as persisted tasks when comparing identities.
    rendered = parse_tasks(text)
    for task in rendered:
        for original in tasks:
            if (
                original.owner
                and task.owner is None
                and task.text == f"{original.owner} {original.text}"
            ):
                task.text, task.owner = original.text, original.owner
                break
    tasks = rendered
    lines = text.split("\n")
    for key, task in zip(task_keys(tasks), tasks, strict=True):
        if key in completed:
            lines[task.line] = re.sub(r"- \[( |x|X)\]", "- [x]", lines[task.line], count=1)
    return "\n".join(lines)


def summary_of(record: dict[str, Any]) -> str | None:
    return (record.get("_notes") or {}).get("summary")


def meeting_row(record: dict[str, Any]) -> dict[str, Any]:
    tasks = meeting_tasks(record)
    people = sorted(
        {a["name"] for a in record.get("assignments", {}).values() if a.get("name")}
        | {name for name in record.get("attendees", []) if name}
    )
    unknown = sum(1 for a in record.get("assignments", {}).values() if not a.get("name"))
    return {
        "id": record["id"],
        "title": record.get("title") or "Untitled",
        "date": record.get("date"),
        "project": safe_filename(record["project"]) if record.get("project") else None,
        "duration": record.get("duration") or 0,
        "people": people,
        "unidentified": unknown,
        "summary": summary_of(record),
        "open_actions": sum(1 for t in tasks if not t.done),
        "has_note": bool(record.get("note_path") and Path(record["note_path"]).exists()),
    }


# -- dashboard ----------------------------------------------------------------------------------


def _day(record: dict[str, Any]) -> date | None:
    try:
        return datetime.fromisoformat(record["date"]).date()
    except (KeyError, TypeError, ValueError):
        return None


def _delta(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def build_dashboard(
    records: list[dict[str, Any]], voices: int, today: date | None = None, days: int = 30
) -> dict[str, Any]:
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)

    activity = {start + timedelta(days=i): {"meetings": 0, "minutes": 0.0} for i in range(days)}
    current = {"meetings": 0, "minutes": 0.0}
    previous = {"meetings": 0, "minutes": 0.0}
    talk: Counter[str] = Counter()
    talk_meetings: Counter[str] = Counter()
    projects: dict[str, dict[str, Any]] = {}
    open_tasks: list[dict[str, Any]] = []
    done_count = 0

    for r in records:
        day = _day(r)
        minutes = (r.get("duration") or 0) / 60
        if day and start <= day <= today:
            activity[day]["meetings"] += 1
            activity[day]["minutes"] += minutes
            current["meetings"] += 1
            current["minutes"] += minutes
        elif day and prev_start <= day < start:
            previous["meetings"] += 1
            previous["minutes"] += minutes
        for name, seconds in speaking_by_name(r).items():
            talk[name] += seconds
            talk_meetings[name] += 1
        if project := r.get("project"):
            project = safe_filename(project)
            p = projects.setdefault(
                project, {"name": project, "meetings": 0, "minutes": 0.0, "last": None}
            )
            p["meetings"] += 1
            p["minutes"] += minutes
            p["last"] = max(p["last"] or "", r.get("date") or "")
        for task in meeting_tasks(r):
            if task.done:
                done_count += 1
                continue
            open_tasks.append(
                asdict(task)
                | {
                    "meeting_id": r["id"],
                    "meeting_title": r.get("title"),
                    "date": r.get("date"),
                    "project": r.get("project"),
                }
            )

    open_tasks.sort(key=lambda t: (t["due"] is None, t["due"] or "", t["date"] or ""))
    total_minutes = sum((r.get("duration") or 0) / 60 for r in records)
    return {
        "totals": {
            "meetings": len(records),
            "hours": round(total_minutes / 60, 1),
            "voices": voices,
            "open_actions": len(open_tasks),
            "done_actions": done_count,
        },
        "period": {
            "days": days,
            "meetings": current["meetings"],
            "minutes": round(current["minutes"], 1),
            "meetings_delta": _delta(current["meetings"], previous["meetings"]),
            "minutes_delta": _delta(current["minutes"], previous["minutes"]),
        },
        "activity": [
            {"date": d.isoformat(), "meetings": v["meetings"], "minutes": round(v["minutes"], 1)}
            for d, v in activity.items()
        ],
        "speakers": [
            {"name": n, "minutes": round(s / 60, 1), "meetings": talk_meetings[n]}
            for n, s in talk.most_common(8)
        ],
        "recent": [meeting_row(r) for r in records[:6]],
        "actions": open_tasks[:50],
        "projects": sorted(projects.values(), key=lambda p: p["last"] or "", reverse=True),
    }
