from conftest import notes_reply

from dzomdu.config import Config, dump_config, load_config
from dzomdu.llm.schema import MeetingNotes
from dzomdu.models import MeetingRecord, SpeakerAssignment, Turn
from dzomdu.notes.render import render_note
from dzomdu.notes.templates import list_templates, load_template
from dzomdu.vault import Vault, safe_filename, split_frontmatter


def record() -> MeetingRecord:
    return MeetingRecord(
        id="20261007-1000-abc123",
        title="Kickoff",
        date="2026-10-07T10:00",
        source_audio="/rec/kickoff.m4a",
        audio_sha="abc",
        duration=3125,
        project="Solar Microgrid",
        turns=[
            Turn("t1", "S0", 5, 9, "Good morning."),
            Turn("t2", "S1", 10, 14, "Thanks, first item."),
            Turn("t3", "S2", 15, 20, "Can I add something?"),
        ],
        assignments={
            "S0": SpeakerAssignment("S0", name="Bob", status="confirmed"),
            "S1": SpeakerAssignment(
                "S1", status="suggested", suggestion="Alice", unknown_label="Unknown speaker 1"
            ),
            "S2": SpeakerAssignment("S2", unknown_label="Unknown speaker 2"),
        },
        asr_model="parakeet",
        diarization_model="pyannote",
    )


def test_every_builtin_template_renders(tmp_path):
    full = MeetingNotes.model_validate(notes_reply(["t1", "t3"]))
    empty = MeetingNotes(summary="Nothing much.")
    for t in list_templates(None):
        for notes in (full, empty):
            text = render_note(record(), notes, t, "qwen3:14b")
            meta, body = split_frontmatter(text)
            assert meta["template"] == t.key and body.startswith("# Kickoff")
            assert "## Transcript" in body


def test_rendering_details():
    notes = MeetingNotes.model_validate(notes_reply(["t1", "t2"]))
    text = render_note(record(), notes, load_template("standard", None), "qwen3:14b")
    meta, body = split_frontmatter(text)
    assert meta["attendees"] == ["[[Bob]]"]
    assert meta["unidentified_speakers"] == ["Alice?", "Unknown speaker 2"]
    assert meta["duration"] == "52m" and meta["models"]["llm"] == "qwen3:14b"
    assert meta["tags"] == ["meeting", "solar-microgrid"]
    assert "- [ ] [[Bob]] Draft the budget 📅 2026-10-14 ([[#^t2|00:00:10]])" in body
    assert "**[[Bob]]** `00:00:05` Good morning. ^t1" in body
    assert "**Alice?** `00:00:10` Thanks, first item. ^t2" in body  # unconfirmed: no link
    assert "**Unknown speaker 2** `00:00:15`" in body


def test_board_table_escapes_pipes():
    notes = MeetingNotes.model_validate(notes_reply(["t1", "t2"]))
    body = render_note(record(), notes, load_template("board", None))
    row = next(line for line in body.splitlines() if line.startswith("| 1 |"))
    assert "[[#^t2\\|00:00:10]]" in row and row.count(" | ") == 3


def test_note_without_llm():
    text = render_note(record(), None, None)
    assert "dzomdu regenerate 20261007-1000-abc123" in text
    assert "template" not in split_frontmatter(text)[0]


def test_vault_templates_override_builtin(tmp_path):
    vault = Vault(tmp_path)
    vault.init()
    assert {p.name for p in vault.templates_dir.iterdir()} >= {"standard.md", "board.md"}
    (vault.templates_dir / "standard.md").write_text(
        "---\nname: Mine\ninstructions: Be terse.\n---\n{{ notes.summary }}\n"
    )
    (vault.templates_dir / "standup.md").write_text("---\nname: Standup\n---\nx\n")
    t = load_template("standard", vault.templates_dir)
    assert (t.name, t.instructions) == ("Mine", "Be terse.")
    assert "standup" in {t.key for t in list_templates(vault.templates_dir)}


def test_people_and_projects(tmp_path):
    vault = Vault(tmp_path)
    vault.ensure_person("Karma Wangmo")
    assert vault.person_context("Karma Wangmo") == ""  # placeholder text is ignored
    vault.ensure_person("Karma Wangmo", role="PM", organisation="GovTech", bio="Runs pilots.")
    assert vault.person_context("Karma Wangmo") == "- Karma Wangmo: PM, GovTech. Runs pilots."
    vault.update_person("Karma Wangmo", bio="Runs energy pilots.")
    assert "Runs pilots" not in vault.person_path("Karma Wangmo").read_text()

    path = vault.ensure_project("Solar: Phase 1")
    assert path == tmp_path / "Projects/Solar- Phase 1/Solar- Phase 1.md"
    assert vault.project_context("Solar: Phase 1") == ""
    path.write_text(path.read_text().replace("_Goals, scope", "Pilot in Punakha.\n_Goals, scope"))
    assert vault.project_context("Solar: Phase 1") == "Pilot in Punakha."


def test_meeting_paths_are_unique(tmp_path):
    from datetime import datetime

    vault = Vault(tmp_path)
    first = vault.meeting_path(datetime(2026, 10, 7), "Kickoff", None)
    first.write_text("x")
    assert vault.meeting_path(datetime(2026, 10, 7), "Kickoff", None).name == (
        "2026-10-07 Kickoff (2).md"
    )
    assert safe_filename('a/b:c*?"d') == "a-b-c---d"


def test_config_roundtrip(tmp_path):
    cfg = Config(vault=tmp_path / "v", data_dir=tmp_path / "d")
    cfg.llm.model = 'gpt-oss:20b "quoted"'
    cfg.speakers.accept_threshold = 0.66
    path = tmp_path / "c.toml"
    path.write_text(dump_config(cfg))
    loaded = load_config(path)
    assert loaded == cfg
    path.write_text("[llm]\nbogus = 1\n")
    import pytest

    with pytest.raises(ValueError, match="bogus"):
        load_config(path)
