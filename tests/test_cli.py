from conftest import FakeASR, FakeDiarizer, make_meeting
from typer.testing import CliRunner

from dzomdu import asr as asr_mod
from dzomdu import diarize as diarize_mod
from dzomdu.cli import app
from dzomdu.config import load_config

runner = CliRunner()


def _init(tmp_path):
    config = tmp_path / "config.toml"
    result = runner.invoke(
        app, ["init", "--vault", str(tmp_path / "vault"), "--config", str(config)]
    )
    assert result.exit_code == 0, result.output
    text = config.read_text().replace(
        f'data_dir = "{load_config(config).data_dir}"', f'data_dir = "{tmp_path / "data"}"'
    )
    config.write_text(
        text.replace('backend = "parakeet"', 'backend = "fake"').replace(
            'backend = "pyannote"', 'backend = "fake"'
        )
    )
    return config


def test_init_templates_people(tmp_path):
    config = _init(tmp_path)
    assert (tmp_path / "vault" / "Templates" / "Minutes" / "board.md").exists()
    result = runner.invoke(app, ["templates", "-c", str(config)])
    assert "standard" in result.output and "board" in result.output
    result = runner.invoke(
        app, ["people", "add", "Karma Wangmo", "--role", "PM", "-c", str(config)]
    )
    assert result.exit_code == 0
    assert "role: PM" in (tmp_path / "vault" / "People" / "Karma Wangmo.md").read_text()


def test_process_without_llm_and_speakers_commands(tmp_path, monkeypatch):
    config = _init(tmp_path)
    script = [("Alice", 0, 4, "Welcome to the review."), ("Bob", 4.5, 8, "Thanks Alice.")]
    segs, words = make_meeting(tmp_path / "m.wav", script)
    monkeypatch.setitem(asr_mod.BACKENDS, "fake", lambda c: FakeASR({8: words}))
    monkeypatch.setitem(diarize_mod.BACKENDS, "fake", lambda c: FakeDiarizer({8: segs}))

    result = runner.invoke(
        app,
        [
            "process",
            str(tmp_path / "m.wav"),
            "--no-llm",
            "--title",
            "Review",
            "--date",
            "2026-10-07T09:30",
            "-c",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    note = tmp_path / "vault" / "Meetings" / "2026-10-07 Review.md"
    assert note.exists()
    assert "**Unknown speaker 1** `00:00:00` Welcome to the review. ^t1" in note.read_text()

    # enrol Alice from the first 4 seconds, then she is recognised
    result = runner.invoke(
        app,
        [
            "speakers",
            "enroll",
            "Alice",
            str(tmp_path / "m.wav"),
            "--end",
            "4",
            "--consent",
            "-c",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["speakers", "list", "-c", str(config)])
    assert "Alice" in result.output and "yes" in result.output

    result = runner.invoke(
        app,
        ["process", str(tmp_path / "m.wav"), "--no-llm", "--title", "Review", "-c", str(config)],
    )
    assert result.exit_code == 0, result.output
    (second,) = [p for p in (tmp_path / "vault" / "Meetings").glob("*Review*.md") if p != note]
    assert "**[[Alice]]** `00:00:00` Welcome to the review." in second.read_text()

    result = runner.invoke(app, ["speakers", "forget", "Alice", "-y", "-c", str(config)])
    assert result.exit_code == 0 and "Forgot" in result.output


def test_process_reports_bad_input(tmp_path):
    config = _init(tmp_path)
    result = runner.invoke(app, ["process", str(tmp_path / "missing.wav"), "-c", str(config)])
    assert result.exit_code == 1
    result = runner.invoke(app, ["process", "x.wav", "--date", "tuesday", "-c", str(config)])
    assert result.exit_code == 1 and "Invalid --date" in result.output
