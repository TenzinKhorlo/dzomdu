from concurrent.futures import ThreadPoolExecutor

import numpy as np
from conftest import PITCH, FakeDiarizer

from dzomdu.asr import ASRBackend
from dzomdu.audio import SAMPLE_RATE
from dzomdu.live import LiveSpeakerTracker, LiveTranscriber, Segmenter
from dzomdu.models import Word
from dzomdu.speakers.matching import LibraryEntry

SR = SAMPLE_RATE


def tone(seconds, freq=220.0, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def quiet(seconds, seed=0):
    return np.random.default_rng(seed).normal(0, 0.002, int(seconds * SR)).astype(np.float32)


def feed_in_chunks(seg, audio):
    rng = np.random.default_rng(1)
    out, i = [], 0
    while i < len(audio):
        n = int(rng.integers(300, 6000))
        out += seg.feed(audio[i : i + n])
        i += n
    return out + seg.flush()


def test_segmenter_splits_on_pauses():
    audio = np.concatenate([quiet(1), tone(2), quiet(1), tone(1.5), quiet(1)])
    utts = feed_in_chunks(Segmenter(), audio)
    assert len(utts) == 2
    assert abs(utts[0].start - 0.8) < 0.15  # includes ~0.2 s of pre-roll
    assert 2.0 <= utts[0].end - utts[0].start <= 3.0
    assert abs(utts[1].start - 3.8) < 0.15


def test_segmenter_caps_long_speech_and_ignores_clicks():
    utts = feed_in_chunks(Segmenter(max_utterance=12.0), np.concatenate([tone(30), quiet(1)]))
    assert len(utts) == 3 and all(u.end - u.start <= 12.1 for u in utts)
    clicks = np.concatenate([quiet(1), tone(0.1), quiet(1), tone(0.15), quiet(1)])
    assert feed_in_chunks(Segmenter(), clicks) == []


def unit(*xs):
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_tracker_names_known_voices_and_clusters_the_rest():
    tracker = LiveSpeakerTracker([LibraryEntry(1, "Alice", np.stack([unit(1, 0, 0)]))], 0.6)
    assert tracker.label(unit(1, 0.1, 0)) == "Alice"
    assert tracker.label(unit(0, 1, 0)) == "Speaker 1"
    assert tracker.label(unit(0, 0, 1)) == "Speaker 2"
    assert tracker.label(unit(0, 1, 0.2)) == "Speaker 1"
    assert tracker.label(None) is None


class EchoASR(ASRBackend):
    """Says which pitch it heard, so the test can check ordering."""

    name = "echo"

    @property
    def model_id(self):
        return "echo"

    def transcribe(self, audio):
        spectrum = np.abs(np.fft.rfft(audio.samples))
        freq = np.argmax(spectrum) * audio.sample_rate / len(audio.samples)
        name = min(PITCH, key=lambda k: abs(PITCH[k] - freq))
        return [Word(f"{name}", 0.0, 0.5), Word("speaking.", 0.5, 1.0)]


def test_live_transcriber_end_to_end(tmp_path):
    segments, errors = [], []
    with ThreadPoolExecutor(max_workers=1) as pool:
        live = LiveTranscriber(
            EchoASR(),
            FakeDiarizer(),
            LiveSpeakerTracker([], 0.6),
            tmp_path,
            pool.submit,
            segments.append,
            errors.append,
        )
        audio = np.concatenate(
            [
                quiet(0.5),
                tone(2, PITCH["Alice"]),
                quiet(1),
                tone(2, PITCH["Bob"]),
                quiet(1),
                tone(2, PITCH["Alice"]),
                quiet(0.3),
            ]
        )
        for i in range(0, len(audio), 4000):
            live.feed(audio[i : i + 4000])
        live.finish()
    assert errors == []
    latest = {s["id"]: s for s in segments}  # each id is re-sent as it improves
    assert [(s["text"], s["speaker"], s["partial"]) for s in latest.values()] == [
        ("Alice speaking.", "Speaker 1", False),
        ("Bob speaking.", "Speaker 2", False),
        ("Alice speaking.", "Speaker 1", False),
    ]
    first = [s for s in segments if s["id"] == 1]
    # words appear while the person is still talking, before the pause closes the utterance
    assert first[0]["partial"] and first[0]["end"] < first[-1]["end"]
    # the final text is sent before the (slower) voice match labels it
    finals = [s for s in first if not s["partial"]]
    assert [s["speaker"] for s in finals] == [None, "Speaker 1"]
    assert list(tmp_path.iterdir()) == []  # temporary chunk files are removed


def test_interim_guess_does_not_create_speakers():
    tracker = LiveSpeakerTracker([], 0.6)
    assert tracker.label(unit(1, 0, 0), learn=False) is None
    assert tracker.label(unit(1, 0, 0)) == "Speaker 1"
    assert tracker.label(unit(1, 0.1, 0), learn=False) == "Speaker 1"
    assert tracker.label(unit(0, 1, 0)) == "Speaker 2"  # the guess didn't add a voice
