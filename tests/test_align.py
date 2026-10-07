from types import SimpleNamespace

from dzomdu.align import align, assign_speakers, build_turns, join_words, smooth_labels
from dzomdu.asr.parakeet import tokens_to_words
from dzomdu.models import SpeakerSegment, Word


def W(text, start, end):
    return Word(text, start, end)


def test_assign_by_overlap_and_nearest_gap():
    segs = [SpeakerSegment(0, 2, "A"), SpeakerSegment(2.5, 5, "B")]
    words = [
        W("hi", 0.1, 0.5),
        W("there", 1.8, 2.3),  # mostly in A
        W("gap", 2.3, 2.45),  # in the gap: nearest is B (0.05 s away)
        W("yes", 3, 3.4),
        W("far", 8, 8.5),  # nothing within 1 s
    ]
    assert assign_speakers(words, segs) == ["A", "A", "B", "B", None]


def test_smoothing_removes_short_islands_and_fills_gaps():
    words = [W(str(i), i * 0.3, i * 0.3 + 0.25) for i in range(7)]
    labels = ["A", "A", "B", "A", "A", None, "C"]
    assert smooth_labels(words, labels) == ["A", "A", "A", "A", "A", "A", "C"]
    # a long run of B is a real turn and is kept
    words = [W(str(i), i * 1.0, i * 1.0 + 0.9) for i in range(5)]
    assert smooth_labels(words, ["A", "B", "B", "A", "A"]) == ["A", "B", "B", "A", "A"]
    assert smooth_labels(words[:2], [None, "B"]) == ["B", "B"]


def test_build_turns_splits_on_speaker_and_pause():
    words = [W("Hello", 0, 0.4), W("there.", 0.5, 0.9), W("Hi", 1.2, 1.4), W("again", 9, 9.3)]
    turns = build_turns(words, ["A", "A", "B", "B"])
    assert [(t.id, t.speaker, t.text) for t in turns] == [
        ("t1", "A", "Hello there."),
        ("t2", "B", "Hi"),
        ("t3", "B", "again"),
    ]


def test_join_words_fixes_punctuation_spacing():
    assert join_words(["Hello", ",", "world", "!", "(", "yes", ")"]) == "Hello, world! (yes)"


def test_align_end_to_end():
    segs = [SpeakerSegment(0, 1, "A"), SpeakerSegment(1, 2, "B")]
    words = [W("one", 0.1, 0.4), W("two", 0.5, 0.9), W("three", 1.1, 1.5)]
    turns = align(words, segs)
    assert [(t.speaker, t.text) for t in turns] == [("A", "one two"), ("B", "three")]


def test_parakeet_tokens_merge_into_words():
    def tok(text, start, dur, conf=1.0):
        return SimpleNamespace(
            text=text, start=start, duration=dur, end=start + dur, confidence=conf
        )

    tokens = [
        tok(" Hel", 0.0, 0.2, 0.9),
        tok("lo", 0.2, 0.1),
        tok(",", 0.3, 0.05),
        tok(" world", 0.5, 0.3, 0.8),
        tok(" ", 0.8, 0.0),
    ]
    words = tokens_to_words(tokens)
    assert [(w.text, w.start, round(w.end, 2), w.confidence) for w in words] == [
        ("Hello,", 0.0, 0.35, 0.9),
        ("world", 0.5, 0.8, 0.8),
    ]
