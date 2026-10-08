import json
from datetime import date

import pytest
from conftest import FakeDiarizer, make_meeting
from fastapi.testclient import TestClient
from test_server import SCRIPT, TolerantASR, wait_for

from dzomdu.dashboard import build_dashboard, parse_tasks, set_task_done
from dzomdu.pipeline import Pipeline
from dzomdu.server.app import create_app

NOTE = """---
type: meeting
---
# Kickoff

## Action items

- [ ] [[Bob]] Draft the budget 📅 2026-10-14 ([[#^t2|00:00:10]])
- [x] Book the venue (due: next week)
- [ ] Send minutes ([[#^t1|00:00:00]], [[#^t3|00:00:20]])
- _No other actions._

## Transcript

- [ ] this is transcript text, not a task ^t1
"""


def test_parse_tasks():
    tasks = parse_tasks(NOTE)
    assert [(t.text, t.owner, t.due, t.done, t.turn) for t in tasks] == [
        ("Draft the budget", "Bob", "2026-10-14", False, "t2"),
        ("Book the venue", None, "next week", True, None),
        ("Send minutes", None, None, False, "t1"),
    ]
    assert [t.line for t in tasks] == [7, 8, 9]


def test_set_task_done(tmp_path):
    note = tmp_path / "n.md"
    note.write_text(NOTE)
    set_task_done(note, 7, True)
    assert "- [x] [[Bob]] Draft the budget" in note.read_text()
    set_task_done(note, 8, False)
    assert "- [ ] Book the venue" in note.read_text()
    with pytest.raises(ValueError):
        set_task_done(note, 4, True)  # a heading, not a task


def record(rid, day, minutes, project=None, people=("Alice",)):
    return {
        "id": rid,
        "title": rid,
        "date": f"{day}T10:00",
        "duration": minutes * 60,
        "project": project,
        "assignments": {f"S{i}": {"name": p} for i, p in enumerate(people)},
        "turns": [
            {"speaker": f"S{i}", "start": 0, "end": 60 * (i + 1)} for i in range(len(people))
        ],
        "_notes": {"summary": f"About {rid}", "action_items": [{"task": f"Do {rid}"}]},
    }


def test_build_dashboard_periods_and_aggregates():
    records = [
        record("a", "2026-10-06", 30, "Solar", ("Alice", "Bob")),
        record("b", "2026-10-01", 60, "Solar"),
        record("c", "2026-08-20", 20),  # previous 30-day window
        record("d", "2025-01-01", 10),  # older: only in totals
    ]
    d = build_dashboard(records, voices=2, today=date(2026, 10, 7))
    assert d["totals"]["meetings"] == 4 and d["totals"]["hours"] == 2.0
    assert d["period"]["meetings"] == 2 and d["period"]["minutes"] == 90.0
    assert d["period"]["minutes_delta"] == 350.0  # 90 vs 20 minutes
    assert len(d["activity"]) == 30 and d["activity"][-1]["date"] == "2026-10-07"
    assert {a["date"]: a["minutes"] for a in d["activity"]}["2026-10-06"] == 30.0
    assert d["speakers"][0] == {"name": "Alice", "minutes": 4.0, "meetings": 4}
    assert d["projects"][0]["name"] == "Solar" and d["projects"][0]["meetings"] == 2
    # no notes on disk: extracted action items are listed read-only
    assert d["totals"]["open_actions"] == 4 and d["actions"][0]["editable"] is False
    assert d["recent"][0]["summary"] == "About a"


@pytest.fixture
def client(cfg, tmp_path, fake_llm):
    segs, words = make_meeting(tmp_path / "meeting.wav", SCRIPT)
    pipe = Pipeline(
        cfg, asr=TolerantASR({13: words}), diarizer=FakeDiarizer({13: segs}), llm=fake_llm
    )
    with TestClient(create_app(cfg, pipe)) as c:
        with (tmp_path / "meeting.wav").open("rb") as fh:
            sid = c.post(
                "/api/upload",
                files={"file": ("m.wav", fh, "audio/wav")},
                data={"meta": json.dumps({"project": "Solar"})},
            ).json()["id"]
        wait_for(c, sid, {"review"})
        c.post(
            f"/api/sessions/{sid}/review",
            json={"names": {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}},
        )
        wait_for(c, sid, {"done"})
        yield c


def test_dashboard_and_meeting_endpoints(client):
    d = client.get("/api/dashboard").json()
    assert d["totals"]["meetings"] == 1 and d["totals"]["voices"] == 2
    assert d["recent"][0]["summary"] == "The team reviewed the survey budget."
    assert d["recent"][0]["open_actions"] == 2
    task = next(a for a in d["actions"] if a["text"] == "Draft the budget")
    assert task["owner"] == "Bob" and task["due"] == "2026-10-14" and task["editable"]

    mid = d["recent"][0]["id"]
    m = client.get(f"/api/meetings/{mid}").json()
    assert [s["label"] for s in m["speakers"]] == ["Alice", "Bob"]
    assert m["turns"][0]["label"] == "Alice" and m["note"]["html"].startswith("<h1>")
    assert m["decisions"][0]["decision"] == "Proceed with the survey"

    # ticking a task edits the note, and doesn't count as a user edit
    res = client.post(f"/api/meetings/{mid}/tasks/{task['line']}", json={"done": True})
    assert res.status_code == 200
    assert (
        "- [x] [[Bob]] Draft the budget"
        in client.get(f"/api/meetings/{mid}").json()["note"]["markdown"]
    )
    assert client.get("/api/dashboard").json()["totals"]["done_actions"] == 1
    sid = client.post(f"/api/meetings/{mid}/open").json()["id"]
    assert client.post(f"/api/sessions/{sid}/regenerate", json={}).status_code == 200
    assert client.post(f"/api/meetings/{mid}/tasks/0", json={"done": True}).status_code == 409
    assert client.get("/api/meetings/nope").status_code == 404


def test_meeting_audio_supports_seeking(client):
    mid = client.get("/api/meetings").json()["meetings"][0]["id"]
    full = client.get(f"/api/meetings/{mid}/audio")
    assert full.status_code == 200 and full.headers["content-type"] == "audio/wav"
    part = client.get(f"/api/meetings/{mid}/audio", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and len(part.content) == 100
    assert client.get("/api/meetings/nope/audio").status_code == 404


def test_people_and_projects(client):
    voices = {v["name"]: v for v in client.get("/api/speakers").json()}
    assert voices["Alice"]["meetings"] == 1 and voices["Alice"]["minutes"] > 0
    client.post("/api/people", json={"name": "Alice", "role": "Director", "bio": "Leads energy."})
    alice = next(v for v in client.get("/api/speakers").json() if v["name"] == "Alice")
    assert (alice["role"], alice["bio"]) == ("Director", "Leads energy.")
    projects = client.get("/api/projects").json()
    assert projects[0]["name"] == "Solar" and projects[0]["meetings"] == 1


def test_serves_built_dashboard(cfg, fake_llm, tmp_path, monkeypatch):
    web = tmp_path / "out"
    (web / "meetings").mkdir(parents=True)
    (web / "index.html").write_text("<h1>dashboard</h1>")
    (web / "meetings" / "index.html").write_text("<h1>meetings</h1>")
    monkeypatch.setenv("DZOMDU_WEB_DIR", str(web))
    with TestClient(create_app(cfg, Pipeline(cfg, llm=fake_llm))) as c:
        assert c.get("/").text == "<h1>dashboard</h1>"
        assert c.get("/meetings/").text == "<h1>meetings</h1>"
        assert "Start recording" in c.get("/classic/").text
        assert c.get("/api/meetings").status_code == 200  # API still wins


def test_atomic_write_replaces_without_leftovers(tmp_path):
    from dzomdu.vault import atomic_write_text

    target = tmp_path / "meeting.json"
    atomic_write_text(target, "old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["meeting.json"]
