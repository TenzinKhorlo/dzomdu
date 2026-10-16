import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import FakeASR, FakeDiarizer, make_meeting
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket

from dzomdu.audio import read_wav
from dzomdu.llm.client import LLMError
from dzomdu.models import Word
from dzomdu.pipeline import Pipeline
from dzomdu.server.app import create_app
from dzomdu.server.markdown import note_to_html
from dzomdu.server.sessions import Session, SessionManager, SessionMeta
from dzomdu.transcript import LiveSpeakerEdit

SCRIPT = [
    ("Alice", 0.0, 4.0, "Good morning, let's review the budget."),
    ("Bob", 4.5, 9.0, "Costs are within the plan."),
    ("Alice", 9.5, 13.0, "Great, we proceed."),
]


class TolerantASR(FakeASR):
    """Full recordings get the scripted words; live chunks get a placeholder."""

    def transcribe(self, audio):
        words = self.words_by_duration.get(round(audio.duration))
        return words if words is not None else [Word("live", 0.0, 0.4)]


@pytest.fixture
def setup(cfg, tmp_path, fake_llm):
    segs, words = make_meeting(tmp_path / "meeting.wav", SCRIPT)
    pipe = Pipeline(
        cfg,
        asr=TolerantASR({13: words}),
        diarizer=FakeDiarizer({13: segs}),
        llm=fake_llm,
    )
    with TestClient(create_app(cfg, pipe)) as client:
        yield client, tmp_path / "meeting.wav"


def wait_for(client, sid, states, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(f"/api/sessions/{sid}").json()
        if s["state"] in states:
            return s
        assert s["state"] != "error", s["error"]
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {states}; last state {s['state']}")


def test_shell_and_info(setup):
    client, _ = setup
    assert "Start recording" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    info = client.get("/api/info").json()
    assert {t["key"] for t in info["templates"]} >= {"standard", "executive", "board"}
    assert info["status"]["llm"]["ok"] is False  # nothing listens on the default port


def test_upload_review_notes_regenerate(setup, cfg):
    client, wav = setup
    with wav.open("rb") as fh:
        res = client.post(
            "/api/upload",
            files={"file": ("kickoff.wav", fh, "audio/wav")},
            data={"meta": '{"project": "Solar Microgrid", "template": "standard"}'},
        )
    sid = res.json()["id"]
    s = wait_for(client, sid, {"review"})
    assert s["meta"]["title"] is None  # the LLM suggests one
    assert [sp["label"] for sp in s["speakers"]] == ["Unknown speaker 1", "Unknown speaker 2"]
    assert s["speakers"][0]["quotes"][0]["text"].startswith("Good morning")

    clip = client.get(f"/api/sessions/{sid}/clips/SPEAKER_00")
    assert clip.status_code == 200 and clip.headers["content-type"] == "audio/wav"
    assert client.get(f"/api/sessions/{sid}/clips/NOPE").status_code == 404
    bad = client.post(f"/api/sessions/{sid}/review", json={"names": {"NOPE": "x"}})
    assert bad.status_code == 409

    client.post(
        f"/api/sessions/{sid}/review", json={"names": {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}}
    )
    s = wait_for(client, sid, {"done"})
    assert "/Projects/Solar Microgrid/Meetings/" in s["note_path"]
    note = client.get(f"/api/sessions/{sid}/note").json()
    assert "**[[Alice]]**" in note["markdown"]
    assert '<p id="t1"><strong>Alice</strong>' in note["html"]
    assert note["obsidian_url"].startswith("obsidian://open?path=")

    assert [m["title"] for m in client.get("/api/meetings").json()["meetings"]] == ["Budget review"]
    assert {v["name"] for v in client.get("/api/speakers").json()} == {"Alice", "Bob"}

    client.post(f"/api/sessions/{sid}/regenerate", json={"template": "board"})
    wait_for(client, sid, {"done"})
    note = client.get(f"/api/sessions/{sid}/note").json()
    assert "Resolutions" in note["markdown"]

    # an edited note is protected unless forced
    path = cfg.vault / note["path"].split(str(cfg.vault) + "/")[1]
    path.write_text(path.read_text() + "\nmy edits\n")
    res = client.post(f"/api/sessions/{sid}/regenerate", json={"template": "standard"})
    assert res.status_code == 409 and res.json()["detail"].startswith("edited:")
    res = client.post(f"/api/sessions/{sid}/regenerate", json={"force": True})
    assert res.status_code == 200
    wait_for(client, sid, {"done"})

    # reopening a finished meeting from the list
    meeting_id = client.get("/api/meetings").json()["meetings"][0]["id"]
    reopened = client.post(f"/api/meetings/{meeting_id}/open").json()["id"]
    assert client.get(f"/api/sessions/{reopened}").json()["state"] == "done"

    # deleting removes the meeting and its note
    note_file = Path(client.get(f"/api/sessions/{sid}/note").json()["path"])
    assert note_file.exists()
    assert client.delete(f"/api/meetings/{meeting_id}").json() == {"deleted": True}
    assert not note_file.exists()
    assert client.get("/api/meetings").json()["meetings"] == []
    assert client.get(f"/api/meetings/{meeting_id}").status_code == 404
    assert client.delete(f"/api/meetings/{meeting_id}").status_code == 404


@pytest.mark.parametrize("initial_summary", [True, False])
def test_failed_rewrite_preserves_note_and_record_and_can_be_retried(
    setup, cfg, monkeypatch, initial_summary
):
    client, wav = setup
    with wav.open("rb") as fh:
        sid = client.post(
            "/api/upload",
            files={"file": ("meeting.wav", fh, "audio/wav")},
            data={"meta": '{"summarize": ' + str(initial_summary).lower() + "}"},
        ).json()["id"]
    wait_for(client, sid, {"review"})
    client.post(f"/api/sessions/{sid}/review", json={"names": {}})
    done = wait_for(client, sid, {"done"})
    note_path = Path(done["note_path"])
    record_path = cfg.meetings_dir / f"{done['meeting_id']}.json"
    before_note, before_record = note_path.read_bytes(), record_path.read_bytes()
    pipe = client.app.state.manager.pipeline
    original = pipe.summarize

    def fail(*args, **kwargs):
        raise LLMError("Model output did not match the notes schema")

    monkeypatch.setattr(pipe, "summarize", fail)
    response = client.post(f"/api/sessions/{sid}/regenerate", json={"template": "board"})
    assert response.status_code == 200
    failed = wait_for(client, sid, {"error"})
    assert "existing notes were kept" in failed["error"]
    assert note_path.read_bytes() == before_note
    assert record_path.read_bytes() == before_record
    assert client.get(f"/api/sessions/{sid}/note").status_code == 200

    monkeypatch.setattr(pipe, "summarize", original)
    response = client.post(f"/api/sessions/{sid}/regenerate", json={"template": "board"})
    assert response.status_code == 200
    recovered = wait_for(client, sid, {"done"})
    assert recovered["error"] is None and recovered["warning"] is None
    assert "Resolutions" in note_path.read_text()
    assert "Not generated yet" not in note_path.read_text()


def test_initial_summary_failure_still_saves_transcript_with_warning(setup, monkeypatch):
    client, wav = setup

    def fail(*args, **kwargs):
        raise LLMError("LLM unavailable")

    monkeypatch.setattr(client.app.state.manager.pipeline, "summarize", fail)
    with wav.open("rb") as fh:
        sid = client.post(
            "/api/upload",
            files={"file": ("meeting.wav", fh, "audio/wav")},
        ).json()["id"]
    wait_for(client, sid, {"review"})
    client.post(f"/api/sessions/{sid}/review", json={"names": {}})
    done = wait_for(client, sid, {"done"})
    assert "LLM unavailable" in done["warning"]
    note = client.get(f"/api/sessions/{sid}/note").json()["markdown"]
    assert "Not generated yet" in note and "review the budget" in note


def test_record_over_websocket_with_live_preview(setup, cfg):
    client, wav = setup
    samples, _ = read_wav(wav)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    sid = client.post("/api/sessions", json={"title": "Weekly", "live": True}).json()["id"]
    assert client.post("/api/sessions", json={}).status_code == 200  # not recording yet
    with client.websocket_connect(f"/api/sessions/{sid}/audio") as ws:
        for i in range(0, len(pcm), 8000):
            ws.send_bytes(pcm[i : i + 8000])
        recording = client.get(f"/api/sessions/{sid}").json()
        assert recording["state"] == "recording"
        assert client.post("/api/sessions", json={}).status_code == 409  # one at a time
        ws.send_text("stop")
    s = wait_for(client, sid, {"review"})
    assert s["meta"]["title"] == "Weekly"
    assert len(s["speakers"]) == 2
    wav_files = list((cfg.data_dir / "recordings").glob(f"{sid}.*"))
    assert [p.suffix for p in wav_files] == [".wav"]


@pytest.mark.parametrize("ending", ["disconnect", "stop", "invalid_session"])
def test_audio_socket_transport_disappears_during_close(setup, cfg, ending):
    client, wav = setup
    samples, _ = read_wav(wav)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    sid = client.post("/api/sessions", json={"live": False}).json()["id"]
    endpoint = next(route.endpoint for route in client.app.routes if route.name == "audio")
    incoming = iter(
        [
            {"type": "websocket.connect"},
            {"type": "websocket.receive", "bytes": pcm},
            {"type": "websocket.disconnect", "code": 1001}
            if ending == "disconnect"
            else {"type": "websocket.receive", "text": "stop"},
        ]
    )
    closes = []

    async def receive():
        return next(incoming)

    async def send(message):
        if message["type"] == "websocket.close":
            closes.append(message["code"])
            # Starlette converts this into WebSocketDisconnect(1006), as Uvicorn
            # does when the browser vanishes before the closing frame is sent.
            raise OSError("Browser connection lost")

    socket = WebSocket({"type": "websocket"}, receive, send)
    asyncio.run(endpoint(socket, "missing" if ending == "invalid_session" else sid))
    assert closes == [4400 if ending == "invalid_session" else 1000]
    if ending == "invalid_session":
        assert client.get(f"/api/sessions/{sid}").json()["state"] == "new"
        return
    wait_for(client, sid, {"review"})
    recording = cfg.data_dir / "recordings" / f"{sid}.wav"
    saved, _ = read_wav(recording)
    assert len(saved) == len(samples)
    assert not recording.with_suffix(".pcm").exists()


def test_cancel_discards_audio(setup, cfg):
    client, _ = setup
    sid = client.post("/api/sessions", json={"live": False}).json()["id"]
    with client.websocket_connect(f"/api/sessions/{sid}/audio") as ws:
        ws.send_bytes(b"\x00\x01" * 16000)
        time.sleep(0.05)
        assert client.post(f"/api/sessions/{sid}/cancel").json()["state"] == "cancelled"
        ws.send_text("stop")
    assert list((cfg.data_dir / "recordings").glob(f"{sid}.*")) == []


def test_interrupted_recordings_are_recovered(cfg, fake_llm):
    rec = cfg.data_dir / "recordings"
    rec.mkdir(parents=True)
    (rec / "crashed.pcm").write_bytes(b"\x00\x10" * 32000)
    with TestClient(create_app(cfg, Pipeline(cfg, llm=fake_llm))) as client:
        assert client.get("/api/info").json()["recovered"] == [str(rec / "crashed.wav")]


def test_note_html_translates_obsidian_syntax():
    md = (
        "---\ntype: meeting\n---\n# T\n\n- [ ] [[Bob]] Draft 📅 2026-10-14 ([[#^t2|00:00:10]])\n\n"
        "| a | b |\n|---|---|\n| x ([[#^t2\\|00:00:10]]) | [[Bob]] |\n\n"
        "**[[Alice]]** `00:00:00` Hi <script>alert(1)</script> ^t1\n"
    )
    html = note_to_html(md.replace("# T\n", "# T\n\nSummary paragraph.\n"))
    assert "<p>Summary paragraph.</p>" in html
    assert '<a href="#t2">00:00:10</a>' in html and "☐ <strong>Bob</strong>" in html
    assert '<p id="t1"><strong>Alice</strong>' in html
    assert "<script>" not in html and "type: meeting" not in html
    assert html.count("<td>") == 2


def test_live_segments_update_in_place_by_revision():
    s = Session("x", SessionMeta(), "recording")
    s.put_live(
        {"id": 1, "start": 0.0, "end": 0.8, "partial": True, "speaker": None, "text": "Let's"}
    )
    s.put_live(
        {
            "id": 1,
            "start": 0.0,
            "end": 2.0,
            "partial": False,
            "speaker": None,
            "text": "Let's start.",
        }
    )
    s.put_live(
        {"id": 2, "start": 2.5, "end": 3.1, "partial": True, "speaker": None, "text": "Good"}
    )
    snap = SessionManager.snapshot(None, s, live_rev=0)  # type: ignore[arg-type]
    assert [(seg["id"], seg["text"]) for seg in snap["live"]] == [(1, "Let's start."), (2, "Good")]
    assert snap["live_rev"] == 3
    assert SessionManager.snapshot(None, s, live_rev=2)["live"][0]["id"] == 2  # type: ignore[arg-type]
    # older clients that page by id only get final segments
    assert [seg["id"] for seg in SessionManager.snapshot(None, s)["live"]] == [1]  # type: ignore[arg-type]


def test_warmup_loads_models_once(setup):
    client, _ = setup
    assert client.post("/api/warmup").json() == {"ok": True}
    assert client.post("/api/warmup").json() == {"ok": True}  # already loading or loaded


def test_settings_change_llm_and_vault(cfg, tmp_path, fake_llm):
    from dzomdu.config import load_config

    path = tmp_path / "config.toml"
    pipe = Pipeline(cfg, llm=fake_llm)
    with TestClient(create_app(cfg, pipe, config_path=path)) as client:
        before = client.get("/api/settings").json()
        assert before["llm"]["api_key_set"] is False and before["vault"] == str(cfg.vault)

        cloud = {
            "api": "ollama",
            "base_url": "https://ollama.com",
            "model": "gpt-oss:120b",
            "api_key": "secret-key",
        }
        new_vault = tmp_path / "elsewhere" / "Notes"
        res = client.put("/api/settings", json={"llm": cloud, "vault": str(new_vault)})
        assert res.status_code == 200
        body = res.json()
        assert body["llm"]["api_key_set"] is True and "secret-key" not in res.text
        assert body["vault"] == str(new_vault.resolve())
        assert (new_vault / "People").is_dir() and (new_vault / "Templates").is_dir()
        assert pipe.vault.root == new_vault.resolve()

        saved = load_config(path)  # persisted for the next start
        assert saved.llm.base_url == "https://ollama.com" and saved.llm.api_key == "secret-key"
        assert saved.vault == new_vault.resolve()
        assert oct(path.stat().st_mode & 0o777) == "0o600"

        # leaving the key blank keeps it; clearing removes it
        local = {"api": "ollama", "base_url": "http://localhost:11434", "model": "qwen3:14b"}
        client.put("/api/settings", json={"llm": local})
        assert load_config(path).llm.api_key == "secret-key"
        client.put("/api/settings", json={"llm": {**local, "clear_api_key": True}})
        assert load_config(path).llm.api_key == ""

        bad = client.put("/api/settings", json={"llm": {**local, "base_url": "localhost"}})
        assert bad.status_code == 400
        file_path = tmp_path / "afile"
        file_path.write_text("x")
        assert client.put("/api/settings", json={"vault": str(file_path)}).status_code == 400
        assert client.post("/api/settings/llm/test", json={**local, "api": "x"}).status_code == 400


def test_create_project(setup, cfg):
    client, _ = setup
    res = client.post("/api/projects", json={"name": "  Solar Microgrid "})
    assert res.json() == {"name": "Solar Microgrid", "created": True}
    assert (cfg.vault / "Projects" / "Solar Microgrid" / "Solar Microgrid.md").exists()
    assert client.post("/api/projects", json={"name": "Solar Microgrid"}).json()["created"] is False
    assert client.post("/api/projects", json={"name": "A/B: plan"}).json()["name"] == "A-B- plan"
    assert client.post("/api/projects", json={"name": "   "}).status_code == 400
    names = {p["name"] for p in client.get("/api/projects").json()}
    assert names >= {"Solar Microgrid", "A-B- plan"}
    assert "Solar Microgrid" in client.get("/api/info").json()["projects"]


def test_custom_formats_and_standing_instructions(cfg, tmp_path, fake_llm):
    from dzomdu.config import load_config

    path = tmp_path / "config.toml"
    pipe = Pipeline(cfg, llm=fake_llm)
    with TestClient(create_app(cfg, pipe, config_path=path)) as client:
        formats = {t["key"]: t for t in client.get("/api/templates").json()}
        assert formats["standard"]["builtin"] and not formats["standard"]["edited"]
        assert formats["standard"]["default"]

        new = {
            "name": "Weekly Sync!",
            "description": "Short weekly note",
            "instructions": "Keep it to five bullets.\nUse plain language.",
            "body": "## Recap\n\n{{ notes.summary }}\n\n{% for a in notes.action_items %}\n"
            "- [ ] {{ task(a) }}\n{% endfor %}",
        }
        sections = [
            {"title": "Meeting purpose", "type": "text", "description": "One sentence."},
            {"title": "Key takeaways", "type": "items", "description": "Top outcomes."},
        ]
        new["body"] += (
            "\n\n{{ notes.extra.meeting_purpose }}\n"
            "{% for k in notes.extra.key_takeaways %}{{ k.title }}{% endfor %}"
        )
        assert (
            client.post("/api/templates", json={**new, "sections": sections[:1]}).status_code == 400
        )
        made = client.post("/api/templates", json={**new, "sections": sections})
        assert made.status_code == 200 and made.json()["key"] == "weekly-sync"
        assert [(x["key"], x["type"]) for x in made.json()["sections"]] == [
            ("meeting_purpose", "text"),
            ("key_takeaways", "items"),
        ]
        blank = [{"title": "  ", "type": "text", "key": "notes"}]
        assert client.post("/api/templates", json={**new, "sections": blank}).status_code == 400
        dup = [{"title": "Notes", "type": "text"}, {"title": "notes", "type": "list"}]
        assert (
            client.post("/api/templates", json={**new, "name": "Dup", "sections": dup}).status_code
            == 400
        )
        new["sections"] = sections
        assert not made.json()["builtin"]
        assert client.post("/api/templates", json=new).status_code == 409
        assert (cfg.vault / "Templates" / "Minutes" / "weekly-sync.md").exists()
        assert "weekly-sync" in {t["key"] for t in client.get("/api/info").json()["templates"]}

        # mistakes in the layout are caught when saving
        bad = client.put("/api/templates/weekly-sync", json={**new, "body": "{% for x in %}"})
        assert bad.status_code == 400 and "Layout error" in bad.json()["detail"]
        unknown = client.put("/api/templates/weekly-sync", json={**new, "body": "{{ nope.x }}"})
        assert unknown.status_code == 400

        # saving a built-in format with its own fields keeps their keys, so its layout still works
        idisc = {t["key"]: t for t in client.get("/api/templates").json()}["internal-discussion"]
        assert [x["key"] for x in idisc["sections"]][:2] == ["meeting_type", "purpose"]
        again = {k: idisc[k] for k in ("name", "description", "instructions", "body", "sections")}
        res = client.put("/api/templates/internal-discussion", json=again)
        assert res.status_code == 200, res.text
        assert [x["key"] for x in res.json()["sections"]] == [x["key"] for x in idisc["sections"]]
        client.delete("/api/templates/internal-discussion")

        edited = client.put("/api/templates/standard", json={**new, "name": "Standard"})
        assert edited.json()["edited"] is True
        assert client.delete("/api/templates/standard").json() == {"reset": True}
        assert not {t["key"]: t for t in client.get("/api/templates").json()}["standard"]["edited"]

        # standing summary instructions and the default format persist to the config file
        res = client.put(
            "/api/settings",
            json={
                "summary_instructions": " Write in British English.\nBe brief. ",
                "default_template": "weekly-sync",
            },
        )
        assert res.json()["default_template"] == "weekly-sync"
        saved = load_config(path)
        assert saved.summary_instructions == "Write in British English.\nBe brief."
        assert saved.default_template == "weekly-sync"
        assert client.put("/api/settings", json={"default_template": "nope"}).status_code == 400

        # the default format can't be deleted from under the app; others can
        assert client.delete("/api/templates/weekly-sync").status_code == 409
        client.put("/api/settings", json={"default_template": "standard"})
        assert client.delete("/api/templates/weekly-sync").json() == {"deleted": True}
        assert client.delete("/api/templates/weekly-sync").status_code == 404


def live_segment(sid, start, end, speaker, text="Speech.", partial=False):
    return {
        "id": sid,
        "start": start,
        "end": end,
        "speaker": speaker,
        "text": text,
        "partial": partial,
    }


def test_live_names_survive_model_updates_and_apply_to_future_speech():
    s = Session("live-edit", SessionMeta(), "recording")
    s.state = "recording"
    s.put_live(live_segment(1, 0, 3, "Speaker 1"))
    s.edit_live(LiveSpeakerEdit(segment_ids=[1], name="Alice", rename_speaker=True))
    s.put_live(live_segment(1, 0, 3, "Speaker 9", "Improved transcript."))
    s.put_live(live_segment(2, 4, 6, "Speaker 1"))
    assert [seg["speaker"] for seg in s.live_segments] == ["Alice", "Alice"]
    s.edit_live(LiveSpeakerEdit(segment_ids=[2], name="Bob"))
    s.put_live(live_segment(2, 4, 6, "Speaker 1", "Late voice match."))
    assert s.live_segments[1]["speaker"] == "Bob"
    assert s.live_segments[0]["speaker"] == "Alice"
    s.put_live(live_segment(3, 7, 8, "Speaker 2"))
    s.edit_live(LiveSpeakerEdit(segment_ids=[3], name="Bob", rename_speaker=True))
    s.edit_live(LiveSpeakerEdit(segment_ids=[2], name="Robert", rename_speaker=True))
    s.put_live(live_segment(4, 9, 11, "Speaker 2"))
    assert [seg["speaker"] for seg in s.live_segments] == ["Alice", "Robert", "Robert", "Robert"]
    assert all(seg["corrected"] for seg in s.live_segments)


def test_live_correction_api_validates_state_partial_and_conflicts(setup):
    client, _ = setup
    manager = client.app.state.manager
    s = manager.create(SessionMeta(), "recording")
    s.state = "recording"
    s.put_live(live_segment(1, 0, 3, "Speaker 1"))
    s.put_live(live_segment(2, 4, 4.5, None, partial=True))
    url = f"/api/sessions/{s.id}/live-speakers"
    assert client.patch(url, json={"segment_ids": [2], "name": "Alice"}).status_code == 409
    assert client.patch(url, json={"segment_ids": [99], "name": "Alice"}).status_code == 400
    assert client.patch(url, json={"segment_ids": [1], "name": "  "}).status_code == 400
    assert (
        client.patch(
            url, json={"segment_ids": [1], "name": "Alice", "revisions": {"1": 0}}
        ).status_code
        == 409
    )
    response = client.patch(url, json={"segment_ids": [1], "name": "Alice", "revisions": {"1": 1}})
    assert response.status_code == 200
    assert response.json()["live"][0]["speaker"] == "Alice"
    s.state = "processing"
    assert client.patch(url, json={"segment_ids": [1], "name": "Bob"}).status_code == 409


def test_live_corrections_use_word_times_and_remain_in_end_review(setup):
    client, wav = setup
    manager = client.app.state.manager
    s = manager.create(SessionMeta(), "recording")
    s.state = "recording"
    s.put_live(live_segment(1, 0, 4, "Speaker 1"))
    s.put_live(live_segment(2, 4.5, 9, "Speaker 1"))  # Bob was wrongly grouped with Alice
    s.edit_live(LiveSpeakerEdit(segment_ids=[1], name="Alice", rename_speaker=True))
    s.edit_live(LiveSpeakerEdit(segment_ids=[2], name="Bob"))
    s.put_live(live_segment(3, 9.5, 13, "Speaker 1"))
    analysis = manager.pipeline.analyze(wav, title="Live review")
    texts = [turn.text for turn in analysis.record.turns]
    manager._apply_live_review(s, analysis)
    s.record, s.analysis, s.state = analysis.record, analysis, "review"
    assert [turn.text for turn in s.record.turns] == texts
    assert [s.record.assignments[turn.speaker].suggestion for turn in s.record.turns] == [
        "Alice",
        "Bob",
        "Alice",
    ]
    review = client.get(f"/api/sessions/{s.id}").json()
    assert review["state"] == "review"
    assert {speaker["suggestion"] for speaker in review["speakers"]} == {"Alice", "Bob"}
    assert all(speaker["has_clip"] for speaker in review["speakers"])
    assert manager.pipeline.store.list() == []  # only the final review learns voiceprints
    names = {speaker["cluster"]: speaker["suggestion"] for speaker in review["speakers"]}
    client.post(f"/api/sessions/{s.id}/review", json={"names": names})
    done = wait_for(client, s.id, {"done"})
    detail = client.get(f"/api/meetings/{done['meeting_id']}").json()
    assert [turn["label"] for turn in detail["turns"]] == ["Alice", "Bob", "Alice"]
    assert {voice["name"] for voice in client.get("/api/speakers").json()} == {"Alice", "Bob"}


def finish_for_corrections(client, wav):
    with wav.open("rb") as fh:
        sid = client.post("/api/upload", files={"file": ("meeting.wav", fh, "audio/wav")}).json()[
            "id"
        ]
    wait_for(client, sid, {"review"})
    client.post(
        f"/api/sessions/{sid}/review", json={"names": {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}}
    )
    done = wait_for(client, sid, {"done"})
    return done["meeting_id"]


def test_finished_batch_corrects_speakers_and_words_then_rewrites_once(setup, cfg, monkeypatch):
    client, wav = setup
    mid = finish_for_corrections(client, wav)
    before = client.get(f"/api/meetings/{mid}").json()
    pipe = client.app.state.manager.pipeline
    original = pipe.summarize
    calls = []

    def summarize(record, *args, **kwargs):
        calls.append(record.to_dict())
        return original(record, *args, **kwargs)

    monkeypatch.setattr(pipe, "summarize", summarize)
    voices = client.get("/api/speakers").json()
    response = client.patch(
        f"/api/meetings/{mid}/transcript",
        json={
            "revision": 0,
            "edits": [
                {"turn_ids": [], "speaker": "SPEAKER_00", "name": "Alicia", "rename_speaker": True},
                {
                    "turn_ids": ["t2"],
                    "speaker": "SPEAKER_00",
                    "text": "Costs are above the revised plan.",
                },
                {"turn_ids": ["t3"], "name": "Carol"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    wait_for(client, response.json()["session_id"], {"done"})
    after = client.get(f"/api/meetings/{mid}").json()
    assert after["transcript_revision"] == 1
    assert after["notes_stale"] is False
    assert [turn["label"] for turn in after["turns"]] == ["Alicia", "Alicia", "Carol"]
    assert after["turns"][1]["text"] == "Costs are above the revised plan."
    assert [(t["id"], t["start"], t["end"]) for t in after["turns"]] == [
        (t["id"], t["start"], t["end"]) for t in before["turns"]
    ]
    assert {s["name"] for s in after["speakers"]} == {"Alicia", "Carol"}
    assert "above the revised plan" in after["note"]["markdown"]
    assert "**[[Carol]]**" in after["note"]["markdown"]
    assert len(calls) == 1 and calls[0]["turns"][1]["text"].startswith("Costs are above")
    assert [(v["name"], v["samples"]) for v in client.get("/api/speakers").json()] == [
        (v["name"], v["samples"]) for v in voices
    ]
    record = json.loads((cfg.meetings_dir / f"{mid}.json").read_text())
    assert record["transcript_revision"] == 1
    second = client.patch(
        f"/api/meetings/{mid}/transcript",
        json={
            "revision": 1,
            "edits": [{"turn_ids": ["t1"], "text": "Second correction batch."}],
        },
    )
    assert second.status_code == 200
    assert second.json()["session_id"] != response.json()["session_id"]
    wait_for(client, second.json()["session_id"], {"done"})
    assert len(calls) == 2
    assert client.get(f"/api/meetings/{mid}").json()["transcript_revision"] == 2
    # A concurrent editor cannot overwrite these corrections.
    assert (
        client.patch(
            f"/api/meetings/{mid}/transcript",
            json={"revision": 0, "edits": [{"turn_ids": ["t1"], "text": "Stale text"}]},
        ).status_code
        == 409
    )


def test_corrections_survive_failed_auto_rewrite_and_keep_notes(setup, cfg, monkeypatch):
    client, wav = setup
    mid = finish_for_corrections(client, wav)
    before = client.get(f"/api/meetings/{mid}").json()

    def fail(*args, **kwargs):
        raise LLMError("Offline")

    monkeypatch.setattr(client.app.state.manager.pipeline, "summarize", fail)
    response = client.patch(
        f"/api/meetings/{mid}/transcript",
        json={"revision": 0, "edits": [{"turn_ids": ["t1"], "text": "A corrected opening."}]},
    )
    wait_for(client, response.json()["session_id"], {"error"})
    after = client.get(f"/api/meetings/{mid}").json()
    assert after["turns"][0]["text"] == "A corrected opening."
    assert after["notes_stale"] is True
    assert after["summary"] == before["summary"]
    assert (
        after["note"]["markdown"].split("## Transcript")[0]
        == before["note"]["markdown"].split("## Transcript")[0]
    )
    assert "A corrected opening." in after["note"]["markdown"]


def test_invalid_batch_is_atomic_and_manual_notes_remain_protected(setup, cfg):
    client, wav = setup
    mid = finish_for_corrections(client, wav)
    before = client.get(f"/api/meetings/{mid}").json()
    record_path = cfg.meetings_dir / f"{mid}.json"
    original = record_path.read_bytes()
    invalid = {
        "revision": 0,
        "edits": [
            {"turn_ids": ["t1"], "text": "Changed"},
            {"turn_ids": ["missing"], "speaker": "SPEAKER_01"},
        ],
    }
    assert client.patch(f"/api/meetings/{mid}/transcript", json=invalid).status_code == 400
    assert record_path.read_bytes() == original
    note = Path(before["note"]["path"])
    note.write_text(note.read_text() + "\n## Personal notes\n\nKeep this text.\n")
    response = client.patch(
        f"/api/meetings/{mid}/transcript",
        json={"revision": 0, "edits": [{"turn_ids": ["t1"], "text": "A corrected opening."}]},
    )
    assert response.status_code == 200
    assert response.json()["session_id"] is None
    assert "manual edits" in response.json()["warning"]
    assert "Keep this text." in note.read_text()
    assert "A corrected opening." in note.read_text()
    assert client.get(f"/api/meetings/{mid}").json()["notes_stale"] is True


def test_live_edit_can_split_a_full_pass_turn_at_real_word_boundaries(setup):
    client, wav = setup
    manager = client.app.state.manager
    s = manager.create(SessionMeta(), "recording")
    s.state = "recording"
    s.put_live(live_segment(1, 0, 1.9, "Speaker 1"))
    s.put_live(live_segment(2, 1.9, 4, "Speaker 1"))
    s.edit_live(LiveSpeakerEdit(segment_ids=[1], name="Alice"))
    s.edit_live(LiveSpeakerEdit(segment_ids=[2], name="Bob"))
    analysis = manager.pipeline.analyze(wav)
    words_before = " ".join(turn.text for turn in analysis.record.turns)
    manager._apply_live_review(s, analysis)
    assert " ".join(turn.text for turn in analysis.record.turns) == words_before
    assert len(analysis.record.turns) == 4
    assert analysis.record.assignments[analysis.record.turns[0].speaker].suggestion == "Alice"
    assert analysis.record.assignments[analysis.record.turns[1].speaker].suggestion == "Bob"
    assert analysis.record.turns[1].start in {round(word.start, 2) for word in analysis.words}


def test_dragging_to_an_anonymous_live_speaker_does_not_create_a_person(setup):
    client, wav = setup
    manager = client.app.state.manager
    s = manager.create(SessionMeta(), "recording")
    s.state = "recording"
    s.put_live(live_segment(1, 0, 4, "Speaker 1"))
    s.edit_live(LiveSpeakerEdit(segment_ids=[1], name="Speaker 2"))
    analysis = manager.pipeline.analyze(wav)
    manager._apply_live_review(s, analysis)
    assignment = analysis.record.assignments[analysis.record.turns[0].speaker]
    assert assignment.unknown_label == "Speaker 2"
    assert assignment.name is None and assignment.suggestion is None
    assert assignment.status == "unknown"
