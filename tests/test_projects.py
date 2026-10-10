import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dzomdu.projects as project_module
from dzomdu.models import MeetingRecord
from dzomdu.pipeline import Pipeline
from dzomdu.projects import ProjectManager
from dzomdu.server.app import create_app
from dzomdu.server.sessions import SessionMeta
from dzomdu.vault import Vault, atomic_write_text


def save_meeting(cfg, vault, meeting_id, project, *, edited=False, owned_audio=False):
    vault.ensure_project(project)
    cfg.meetings_dir.mkdir(parents=True, exist_ok=True)
    recordings = cfg.data_dir / "recordings"
    recordings.mkdir(parents=True, exist_ok=True)
    audio = (recordings if owned_audio else cfg.data_dir.parent) / f"{meeting_id}.wav"
    audio.write_bytes(b"sample audio")
    note = vault.project_dir(project) / "Meetings" / f"{meeting_id}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f"---\nproject: '[[{project}]]'\n---\n# Meeting\n\n"
        f"Keep this decision. [[{project}|Project]]\n"
    )
    note.write_text(text + ("User edits\n" if edited else ""))
    record = MeetingRecord(
        id=meeting_id,
        title=meeting_id,
        date="2026-10-08T10:00:00",
        source_audio=str(audio),
        audio_sha="audio",
        duration=120,
        project=project,
        turns=[],
        assignments={},
        asr_model="test",
        diarization_model="test",
        note_path=str(note),
    ).to_dict()
    record.update(
        _notes={"summary": "Keep the structured notes"},
        _note_sha=hashlib.sha256(text.encode()).hexdigest(),
    )
    path = cfg.meetings_dir / f"{meeting_id}.json"
    path.write_text(json.dumps(record))
    return path, note, audio


@pytest.fixture
def projects(cfg):
    vault = Vault(cfg.vault)
    vault.init()
    return ProjectManager(cfg, vault, cfg.data_dir / "recordings")


def test_rename_preserves_notes_and_updates_paths_and_clean_hashes(cfg, projects):
    clean, note, audio = save_meeting(cfg, projects.vault, "one", "Alpha")
    edited, edited_note, _ = save_meeting(cfg, projects.vault, "two", "Alpha", edited=True)
    old_sha = json.loads(edited.read_text())["_note_sha"]
    result = projects.rename("Alpha", "New name")
    assert result["name"] == "New name" and result["meetings"] == 2
    assert not projects.vault.project_dir("Alpha").exists()
    assert "# New name" in projects.vault.project_context("New name") or (
        "# New name" in (projects.vault.project_dir("New name") / "New name.md").read_text()
    )
    moved = projects.vault.project_dir("New name") / "Meetings" / note.name
    assert "Keep this decision" in moved.read_text()
    assert "[[New name]]" in moved.read_text() and "[[New name|Project]]" in moved.read_text()
    data = json.loads(clean.read_text())
    assert data["project"] == "New name" and data["note_path"] == str(moved)
    assert data["_note_sha"] == hashlib.sha256(moved.read_bytes()).hexdigest()
    assert data["_notes"]["summary"] == "Keep the structured notes"
    assert json.loads(edited.read_text())["_note_sha"] == old_sha
    assert "User edits" in (moved.parent / edited_note.name).read_text()
    assert audio.exists()


def test_rename_collision_does_not_merge_or_overwrite(cfg, projects):
    record, note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    projects.vault.ensure_project("Beta")
    with pytest.raises(ValueError, match="already exists"):
        projects.rename("Alpha", "Beta")
    assert note.exists() and json.loads(record.read_text())["project"] == "Alpha"
    (projects.vault.project_dir("Alpha") / "New.md").write_text("User document")
    with pytest.raises(ValueError, match="note with the new project name"):
        projects.rename("Alpha", "New")
    assert not projects.vault.project_dir("New").exists()


def test_rename_updates_quoted_metadata_and_overview_links(cfg, projects):
    record, note, _ = save_meeting(cfg, projects.vault, "one", "Team's work")
    note.write_bytes(
        b'---\r\nproject: "[[Team\'s work]]"\r\ncustom: keep\r\n---\r\n'
        b"[[Projects/Team's work/Team's work|Overview]]\r\n"
    )
    projects.rename("Team's work", "New team")
    moved = Path(json.loads(record.read_text())["note_path"])
    text = moved.read_bytes().decode()
    assert 'project: "[[New team]]"\r\n' in text
    assert "custom: keep\r\n" in text
    assert "[[Projects/New team/New team|Overview]]" in text


def test_rename_rollback_restores_files_when_a_write_fails(cfg, projects, monkeypatch):
    record, note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    original_record, original_note = record.read_bytes(), note.read_bytes()
    calls = 0

    def fail_once(path, text):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk failure")
        atomic_write_text(path, text)

    monkeypatch.setattr(project_module, "atomic_write_text", fail_once)
    with pytest.raises(OSError):
        projects.rename("Alpha", "Beta")
    assert record.read_bytes() == original_record and note.read_bytes() == original_note
    assert (projects.vault.project_dir("Alpha") / "Alpha.md").exists()
    assert not projects.vault.project_dir("Beta").exists()


def test_delete_removes_related_data_and_preserves_original_uploads(cfg, projects):
    first, note, upload = save_meeting(cfg, projects.vault, "one", "Alpha")
    second, _, recording = save_meeting(cfg, projects.vault, "two", "Alpha", owned_audio=True)
    other, other_note, _ = save_meeting(cfg, projects.vault, "other", "Beta")
    details = projects.details("Alpha")
    assert details["meeting_ids"] == ["one", "two"]
    result = projects.delete("Alpha", details["meeting_ids"])
    assert result["meetings"] == 2
    assert not first.exists() and not second.exists() and not note.exists()
    assert not recording.exists() and not projects.vault.project_dir("Alpha").exists()
    assert upload.exists() and other.exists() and other_note.exists()


def test_delete_checks_the_exact_confirmed_meetings(cfg, projects):
    record, note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    with pytest.raises(ValueError, match="meetings changed"):
        projects.delete("Alpha", ["different-meeting"])
    assert record.exists() and note.exists()


def test_delete_rollback_before_any_data_is_purged(cfg, projects, monkeypatch):
    first, first_note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    second, second_note, _ = save_meeting(cfg, projects.vault, "two", "Alpha")
    original = Path.rename

    def fail_second(path, destination):
        if path == second:
            raise OSError("disk failure")
        return original(path, destination)

    monkeypatch.setattr(Path, "rename", fail_second)
    with pytest.raises(OSError):
        projects.delete("Alpha", ["one", "two"])
    assert first.exists() and second.exists() and first_note.exists() and second_note.exists()


def test_project_path_guards_and_external_notes(cfg, projects, tmp_path):
    projects.vault.ensure_project("Alpha")
    with pytest.raises(ValueError, match="Invalid project"):
        projects.delete("..", [])
    outside = tmp_path / "outside"
    outside.mkdir()
    (projects.vault.projects_dir / "Linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        projects.delete("Linked", [])
    record, note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    data = json.loads(record.read_text())
    external_note = tmp_path / "external.md"
    external_note.write_text("Do not delete")
    data["note_path"] = str(external_note)
    record.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="outside the current vault"):
        projects.delete("Alpha", ["one"])
    assert external_note.exists() and note.exists() and record.exists()


def test_empty_project_can_be_renamed_and_deleted(cfg, projects):
    projects.vault.ensure_project("Empty")
    assert projects.rename("Empty", "Renamed")["meetings"] == 0
    assert projects.delete("Renamed", [])["deleted"]


def test_api_rename_updates_open_meeting_session_and_deletion_clears_it(cfg, fake_llm):
    pipeline = Pipeline(cfg, llm=fake_llm)
    save_meeting(cfg, pipeline.vault, "one", "Alpha")
    app = create_app(cfg, pipeline)
    manager = app.state.manager
    sid = manager.open_existing("one").id
    with TestClient(app) as client:
        renamed = client.patch("/api/projects/Alpha", json={"name": "Beta"})
        assert renamed.status_code == 200
        assert manager.get(sid).record.project == "Beta"
        assert manager.get(sid).note_path == Path(manager.get(sid).record.note_path)
        details = client.get("/api/projects/Beta").json()
        assert client.delete("/api/projects/Beta").status_code == 422
        assert (
            client.request("DELETE", "/api/projects/Beta", json={"meeting_ids": []}).status_code
            == 409
        )
        deleted = client.request(
            "DELETE", "/api/projects/Beta", json={"meeting_ids": details["meeting_ids"]}
        )
        assert deleted.status_code == 200
        assert sid not in manager.sessions
        assert client.get("/api/projects/Beta").status_code == 404
        assert client.get("/api/meetings/one").status_code == 404


@pytest.mark.parametrize("state", ["new", "recording", "processing", "review", "summarizing"])
def test_api_blocks_project_changes_during_active_meetings(cfg, fake_llm, state):
    pipeline = Pipeline(cfg, llm=fake_llm)
    save_meeting(cfg, pipeline.vault, "one", "Alpha")
    app = create_app(cfg, pipeline)
    session = app.state.manager.create(SessionMeta(project="Alpha"), "recording")
    session.state = state
    with TestClient(app) as client:
        assert client.patch("/api/projects/Alpha", json={"name": "Beta"}).status_code == 409
        assert (
            client.request(
                "DELETE", "/api/projects/Alpha", json={"meeting_ids": ["one"]}
            ).status_code
            == 409
        )
    assert pipeline.vault.project_dir("Alpha").exists()


def test_projects_are_ordered_by_recent_activity(cfg, fake_llm):
    pipeline = Pipeline(cfg, llm=fake_llm)
    for name, modified in [("Old", 100), ("Middle", 200), ("Newest", 300), ("Fourth", 50)]:
        note = pipeline.vault.ensure_project(name)
        os.utime(note, (modified, modified))
        os.utime(note.parent, (modified, modified))
    with TestClient(create_app(cfg, pipeline)) as client:
        assert [p["name"] for p in client.get("/api/projects").json()] == [
            "Newest",
            "Middle",
            "Old",
            "Fourth",
        ]


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_project_database_failure_restores_files_and_chat_link(
    cfg, projects, monkeypatch, operation
):
    import sqlite3

    from dzomdu.chat import ChatStore

    record, note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    original_record, original_note = record.read_bytes(), note.read_bytes()
    store = ChatStore(cfg.data_dir / "chats.sqlite")
    chat = store.create([])
    store.update(chat["id"], {"project": "Alpha"})
    projects.chats = store

    def fail(old, new):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "relink_project", fail)
    with pytest.raises(sqlite3.OperationalError):
        projects.rename("Alpha", "Beta") if operation == "rename" else projects.delete(
            "Alpha", ["one"]
        )
    assert record.read_bytes() == original_record and note.read_bytes() == original_note
    assert store.get(chat["id"])["project"] == "Alpha"
    assert (projects.vault.project_dir("Alpha") / "Alpha.md").exists()
    assert not projects.vault.project_dir("Beta").exists()


def test_project_overview_groups_team_meetings_and_remaining_tasks(cfg, projects):
    one, note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    two, second_note, _ = save_meeting(cfg, projects.vault, "two", "Alpha")
    save_meeting(cfg, projects.vault, "other", "Beta")
    data = json.loads(one.read_text())
    data.update(
        assignments={"S1": {"name": "Alice"}, "S2": {"name": None}}, attendees=["Alice", "Carol"]
    )
    one.write_text(json.dumps(data))
    data = json.loads(two.read_text())
    data.update(
        date="2026-10-09T10:00:00", assignments={"S1": {"name": "ALICE"}}, attendees=["Carol"]
    )
    two.write_text(json.dumps(data))
    note.write_text(
        "# Meeting\n## Action items\n- [ ] [[Bob]] Draft roadmap\n"
        "- [x] [[Alice]] Send invite\n- [ ] Book venue\n"
    )
    second_note.write_text("# Meeting\n## Action items\n- [ ] [[Owen]] Review contract\n")
    projects.vault.ensure_person("Bob", role="Designer", organisation="Studio")
    with TestClient(create_app(cfg, Pipeline(cfg))) as client:
        assert (
            client.put(
                "/api/projects/Alpha/members", json={"members": ["Alice", "Dana"]}
            ).status_code
            == 200
        )
        response = client.get("/api/projects/Alpha/overview")
        assert response.status_code == 200
        overview = response.json()
        assert overview["members"] == ["Alice", "Dana"]
        assert overview["meetings"] == 2 and overview["minutes"] == 4
        assert [row["id"] for row in overview["meeting_rows"]] == ["two", "one"]
        assert overview["meeting_ids"] == ["one", "two"]
        assert len(overview["open_tasks"]) == 3
        assert overview["completed_tasks"] == 1 and overview["unassigned_tasks"] == 1
        assert all(task["id"] and task["reminder_date"] for task in overview["open_tasks"])
        people = {person["name"]: person for person in overview["team"]}
        assert set(people) == {"Alice", "Bob", "Carol", "Dana", "Owen"}
        assert people["Alice"]["assigned"] and people["Alice"]["meetings"] == 2
        assert people["Carol"]["meetings"] == 2 and not people["Carol"]["assigned"]
        assert people["Dana"]["assigned"] and people["Dana"]["meetings"] == 0
        assert people["Bob"]["role"] == "Designer" and people["Bob"]["open_tasks"] == 1
        assert people["Owen"]["open_tasks"] == 1
        assert overview["team"][0]["assigned"] and overview["team"][1]["assigned"]
        draft = next(task for task in overview["open_tasks"] if task["owner"] == "Bob")
        assert client.patch(f"/api/tasks/{draft['id']}", json={"done": True}).status_code == 200
        updated = client.get("/api/projects/Alpha/overview").json()
        assert len(updated["open_tasks"]) == 2 and updated["completed_tasks"] == 2
        assert (
            next(person for person in updated["team"] if person["name"] == "Bob")["open_tasks"] == 0
        )
        assert client.get("/api/projects/missing/overview").status_code == 404


def test_project_members_persist_follow_rename_and_keep_user_notes(cfg, projects):
    from dzomdu.tasks import TaskManager

    record, note, _ = save_meeting(cfg, projects.vault, "one", "Alpha")
    before = note.read_bytes()
    overview_path = projects.vault.project_dir("Alpha") / "Alpha.md"
    overview_before = overview_path.read_bytes()
    metadata = overview_path.parent / ".dzomdu-project.json"
    metadata.write_text(json.dumps({"custom": "keep", "members": []}))
    with TestClient(create_app(cfg, Pipeline(cfg))) as client:
        response = client.put(
            "/api/projects/Alpha/members", json={"members": ["  Alice  ", "alice", "Dawa  Dorji"]}
        )
        assert response.json()["members"] == ["Alice", "Dawa Dorji"]
        assert note.read_bytes() == before and overview_path.read_bytes() == overview_before
        assert json.loads(metadata.read_text())["custom"] == "keep"
        assert client.put("/api/projects/Alpha/members", json={"members": [" "]}).status_code == 400
        assert (
            client.put("/api/projects/Alpha/members", json={"members": ["x" * 101]}).status_code
            == 422
        )
        assert (
            client.put("/api/projects/Alpha/members", json={"members": ["Alice"] * 101}).status_code
            == 422
        )
        assert client.put("/api/projects/missing/members", json={"members": []}).status_code == 404
        assert client.patch("/api/projects/Alpha", json={"name": "Renamed"}).status_code == 200
    restarted = ProjectManager(cfg, projects.vault, cfg.data_dir / "recordings")
    assert restarted.overview("Renamed", TaskManager(cfg))["members"] == ["Alice", "Dawa Dorji"]
    restarted.set_members("Renamed", [])
    assert restarted.overview("Renamed", TaskManager(cfg))["members"] == []
    restarted.delete("Renamed", ["one"])
    assert not projects.vault.project_dir("Renamed").exists()


def test_empty_project_and_legacy_names_have_valid_overviews(cfg, projects):
    projects.vault.ensure_project("Empty")
    save_meeting(cfg, projects.vault, "legacy", "Legacy / Team")
    with TestClient(create_app(cfg, Pipeline(cfg))) as client:
        empty = client.get("/api/projects/Empty/overview").json()
        assert empty["meeting_rows"] == empty["team"] == empty["open_tasks"] == []
        assert empty["meetings"] == empty["completed_tasks"] == empty["unassigned_tasks"] == 0
        legacy = client.get("/api/projects/Legacy%20-%20Team/overview")
        assert legacy.status_code == 200
        assert legacy.json()["meeting_rows"][0]["project"] == "Legacy - Team"


def test_project_team_file_symlink_cannot_modify_external_file(cfg, projects, tmp_path):
    projects.vault.ensure_project("Alpha")
    outside = tmp_path / "outside.json"
    outside.write_text('{"members":["Alice"]}')
    metadata = projects.vault.project_dir("Alpha") / ".dzomdu-project.json"
    metadata.symlink_to(outside)
    with TestClient(create_app(cfg, Pipeline(cfg))) as client:
        assert (
            client.put("/api/projects/Alpha/members", json={"members": ["Bob"]}).status_code == 400
        )
    assert json.loads(outside.read_text())["members"] == ["Alice"]
