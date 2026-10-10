from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import pytest
from conftest import notes_reply
from typer.testing import CliRunner

from dzomdu.cli import app
from dzomdu.config import dump_config
from dzomdu.llm.schema import MeetingNotes
from dzomdu.models import MeetingRecord, SpeakerAssignment, Turn
from dzomdu.okf import export_bundle
from dzomdu.pipeline import Pipeline
from dzomdu.projects import ProjectManager
from dzomdu.vault import dump_frontmatter, split_frontmatter


def saved(cfg, fake_llm, *, notes=True, meeting_id="20261009-1000-test"):
    record = MeetingRecord(
        id=meeting_id,
        title="Budget: Q&A",
        date="2026-10-09T10:00:00+06:00",
        source_audio=str(cfg.data_dir / "recordings" / "meeting audio.wav"),
        audio_sha="a" * 64,
        duration=20,
        project="Solar Microgrid",
        turns=[
            Turn("t1", "S0", 0, 4, "The survey budget is approved."),
            Turn("t2", "S0", 5, 9, "I will draft the budget."),
        ],
        assignments={"S0": SpeakerAssignment("S0", name="Bob", status="confirmed")},
        asr_model="parakeet",
        diarization_model="pyannote",
    )
    pipe = Pipeline(cfg, llm=fake_llm)
    pipe.vault.ensure_person("Bob", bio="Runs surveys.")
    summary = MeetingNotes.model_validate(notes_reply(["t1", "t2"])) if notes else None
    path = pipe.write_note(record, summary, pipe.template("standard") if notes else None)
    return record, path, pipe


def test_saved_meeting_has_okf_provenance_without_false_verification(cfg, fake_llm):
    record, path, _ = saved(cfg, fake_llm)
    meta, body = split_frontmatter(path.read_text())
    assert meta["type"] == "meeting" and meta["title"] == record.title
    assert meta["status"] == "draft" and "verified" not in meta
    assert meta["description"] and meta["audio_sha256"] == record.audio_sha
    assert meta["sources"][0]["resource"] == Path(record.source_audio).as_uri()
    assert meta["generated"]["by"].startswith(("dzomdu/", "process:"))
    assert datetime.fromisoformat(meta["generated"]["at"]).utcoffset() is not None
    assert meta["date"] == "2026-10-09T10:00+06:00"
    assert "## Transcript" in body and "^t1" in body


def test_export_is_a_portable_linked_bundle_and_preserves_storage(cfg, fake_llm, tmp_path):
    record, note, _ = saved(cfg, fake_llm)
    snapshot = {
        p: p.read_bytes()
        for root in (cfg.vault, cfg.meetings_dir)
        for p in root.rglob("*")
        if p.is_file()
    }
    destination = tmp_path / "bundle"
    assert export_bundle(cfg, destination) == 1
    assert all(path.read_bytes() == original for path, original in snapshot.items())
    index, _ = split_frontmatter((destination / "index.md").read_text())
    assert index == {"okf_version": "0.2"}
    (notes,) = (destination / "meetings").glob("*.md")
    (transcript,) = (destination / "transcripts").glob("*.md")
    note_meta, note_body = split_frontmatter(notes.read_text())
    transcript_meta, transcript_body = split_frontmatter(transcript.read_text())
    assert note_meta["type"] == "Meeting Notes"
    assert transcript_meta["type"] == "Meeting Transcript"
    assert transcript_meta["audio_sha256"] == record.audio_sha
    assert str(cfg.data_dir) not in notes.read_text() + transcript.read_text()
    assert "audio" not in note_meta and "verified" not in note_meta
    assert "[^t2]" in note_body and "t999" not in note_body
    assert {s["id"] for s in note_meta["sources"]} == {"transcript", "t1", "t2"}
    assert '<a id="turn-t2"></a>' in transcript_body
    assert "The survey budget is approved." in transcript_body
    assert "[[" not in note_body + transcript_body
    assert not list(destination.rglob("*.wav")) and not list(destination.rglob("*.sqlite"))
    for path in destination.rglob("*.md"):
        meta, body = split_frontmatter(path.read_text())
        if path.name != "index.md":
            assert isinstance(meta["type"], str)
            assert meta.get("status", "stable") in ("draft", "stable", "deprecated")
        for target in re.findall(r"\]\(([^)]+)\)", body):
            file, _, anchor = unquote(target).partition("#")
            linked = destination / file.lstrip("/") if file.startswith("/") else path.parent / file
            assert linked.is_file(), target
            if anchor:
                assert f'id="{anchor}"' in linked.read_text(), target


def test_export_preserves_user_sections_and_unknown_metadata(cfg, fake_llm, tmp_path):
    _, note, _ = saved(cfg, fake_llm)
    meta, body = split_frontmatter(note.read_text())
    meta["my_custom_property"] = {"reviewer": "Bob"}
    meta["sources"].append({"id": "policy", "resource": "https://example.org/policy"})
    meta["verified"] = {"by": "human:bob", "at": "2026-10-09T11:00:00+06:00"}
    original = dump_frontmatter(meta) + body + "\n## My corrections\n\nKeep this decision.\n"
    note.write_text(original)
    export_bundle(cfg, tmp_path / "edited")
    (exported,) = (tmp_path / "edited" / "meetings").glob("*.md")
    exported_meta, exported_body = split_frontmatter(exported.read_text())
    assert exported_meta["my_custom_property"] == {"reviewer": "Bob"}
    assert "## My corrections\n\nKeep this decision." in exported_body
    assert "generated" not in exported_meta and "verified" not in exported_meta
    assert {"id": "policy", "resource": "https://example.org/policy"} in exported_meta["sources"]
    assert note.read_text() == original


def test_export_transcript_only_and_legacy_naive_dates(cfg, fake_llm, tmp_path):
    record, note, _ = saved(cfg, fake_llm, notes=False)
    json_path = cfg.meetings_dir / f"{record.id}.json"
    data = json.loads(json_path.read_text())
    data["date"] = "2026-10-09T10:00"
    json_path.write_text(json.dumps(data))
    note.unlink()  # recover a missing note from the persistent speaker turns
    export_bundle(cfg, tmp_path / "legacy")
    (exported,) = (tmp_path / "legacy" / "meetings").glob("*.md")
    meta, body = split_frontmatter(exported.read_text())
    assert meta["type"] == "Meeting" and "template" not in meta
    assert datetime.fromisoformat(meta["date"]).utcoffset() is not None
    assert "The survey budget is approved." in body


def test_export_refuses_existing_destination_and_cleans_failed_bundle(cfg, fake_llm, tmp_path):
    saved(cfg, fake_llm)
    destination = tmp_path / "existing"
    destination.mkdir()
    original = destination / "keep.txt"
    original.write_text("Keep this")
    with pytest.raises(ValueError, match="already exists"):
        export_bundle(cfg, destination)
    assert original.read_text() == "Keep this"
    profile = cfg.vault / "People" / "Bob.md"
    profile.write_text("---\ninvalid: [\n---\n")
    import yaml

    with pytest.raises(yaml.YAMLError):
        export_bundle(cfg, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".dzomdu-okf-*"))


def test_project_rename_updates_okf_audio_uri_and_hash(cfg, fake_llm, tmp_path):
    record, note, pipe = saved(cfg, fake_llm)
    source = pipe.vault.project_dir(record.project) / "meeting audio.wav"
    source.write_bytes(b"audio")
    record.source_audio = str(source)
    pipe.write_note(record, None, None, overwrite=True)
    manager = ProjectManager(cfg, pipe.vault, cfg.data_dir / "recordings")
    manager.rename("Solar Microgrid", "Solar Phase Two")
    moved = pipe.vault.project_dir("Solar Phase Two") / "Meetings" / note.name
    meta, _ = split_frontmatter(moved.read_text())
    assert (
        meta["sources"][0]["resource"]
        == (pipe.vault.project_dir("Solar Phase Two") / "meeting audio.wav").as_uri()
    )
    data = json.loads((cfg.meetings_dir / f"{record.id}.json").read_text())
    assert data["_note_sha"] == hashlib.sha256(moved.read_bytes()).hexdigest()


def test_export_disk_failure_never_publishes_partial_bundle(cfg, fake_llm, tmp_path, monkeypatch):
    _, note, _ = saved(cfg, fake_llm)
    original = note.read_bytes()
    write = Path.write_text

    def fail_index(path, *args, **kwargs):
        if path.name == "index.md":
            raise OSError("disk full")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_index)
    with pytest.raises(OSError, match="disk full"):
        export_bundle(cfg, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".dzomdu-okf-*"))
    assert note.read_bytes() == original


def test_export_cli_and_safe_colliding_ids(cfg, fake_llm, tmp_path):
    saved(cfg, fake_llm, meeting_id="A:B")
    saved(cfg, fake_llm, meeting_id="A-B")
    config = tmp_path / "config.toml"
    config.write_text(dump_config(cfg))
    destination = tmp_path / "cli-bundle"
    result = CliRunner().invoke(app, ["export-okf", str(destination), "-c", str(config)])
    assert result.exit_code == 0, result.output
    assert "2 meeting(s)" in result.output
    assert len(list((destination / "meetings").glob("*.md"))) == 2
    result = CliRunner().invoke(app, ["export-okf", str(destination), "-c", str(config)])
    assert result.exit_code == 1 and "already exists" in result.output


def test_export_includes_assigned_project_team(cfg, fake_llm, tmp_path):
    _, _, pipe = saved(cfg, fake_llm)
    manager = ProjectManager(cfg, pipe.vault, cfg.data_dir / "recordings")
    manager.set_members("Solar Microgrid", ["Bob", "Dawa"])
    destination = tmp_path / "bundle-team"
    export_bundle(cfg, destination)
    (project,) = (destination / "projects").glob("*.md")
    meta, _ = split_frontmatter(project.read_text())
    assert meta["team"] == ["Bob", "Dawa"]
    assert not list(destination.rglob(".dzomdu-project.json"))
