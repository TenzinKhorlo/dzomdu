import itertools

import httpx
import numpy as np
import pytest
from conftest import FakeASR, FakeDiarizer, make_meeting, ollama_transport

from dzomdu import asr as asr_mod
from dzomdu import diarize as diarize_mod
from dzomdu.bench import runner
from dzomdu.bench.labels import read_audacity, read_rttm, write_rttm
from dzomdu.bench.metrics import der, edit_distance, verification, wer
from dzomdu.models import SpeakerSegment


def naive_distance(a, b):
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i, j in itertools.product(range(1, len(a) + 1), range(1, len(b) + 1)):
        d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    return d[-1][-1]


def test_edit_distance_matches_naive():
    rng = np.random.default_rng(0)
    for _ in range(50):
        a = list(rng.choice(list("abcd"), rng.integers(0, 12)))
        b = list(rng.choice(list("abcd"), rng.integers(0, 12)))
        assert edit_distance(a, b) == naive_distance(a, b)


def test_wer():
    score, errors, n = wer("The cat sat on the mat.", "the cat sat on a mat")
    assert (errors, n) == (1, 6) and score == pytest.approx(1 / 6)
    assert wer("", "")[0] == 0.0


def S(a, b, s):
    return SpeakerSegment(a, b, s)


def test_der():
    ref = [S(0, 10, "alice"), S(10, 20, "bob")]
    assert der(ref, [S(0, 10, "X"), S(10, 20, "Y")]).der == pytest.approx(0, abs=1e-6)
    r = der(ref, [S(0, 20, "X")], collar=0)
    assert r.confusion == pytest.approx(10) and r.der == pytest.approx(0.5)
    r = der(ref, [S(0, 10, "X")], collar=0)
    assert r.missed == pytest.approx(10) and r.mapping == {"X": "alice"}
    r = der(ref, [S(0, 10, "X"), S(10, 20, "Y"), S(30, 35, "Y")], collar=0)
    assert r.false_alarm == pytest.approx(5)


def test_verification():
    v = verification(np.array([0.8, 0.85, 0.9, 0.7]), np.array([0.1, 0.2, 0.3, 0.75]))
    assert v.eer == pytest.approx(0.25)
    assert v.threshold_far_1pct > 0.75


def test_label_readers(tmp_path):
    aud = tmp_path / "labels.txt"
    aud.write_text("0.0\t2.5\tKarma Wangmo\n\\\t100\t200\n3.0\t4.0\tBob\n")
    segs = read_audacity(aud)
    assert [(s.start, s.end, s.speaker) for s in segs] == [(0, 2.5, "Karma Wangmo"), (3, 4, "Bob")]
    rttm = tmp_path / "x.rttm"
    write_rttm(rttm, "m1", segs)
    assert [s.speaker for s in read_rttm(rttm)] == ["Karma_Wangmo", "Bob"]


@pytest.fixture
def bench_setup(tmp_path, cfg, monkeypatch):
    scripts = {
        "m1": [
            ("Alice", 0, 4, "hello there team"),
            ("Bob", 4.5, 9, "budget is fine"),
            ("Alice", 9.5, 13, "great work"),
        ],
        "m2": [
            ("Bob", 0, 3, "morning all"),
            ("Alice", 3.5, 8, "let us begin now"),
            ("Bob", 8.5, 11, "agreed"),
        ],
    }
    seg_by_dur, words_by_dur = {}, {}
    lines = ["meetings:"]
    for mid, script in scripts.items():
        segs, words = make_meeting(tmp_path / f"{mid}.wav", script)
        dur = round(max(e for _, _, e, _ in script) + 0.4)
        seg_by_dur[dur], words_by_dur[dur] = segs, words
        (tmp_path / f"{mid}.txt").write_text(" ".join(t for *_, t in script))
        (tmp_path / f"{mid}.labels.txt").write_text(
            "".join(f"{a}\t{b}\t{p}\n" for p, a, b, _ in script)
        )
        lines += [
            f"  - id: {mid}",
            f"    audio: {mid}.wav",
            f"    reference_text: {mid}.txt",
            f"    reference_speakers: {mid}.labels.txt",
            "    num_speakers: 2",
            "    tags: {mic: laptop}",
        ]
    lines += ["asr_backends: [fake]", "llm_models: [model-a, model-b]"]
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("\n".join(lines) + "\n")

    monkeypatch.setitem(asr_mod.BACKENDS, "fake", lambda c: FakeASR(words_by_dur))
    monkeypatch.setitem(diarize_mod.BACKENDS, "fake", lambda c: FakeDiarizer(seg_by_dur))
    cfg.asr.backend = "fake"
    cfg.diarization.backend = "fake"
    cfg.vault.mkdir(parents=True)
    return cfg, runner.load_manifest(manifest), tmp_path / "out"


def test_bench_asr_and_diarization(bench_setup):
    cfg, manifest, out = bench_setup
    report = runner.bench_asr(cfg, manifest, out, lambda m: None)
    assert "| fake | 0.0% |" in report
    assert (
        out / "asr" / "fake" / "m1.txt"
    ).read_text() == "hello there team budget is fine great work"
    report = runner.bench_diarization(cfg, manifest, out, lambda m: None)
    assert "Overall DER (speaker count not given): **0.0%**" in report
    assert "m1 (n given)" in report


def test_bench_speaker_id(bench_setup):
    cfg, manifest, out = bench_setup
    report = runner.bench_speaker_id(cfg, manifest, out, lambda m: None)
    assert "Equal error rate: **0.0%**" in report
    assert "**2/2** speakers correct" not in report  # 2 meetings x 2 people = 4
    assert "**4/4** speakers correct" in report
    assert "accept_threshold =" in report


def test_bench_llm_blind(bench_setup, monkeypatch):
    cfg, manifest, out = bench_setup
    monkeypatch.setattr(runner, "LLMClient", _mock_client)
    report = runner.bench_llm(cfg, manifest, out, lambda m: None)
    assert "blind comparison" in report
    assert sorted(p.name for p in (out / "llm" / "m1").iterdir()) == ["A.md", "B.md"]
    key = (out / "llm" / "KEY-open-after-judging.json").read_text()
    assert "model-a" in key and "model-b" in key


def _mock_client(llm_cfg):
    from dzomdu.llm.client import LLMClient

    return LLMClient(llm_cfg, http=httpx.Client(transport=ollama_transport()))
