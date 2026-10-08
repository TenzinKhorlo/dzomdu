"""End to end: two meetings, voices learned in the first are recognised in the second."""

from __future__ import annotations

from datetime import datetime

from conftest import FakeASR, FakeDiarizer, make_meeting

from dzomdu.pipeline import Pipeline
from dzomdu.vault import Vault, split_frontmatter

MEETING_1 = [
    ("Alice", 0.0, 4.0, "Good morning everyone, let's review the budget."),
    ("Bob", 4.5, 9.0, "Thanks. The survey costs are within the plan."),
    ("Alice", 9.5, 13.0, "Great, then we proceed with the survey."),
    ("Bob", 13.5, 17.0, "I will draft the budget by next Tuesday."),
]
MEETING_2 = [
    ("Bob", 0.0, 4.0, "Let's start, the budget draft is ready."),
    ("Carol", 4.5, 8.0, "I joined from the finance team today."),
    ("Alice", 8.5, 12.0, "Welcome Carol, please review the numbers."),
    ("Bob", 12.5, 15.0, "I'll send the file after this meeting."),
]


def _pipeline(cfg, tmp_path, fake_llm):
    seg1, words1 = make_meeting(tmp_path / "m1.wav", MEETING_1, seed=1)
    seg2, words2 = make_meeting(tmp_path / "m2.wav", MEETING_2, seed=2)
    asr = FakeASR({17: words1, 15: words2})
    diarizer = FakeDiarizer({17: seg1, 15: seg2})
    vault = Vault(cfg.vault)
    vault.init()
    pipe = Pipeline(cfg, asr=asr, diarizer=diarizer, llm=fake_llm, vault=vault)
    return pipe, asr, diarizer


def test_first_meeting_unknown_then_learned(cfg, tmp_path, fake_llm):
    pipe, _, _ = _pipeline(cfg, tmp_path, fake_llm)
    analysis = pipe.analyze(tmp_path / "m1.wav", date=datetime(2026, 10, 7, 10, 0))
    record = analysis.record

    assert [a.status for a in record.assignments.values()] == ["unknown", "unknown"]
    assert record.name_for("SPEAKER_00") == "Unknown speaker 1"
    assert [t.speaker for t in record.turns] == ["SPEAKER_00", "SPEAKER_01"] * 2
    assert record.turns[0].text == "Good morning everyone, let's review the budget."

    pipe.apply_review(analysis, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    assert pipe.learn(analysis) == ["Alice", "Bob"]
    assert {s.name: s.samples for s in pipe.store.list()} == {"Alice": 1, "Bob": 1}
    assert (cfg.vault / "People" / "Alice.md").exists()
    # a reference clip is kept for each learned voice
    assert len(list(cfg.clips_dir.rglob("*.wav"))) == 2


def test_second_meeting_recognises_voices(cfg, tmp_path, fake_llm):
    pipe, _, _ = _pipeline(cfg, tmp_path, fake_llm)
    first = pipe.analyze(tmp_path / "m1.wav")
    pipe.apply_review(first, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    pipe.learn(first)

    # In meeting 2 the anonymous labels are in a different order (Bob speaks first)
    second = pipe.analyze(tmp_path / "m2.wav").record
    by_label = {k: (a.name, a.status) for k, a in second.assignments.items()}
    assert by_label == {
        "SPEAKER_00": ("Bob", "auto"),
        "SPEAKER_01": (None, "unknown"),
        "SPEAKER_02": ("Alice", "auto"),
    }
    assert second.name_for("SPEAKER_01") == "Unknown speaker 1"


def test_attendee_list_restricts_candidates(cfg, tmp_path, fake_llm):
    pipe, _, _ = _pipeline(cfg, tmp_path, fake_llm)
    first = pipe.analyze(tmp_path / "m1.wav")
    pipe.apply_review(first, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    pipe.learn(first)

    record = pipe.analyze(tmp_path / "m2.wav", attendees=["bob"]).record
    names = {a.name for a in record.assignments.values() if a.name}
    assert names == {"Bob"}  # Alice is not a candidate when not listed


def test_unconfirmed_matches_are_not_learned(cfg, tmp_path, fake_llm):
    pipe, _, _ = _pipeline(cfg, tmp_path, fake_llm)
    first = pipe.analyze(tmp_path / "m1.wav")
    pipe.apply_review(first, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    pipe.learn(first)

    second = pipe.analyze(tmp_path / "m2.wav")
    pipe.learn(second)  # no review -> only feedback is logged
    assert {s.name: s.samples for s in pipe.store.list()} == {"Alice": 1, "Bob": 1}
    rows = pipe.store.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    assert rows == 5  # 2 clusters in meeting 1 + 3 in meeting 2


def test_merging_two_clusters_into_one_person(cfg, tmp_path, fake_llm):
    pipe, _, _ = _pipeline(cfg, tmp_path, fake_llm)
    analysis = pipe.analyze(tmp_path / "m1.wav")
    pipe.apply_review(analysis, {"SPEAKER_00": "Alice", "SPEAKER_01": "Alice"})
    assert pipe.learn(analysis) == ["Alice"]
    assert {s.name: s.samples for s in pipe.store.list()} == {"Alice": 1}


def test_cache_skips_models_on_rerun(cfg, tmp_path, fake_llm):
    pipe, asr, diarizer = _pipeline(cfg, tmp_path, fake_llm)
    pipe.analyze(tmp_path / "m1.wav")
    pipe.analyze(tmp_path / "m1.wav")
    assert (asr.calls, diarizer.calls) == (1, 1)
    pipe.analyze(tmp_path / "m1.wav", fresh=True)
    assert (asr.calls, diarizer.calls) == (2, 2)


def test_note_written_and_regenerated(cfg, tmp_path, fake_llm):
    pipe, _, _ = _pipeline(cfg, tmp_path, fake_llm)
    analysis = pipe.analyze(
        tmp_path / "m1.wav", project="Solar Microgrid", date=datetime(2026, 10, 7, 10, 0)
    )
    pipe.apply_review(analysis, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    pipe.learn(analysis)
    record = analysis.record
    template = pipe.template("standard")
    notes = pipe.summarize(record, template)
    path = pipe.write_note(record, notes, template)

    assert path == cfg.vault / "Projects/Solar Microgrid/Meetings/2026-10-07 Budget review.md"
    assert (cfg.vault / "Projects/Solar Microgrid/Solar Microgrid.md").exists()
    text = path.read_text()
    meta, body = split_frontmatter(text)
    assert meta["attendees"] == ["[[Alice]]", "[[Bob]]"]
    assert meta["project"] == "[[Solar Microgrid]]"
    assert "- [ ] [[Bob]] Draft the budget 📅 2026-10-14 ([[#^t4|00:00:14]])" in body
    assert "- [ ] Someone else Book the venue (due: next week)" in body
    assert "t999" not in body  # invented citation dropped
    assert "**[[Alice]]** `00:00:00` Good morning everyone, let's review the budget. ^t1" in body

    # regenerate with another template, replacing the same file
    loaded, sha = pipe.load_record(record.id)
    assert not pipe.note_was_edited(loaded, sha)
    board = pipe.template("board")
    path2 = pipe.write_note(loaded, pipe.summarize(loaded, board), board, overwrite=True)
    assert path2 == path
    assert "## Resolutions" in path.read_text()

    # once the user edits the note in Obsidian, it is detected
    loaded, sha = pipe.load_record(record.id)
    path.write_text(path.read_text() + "\nMy own notes\n")
    assert pipe.note_was_edited(loaded, sha)


def test_llm_receives_people_and_project_context(cfg, tmp_path):
    import httpx
    from conftest import ollama_transport

    from dzomdu.config import LLMConfig
    from dzomdu.llm.client import LLMClient

    log: list[dict] = []
    llm = LLMClient(LLMConfig(), http=httpx.Client(transport=ollama_transport(log=log)))
    pipe, _, _ = _pipeline(cfg, tmp_path, llm)
    pipe.vault.ensure_person("Alice", role="Director", bio="Leads the energy division.")
    analysis = pipe.analyze(tmp_path / "m1.wav", project="Solar Microgrid")
    pipe.apply_review(analysis, {"SPEAKER_00": "Alice", "SPEAKER_01": None})
    pipe.summarize(analysis.record, pipe.template("executive"))

    prompt = log[0]["messages"][1]["content"]
    assert "- Alice: Director. Leads the energy division." in prompt
    assert "Project: Solar Microgrid" in prompt
    assert "busy director" in prompt  # template style instructions
    assert "] Unknown speaker 2: Thanks." in prompt
    assert log[0]["options"]["num_ctx"] == 16384


def test_standing_summary_instructions_reach_the_llm(cfg, tmp_path):
    import httpx
    from conftest import ollama_transport

    from dzomdu.config import LLMConfig
    from dzomdu.llm.client import LLMClient

    cfg.summary_instructions = "Always write in British English."
    log: list[dict] = []
    llm = LLMClient(LLMConfig(), http=httpx.Client(transport=ollama_transport(log=log)))
    pipe, _, _ = _pipeline(cfg, tmp_path, llm)
    analysis = pipe.analyze(tmp_path / "m1.wav")
    pipe.summarize(analysis.record, pipe.template("executive"), "Mention the budget first.")

    prompt = log[0]["messages"][1]["content"]
    # format guidance, then the standing instructions, then this meeting's request
    order = ["busy director", "Always write in British English.", "Mention the budget first."]
    assert [prompt.index(x) for x in order] == sorted(prompt.index(x) for x in order)
