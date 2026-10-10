import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from dzomdu import dashboard
from dzomdu.llm.schema import ActionItem, MeetingNotes
from dzomdu.models import MeetingRecord, SpeakerAssignment, Turn
from dzomdu.okf import export_bundle
from dzomdu.pipeline import Pipeline
from dzomdu.projects import ProjectManager
from dzomdu.server.app import create_app
from dzomdu.tasks import TaskManager
from dzomdu.vault import split_frontmatter


@pytest.fixture
def meetings(cfg, fake_llm):
    pipe = Pipeline(cfg, llm=fake_llm)

    def save(*, template="standard", project="Alpha", meeting_id="one", items=None):
        record = MeetingRecord(
            id=meeting_id,
            title="Budget review",
            date="2026-10-09T10:00+06:00",
            source_audio="/original.wav",
            audio_sha="a" * 64,
            duration=10,
            project=project,
            turns=[Turn("t1", "S0", 0, 5, "Approve the budget.")],
            assignments={"S0": SpeakerAssignment("S0", name="Alice", status="confirmed")},
            asr_model="fake",
            diarization_model="fake",
        )
        notes = MeetingNotes(
            summary="Budget reviewed.",
            action_items=items
            or [
                ActionItem(
                    task="Send the budget", owner="Alice", due="2026-10-20", source_turns=["t1"]
                ),
                ActionItem(task="Book the venue", owner="Someone else", source_turns=["t1"]),
            ],
        )
        note = pipe.write_note(record, notes, pipe.template(template))
        return record, notes, note, pipe

    return save


def test_actions_collected_with_projects_and_fixed_week_reminders(cfg, meetings):
    record, _, _, _ = meetings()
    meetings(project=None, meeting_id="two")
    manager = TaskManager(cfg)
    rows = manager.list()
    assert len(rows) == 4 and len({r["id"] for r in rows}) == 4
    expected = (date.today() + timedelta(days=7)).isoformat()
    assert all(r["reminder_date"] == expected for r in rows)
    assert {r["project"] for r in rows} == {None, "Alpha"}
    assert all(r["meeting_title"] == record.title and r["turn"] == "t1" for r in rows)
    alice = next(r for r in rows if r["owner"] == "Alice")
    assert alice["due"] == "2026-10-20" and alice["reminder_date"] == expected
    data = json.loads((cfg.meetings_dir / "one.json").read_text())
    assert not dashboard.sync_task_state(data, today=date.today() + timedelta(days=20))


def test_custom_date_survives_new_manager_and_regeneration(cfg, meetings):
    record, notes, _, pipe = meetings()
    manager = TaskManager(cfg)
    task = next(r for r in manager.list() if r["owner"] == "Alice")
    manager.update(task["id"], reminder_date="2026-11-02")
    loaded, sha = pipe.load_record(record.id)
    assert not pipe.note_was_edited(loaded, sha)
    pipe.write_note(loaded, notes, pipe.template("standard"), overwrite=True)
    updated = next(r for r in TaskManager(cfg).list() if r["id"] == task["id"])
    assert updated["reminder_date"] == "2026-11-02"


def test_complete_reopen_and_regenerate_keep_note_in_sync(cfg, meetings):
    record, notes, note, pipe = meetings()
    manager = TaskManager(cfg)
    task = next(r for r in manager.list() if r["owner"] == "Alice")
    assert manager.update(task["id"], done=True)["done"]
    assert "- [x] [[Alice]] Send the budget" in note.read_text()
    loaded, sha = pipe.load_record(record.id)
    assert not pipe.note_was_edited(loaded, sha)
    pipe.write_note(loaded, notes, pipe.template("standard"), overwrite=True)
    assert next(r for r in manager.list() if r["id"] == task["id"])["done"]
    assert not manager.update(task["id"], done=False)["done"]
    assert "- [ ] [[Alice]] Send the budget" in note.read_text()


def test_table_actions_are_editable_and_survive_template_switch(cfg, meetings):
    record, notes, note, pipe = meetings(template="board")
    manager = TaskManager(cfg)
    task = next(r for r in manager.list() if r["owner"] == "Someone else")
    original = note.read_bytes()
    assert not task["editable"] and task["id"]
    manager.update(task["id"], done=True, reminder_date="2026-11-03")
    assert note.read_bytes() == original
    pipe.write_note(record, notes, pipe.template("standard"), overwrite=True)
    updated = next(r for r in manager.list() if r["id"] == task["id"])
    assert updated["done"] and updated["reminder_date"] == "2026-11-03"
    assert "- [x] Someone else Book the venue" in note.read_text()


def test_external_edits_reordering_and_new_actions_keep_identity(cfg, meetings):
    _, _, note, _ = meetings()
    manager = TaskManager(cfg)
    before = {r["text"]: r for r in manager.list()}
    manager.update(before["Send the budget"]["id"], reminder_date="2026-11-04")
    lines = note.read_text().splitlines()
    first = next(i for i, line in enumerate(lines) if "- [ ] [[Alice]]" in line)
    second = next(i for i, line in enumerate(lines) if "- [ ] Someone else" in line)
    lines[first], lines[second] = lines[second], lines[first].replace("- [ ]", "- [x]")
    lines.insert(first, "- [ ] Prepare the slides")
    note.write_text("\n".join(lines))
    after = {r["text"]: r for r in manager.list()}
    assert len(after) == 3
    assert after["Send the budget"]["id"] == before["Send the budget"]["id"]
    assert after["Send the budget"]["done"]
    assert after["Send the budget"]["reminder_date"] == "2026-11-04"
    assert after["Book the venue"]["id"] == before["Book the venue"]["id"]


def test_completing_externally_edited_note_keeps_edit_protection(cfg, meetings):
    record, _, note, pipe = meetings()
    note.write_text(note.read_text() + "\nMy corrections.\n")
    task = TaskManager(cfg).list()[0]
    TaskManager(cfg).update(task["id"], done=True)
    loaded, sha = pipe.load_record(record.id)
    assert pipe.note_was_edited(loaded, sha)
    assert "My corrections." in note.read_text()


def test_duplicate_actions_have_independent_state(cfg, meetings):
    item = ActionItem(task="Send the update")
    meetings(items=[item, item])
    manager = TaskManager(cfg)
    rows = manager.list()
    assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"]
    manager.update(rows[0]["id"], done=True, reminder_date="2026-11-05")
    by_id = {row["id"]: row for row in manager.list()}
    assert by_id[rows[0]["id"]]["done"] and not by_id[rows[1]["id"]]["done"]


def test_project_rename_and_delete_update_tasks_without_orphans(cfg, meetings):
    _, _, _, pipe = meetings()
    manager = TaskManager(cfg)
    old = manager.list()
    projects = ProjectManager(cfg, pipe.vault, cfg.data_dir / "recordings")
    projects.rename("Alpha", "Beta")
    renamed = manager.list()
    assert {r["id"] for r in old} == {r["id"] for r in renamed}
    assert all(r["project"] == "Beta" for r in renamed)
    projects.delete("Beta", ["one"])
    assert manager.list() == []
    with pytest.raises(FileNotFoundError):
        manager.update(old[0]["id"], done=True)


def test_record_write_failure_rolls_back_note_completion(cfg, meetings, monkeypatch):
    _, _, note, _ = meetings()
    manager = TaskManager(cfg)
    task = manager.list()[0]
    original = note.read_bytes()
    record_bytes = (cfg.meetings_dir / "one.json").read_bytes()

    def fail(record):
        raise OSError("disk full")

    monkeypatch.setattr(manager, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        manager.update(task["id"], done=True)
    assert note.read_bytes() == original
    assert (cfg.meetings_dir / "one.json").read_bytes() == record_bytes


def test_concurrent_completion_and_date_updates_are_preserved(cfg, meetings):
    meetings()
    manager = TaskManager(cfg)
    task = manager.list()[0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(manager.update, task["id"], done=True)
        two = executor.submit(manager.update, task["id"], reminder_date="2026-11-06")
        one.result()
        two.result()
    updated = next(r for r in manager.list() if r["id"] == task["id"])
    assert updated["done"] and updated["reminder_date"] == "2026-11-06"


def test_api_validates_custom_dates_and_updates_all_views(cfg, meetings):
    _, _, note, pipe = meetings()
    with TestClient(create_app(cfg, pipeline=pipe)) as client:
        task = client.get("/api/tasks").json()[0]
        path = f"/api/tasks/{task['id']}"
        assert client.patch(path, json={"reminder_date": "not-a-date"}).status_code == 422
        assert client.patch(path, json={"reminder_date": "2026-02-30"}).status_code == 422
        assert client.patch(path, json={}).status_code == 400
        assert client.patch(path, json={"reminder_date": None}).status_code == 400
        response = client.patch(path, json={"done": True, "reminder_date": "2026-10-10"})
        assert response.status_code == 200 and response.json()["done"]
        detail = client.get("/api/meetings/one").json()
        assert next(t for t in detail["tasks"] if t["id"] == task["id"])["done"]
        assert client.get("/api/dashboard").json()["totals"]["done_actions"] == 1
        assert client.patch("/api/tasks/missing", json={"done": True}).status_code == 404
        updated = json.loads((cfg.meetings_dir / "one.json").read_text())
        assert updated["_note_sha"] == hashlib.sha256(note.read_bytes()).hexdigest()


def test_okf_export_includes_task_status_reminder_and_source(cfg, meetings, tmp_path):
    meetings()
    manager = TaskManager(cfg)
    task = manager.list()[0]
    manager.update(task["id"], done=True, reminder_date="2026-11-07")
    export_bundle(cfg, tmp_path / "bundle")
    meta, body = split_frontmatter((tmp_path / "bundle" / "tasks" / f"{task['id']}.md").read_text())
    assert meta["type"] == "Task" and meta["task_status"] == "completed"
    assert meta["reminder_date"] == "2026-11-07" and meta["project"] == "Alpha"
    assert meta["sources"][0]["resource"].startswith("/meetings/")
    assert "- [x]" in body and "Project:" in body
