import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dzomdu.pipeline as pipeline_module
from dzomdu.llm.client import LLMError
from dzomdu.llm.schema import MeetingNotes
from dzomdu.models import MeetingRecord, Turn
from dzomdu.notes.render import retitle_note
from dzomdu.pipeline import Pipeline
from dzomdu.server.app import create_app
from dzomdu.vault import atomic_write_text, split_frontmatter


class TitleModel:
    model = "test-ollama"

    def __init__(self, *replies):
        self.replies = iter(replies)
        self.calls = []

    def chat_json(self, system, user, schema):
        self.calls.append((system, user, schema))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def record(title=""):
    return MeetingRecord(
        id="title-test",
        title=title,
        date="2026-10-09T10:00:00+06:00",
        source_audio="meeting.wav",
        audio_sha="audio",
        duration=60,
        project=None,
        turns=[Turn("t1", "SPEAKER_00", 0, 60, "Let's review the survey budget.")],
        assignments={},
        asr_model="test",
        diarization_model="test",
    )


def pipeline(cfg, model=None):
    pipe = Pipeline(cfg, llm=model or TitleModel())
    pipe.vault.init()
    return pipe


def test_generated_title_and_manual_title_survive_rewriting(cfg):
    model = TitleModel(*[{"title": "Survey budget review", "summary": "Budget reviewed."}] * 3)
    pipe = pipeline(cfg, model)
    meeting = record()
    template = pipe.template("standard")
    notes = pipe.summarize(meeting, template)
    path = pipe.write_note(meeting, notes, template)
    assert meeting.title == "Survey budget review" and not meeting.title_pending
    assert len(model.calls) == 1
    assert "descriptive" in model.calls[0][0] and '"title"' in model.calls[0][0]
    pipe.rename_meeting(meeting.id, "Weekly planning")
    renamed, sha = pipe.load_record(meeting.id)
    assert not pipe.note_was_edited(renamed, sha)
    rewritten = pipe.summarize(renamed, template)
    assert pipe.write_note(renamed, rewritten, template, overwrite=True) == path
    assert split_frontmatter(path.read_text())[0]["title"] == "Weekly planning"
    manual = record("My custom title")
    manual.id = "manual"
    pipe.write_note(manual, pipe.summarize(manual, template), template)
    assert manual.title == "My custom title" and len(model.calls) == 3


def test_missing_model_title_is_requested_from_notes(cfg):
    model = TitleModel(
        {"title": "  ", "summary": "The team reviewed the survey budget."},
        {"title": "  Survey\n budget review  "},
    )
    pipe = pipeline(cfg, model)
    meeting = record("  ")
    template = pipe.template("standard")
    notes = pipe.summarize(meeting, template)
    pipe.write_note(meeting, notes, template)
    assert meeting.title == "Survey budget review"
    assert len(model.calls) == 2
    assert "survey budget" in model.calls[1][1]
    assert model.calls[1][2]["properties"]["title"]["maxLength"] == 120


def test_failed_title_request_keeps_notes_and_can_retry_later(cfg):
    model = TitleModel(
        {"summary": "Budget reviewed."},
        LLMError("offline"),
        {"title": "Budget planning", "summary": "Budget reviewed."},
    )
    pipe = pipeline(cfg, model)
    meeting = record()
    template = pipe.template("standard")
    path = pipe.write_note(meeting, pipe.summarize(meeting, template), template)
    assert meeting.title_pending and "Budget reviewed." in path.read_text()
    loaded, _ = pipe.load_record(meeting.id)
    pipe.write_note(loaded, pipe.summarize(loaded, template), template, overwrite=True)
    assert loaded.title == "Budget planning" and not loaded.title_pending
    assert Path(loaded.note_path) == path


def test_manual_title_skips_extra_naming_request(cfg):
    model = TitleModel({"summary": "Budget reviewed."})
    pipe = pipeline(cfg, model)
    meeting = record("Custom name")
    template = pipe.template("standard")
    pipe.write_note(meeting, pipe.summarize(meeting, template), template)
    assert meeting.title == "Custom name" and len(model.calls) == 1


def test_rename_keeps_edits_task_state_paths_and_citations(cfg):
    pipe = pipeline(cfg)
    meeting = record("Old title")
    notes = MeetingNotes(summary="Budget reviewed.", action_items=[{"task": "Review costs"}])
    path = pipe.write_note(meeting, notes, pipe.template("standard"))
    record_path = cfg.meetings_dir / f"{meeting.id}.json"
    before = json.loads(record_path.read_text())
    edited = path.read_text() + "\n## Personal note\nKeep this exactly. [[#^t1]]\n"
    path.write_text(edited)
    pipe.rename_meeting(meeting.id, 'Survey: "budget" review')
    data = json.loads(record_path.read_text())
    metadata, body = split_frontmatter(path.read_text())
    assert metadata["title"] == data["title"] == 'Survey: "budget" review'
    assert body.startswith('# Survey: "budget" review\n')
    assert body.endswith("## Personal note\nKeep this exactly. [[#^t1]]\n")
    assert data["note_path"] == before["note_path"] and data["_tasks"] == before["_tasks"]
    assert data["_notes"]["summary"] == before["_notes"]["summary"]
    assert data["_note_sha"] == before["_note_sha"]
    loaded, sha = pipe.load_record(meeting.id)
    assert pipe.note_was_edited(loaded, sha)


def test_rename_rolls_back_note_if_record_save_fails(cfg, monkeypatch):
    pipe = pipeline(cfg)
    meeting = record("Before")
    path = pipe.write_note(meeting, MeetingNotes(summary="Keep"), pipe.template("standard"))
    record_path = cfg.meetings_dir / f"{meeting.id}.json"
    original_note, original_record = path.read_bytes(), record_path.read_bytes()

    def fail_record(target, text):
        if target == record_path:
            raise OSError("Disk failure")
        atomic_write_text(target, text)

    monkeypatch.setattr(pipeline_module, "atomic_write_text", fail_record)
    with pytest.raises(OSError, match="Disk failure"):
        pipe.rename_meeting(meeting.id, "After")
    assert path.read_bytes() == original_note and record_path.read_bytes() == original_record


def test_retitle_preserves_crlf_multiline_yaml_and_body():
    text = (
        "---\r\n# metadata comment\r\ntitle: >-\r\n  Old long\r\n  title\r\n"
        "custom: keep\r\n---\r\n\r\n# Old long title\r\n\r\n## Decisions\r\nKeep.\r\n"
    )
    result = retitle_note(text, "New name")
    assert '# metadata comment\r\ntitle: "New name"\r\ncustom: keep\r\n' in result
    assert result.endswith("# New name\r\n\r\n## Decisions\r\nKeep.\r\n")
    with pytest.raises(ValueError, match="frontmatter"):
        retitle_note("---\ntitle: [\n---\n# Old\n", "New")


def test_rename_api_validates_and_updates_existing_sessions(cfg):
    pipe = pipeline(cfg)
    meeting = record("Original")
    path = pipe.write_note(meeting, MeetingNotes(summary="Keep"), pipe.template("standard"))
    app = create_app(cfg, pipeline=pipe)
    with TestClient(app) as client:
        session = app.state.manager.open_existing(meeting.id)
        url = f"/api/meetings/{meeting.id}"
        assert client.patch(url, json={"title": "  "}).status_code == 400
        assert client.patch(url, json={"title": "x" * 121}).status_code == 422
        assert client.patch("/api/meetings/missing", json={"title": "Name"}).status_code == 404
        session.state = "summarizing"
        assert client.patch(url, json={"title": "Busy"}).status_code == 409
        session.state = "done"
        response = client.patch(url, json={"title": "  User's  title "})
        assert response.status_code == 200 and response.json()["title"] == "User's title"
        assert session.record.title == session.meta.title == "User's title"
        assert not session.record.title_pending
        detail = client.get(url).json()
        assert detail["title"] == "User's title" and "# User's title" in detail["note"]["markdown"]
        data = json.loads((cfg.meetings_dir / f"{meeting.id}.json").read_text())
        assert data["_note_sha"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_rename_rejects_external_notes_without_changes(cfg, tmp_path):
    pipe = pipeline(cfg)
    meeting = record("Keep")
    external = tmp_path / "external.md"
    external.write_text("# Keep\nPrivate contents")
    meeting.note_path = str(external)
    saved = pipe.save_record(meeting)
    before = saved.read_bytes()
    with pytest.raises(ValueError, match="vault"):
        pipe.rename_meeting(meeting.id, "New")
    assert saved.read_bytes() == before and external.read_text() == "# Keep\nPrivate contents"


def test_empty_record_has_safe_fallback_without_calling_model(cfg):
    pipe = pipeline(cfg)
    meeting = record()
    meeting.turns = []
    template = pipe.template("standard")
    pipe.write_note(meeting, pipe.summarize(meeting, template), template)
    assert meeting.title == "Meeting 1000" and meeting.title_pending
