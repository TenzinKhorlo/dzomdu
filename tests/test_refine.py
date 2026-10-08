"""Pass 2 must not lose people or words that the live preview had.

Two failure modes seen in real meetings:
- the diarization model put two similar voices into one speaker, so the meeting showed one
  person where two had spoken;
- the speech engine returned nothing for the last sentence of the recording.
"""

from __future__ import annotations

import numpy as np
from conftest import FakeASR, FakeDiarizer, make_meeting

from dzomdu.asr import ASRBackend
from dzomdu.audio import read_wav
from dzomdu.models import SpeakerSegment, Word
from dzomdu.pipeline import Pipeline
from dzomdu.recover import missing_spans
from dzomdu.speakers.refine import refine_clusters
from dzomdu.vault import Vault

CONVERSATION = [
    ("Alice", 0.0, 5.0, "Let's start with the survey plan for next month."),
    ("Bob", 5.5, 10.5, "I checked the costs and transport is the biggest item."),
    ("Alice", 11.0, 15.0, "Then we should ask the district office for permits."),
    ("Bob", 15.5, 20.0, "I can draft the request before Friday."),
]


def _merged(segments: list[SpeakerSegment]) -> list[SpeakerSegment]:
    """What a diarizer does when it can't tell two voices apart: one cluster."""
    return [SpeakerSegment(s.start, s.end, "SPEAKER_00") for s in segments]


def _pipeline(cfg, tmp_path, fake_llm, asr, diarizer):
    vault = Vault(cfg.vault)
    vault.init()
    return Pipeline(cfg, asr=asr, diarizer=diarizer, llm=fake_llm, vault=vault)


def test_merged_cluster_is_split_into_two_people(cfg, tmp_path, fake_llm):
    segs, words = make_meeting(tmp_path / "m.wav", CONVERSATION, seed=3)
    pipe = _pipeline(
        cfg, tmp_path, fake_llm, FakeASR({20: words}), FakeDiarizer({20: _merged(segs)})
    )
    record = pipe.analyze(tmp_path / "m.wav").record
    assert [t.speaker for t in record.turns] == ["SPEAKER_00", "SPEAKER_00_2"] * 2
    assert len(record.assignments) == 2


def test_split_uses_known_voices(cfg, tmp_path, fake_llm):
    """Once both people are known, the split clusters are recognised by name."""
    segs, words = make_meeting(tmp_path / "m.wav", CONVERSATION, seed=3)
    diarizer = FakeDiarizer({20: segs})
    pipe = _pipeline(cfg, tmp_path, fake_llm, FakeASR({20: words}), diarizer)
    first = pipe.analyze(tmp_path / "m.wav")
    pipe.apply_review(first, {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    pipe.learn(first)

    diarizer.segments_by_duration[20] = _merged(segs)
    record = pipe.analyze(tmp_path / "m.wav").record
    names = [record.name_for(t.speaker) for t in record.turns]
    assert names == ["Alice", "Bob", "Alice", "Bob"]


def test_two_voices_inside_one_segment_are_separated(cfg, tmp_path):
    """A merged cluster can also glue back-to-back turns into one long segment."""
    _segs, _ = make_meeting(tmp_path / "m.wav", CONVERSATION[:2], seed=4)
    samples, sr = read_wav(tmp_path / "m.wav")
    from dzomdu.audio import Audio

    audio = Audio(samples, sr, tmp_path / "m.wav")
    out = refine_clusters(
        audio, [SpeakerSegment(0.0, 10.5, "SPEAKER_00")], FakeDiarizer(), [], window=2.0
    )
    speakers = [s.speaker for s in out]
    assert speakers[0] == "SPEAKER_00" and speakers[-1] == "SPEAKER_00_2"
    boundary = next(s.start for s in out if s.speaker == "SPEAKER_00_2")
    assert 4.0 <= boundary <= 6.5


def test_one_person_is_not_split(cfg, tmp_path):
    script = [
        ("Alice", 0.0, 5.0, "a b c d e"),
        ("Alice", 5.5, 10.0, "f g h i j"),
        ("Alice", 10.5, 15.0, "k l m n o"),
    ]
    segs, _ = make_meeting(tmp_path / "m.wav", script, seed=5)
    samples, sr = read_wav(tmp_path / "m.wav")
    from dzomdu.audio import Audio

    out = refine_clusters(Audio(samples, sr, tmp_path / "m.wav"), segs, FakeDiarizer(), [])
    assert out == segs


class DropsLastSentence(ASRBackend):
    """Behaves like a speech engine that loses the final sentence of a file, but hears it
    fine when that stretch is transcribed on its own."""

    name = "drops-last"

    def __init__(self, words: list[Word], cut: float):
        self.words, self.cut, self.calls = words, cut, 0

    @property
    def model_id(self) -> str:
        return "drops-last"

    def transcribe(self, audio):
        self.calls += 1
        if audio.duration > 10:
            return [w for w in self.words if w.start < self.cut]
        # word times relative to the clip, starting where the speech starts
        # (the speech after the last pause: a clip may begin with the previous speaker's tail)
        frame = audio.sample_rate // 100
        loud = [
            float(np.abs(audio.samples[i : i + frame]).max()) > 0.05
            for i in range(0, len(audio.samples) - frame, frame)
        ]
        starts = [i for i in range(20, len(loud)) if loud[i] and not any(loud[i - 20 : i])]
        onset = (starts[-1] if starts else 0) / 100
        return [
            Word("Thank", onset, onset + 0.5),
            Word("you", onset + 0.6, onset + 1.0),
            Word("all.", onset + 1.1, onset + 1.8),
        ]


def test_lost_last_sentence_is_recovered(cfg, tmp_path, fake_llm):
    script = CONVERSATION + [("Carol", 20.5, 22.5, "Thank you all.")]
    segs, words = make_meeting(tmp_path / "m.wav", script, seed=6)
    asr = DropsLastSentence(words, cut=20.4)
    pipe = _pipeline(cfg, tmp_path, fake_llm, asr, FakeDiarizer({23: segs}))
    record = pipe.analyze(tmp_path / "m.wav").record
    last = record.turns[-1]
    assert last.text == "Thank you all."
    assert 20.0 <= last.start <= 21.5
    assert last.speaker == "SPEAKER_02"  # Carol's own cluster, not folded into Bob's


def test_missing_spans_only_reports_real_gaps():
    words = [Word("a", 0.0, 0.5), Word("b", 0.6, 1.0), Word("c", 3.2, 3.6)]
    assert missing_spans(words, [(0.0, 3.6)]) == [(1.0, 3.2)]
    assert missing_spans(words, [(0.0, 1.2)]) == []  # a short pause is not a gap
