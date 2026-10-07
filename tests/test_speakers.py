import numpy as np
import pytest

from dzomdu.speakers.matching import ClusterVoice, LibraryEntry, match_clusters, similarity
from dzomdu.speakers.store import VoiceprintStore


def unit(*xs):
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def store(tmp_path):
    s = VoiceprintStore(tmp_path / "db.sqlite", tmp_path / "clips")
    yield s
    s.close()


def test_get_or_create_is_case_insensitive(store):
    a = store.get_or_create("Karma Wangmo")
    assert store.get_or_create("karma wangmo").id == a.id
    assert store.get_or_create("Karma Wangmo", consent=True).consent
    with pytest.raises(ValueError):
        store.get_or_create("  ")


def test_embeddings_are_separated_by_model(store):
    s = store.get_or_create("A")
    store.add_embedding(s.id, "m1", unit(1, 0, 0))
    store.add_embedding(s.id, "m2", unit(0, 1, 0))
    assert store.embeddings("m1")[s.id].shape == (1, 3)
    assert store.embeddings("m1", []) == {}
    assert [x.samples for x in store.list(model="m2")] == [1]
    with pytest.raises(ValueError):
        store.add_embedding(s.id, "m1", np.array([np.nan, 1, 0]))


def test_prune_keeps_diverse_samples_and_newest(store, tmp_path):
    s = store.get_or_create("A")
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"x")
    store.add_embedding(s.id, "m", unit(1, 0, 0), clip_path=clip)
    store.add_embedding(s.id, "m", unit(1, 0.01, 0), max_per_speaker=3)
    store.add_embedding(s.id, "m", unit(0, 1, 0), max_per_speaker=3)
    store.add_embedding(s.id, "m", unit(0, 0, 1), max_per_speaker=3)
    kept = store.embeddings("m")[s.id]
    assert len(kept) == 3
    # one of the two near-duplicates was dropped; the distinct and newest ones remain
    assert np.isclose(kept @ unit(0, 1, 0), 1).any() and np.isclose(kept @ unit(0, 0, 1), 1).any()


def test_rename_and_forget(store, tmp_path):
    s = store.get_or_create("Old")
    clip = store.clip_path_for(s.id, "x")
    clip.write_bytes(b"x")
    store.add_embedding(s.id, "m", unit(1, 0), clip_path=clip)
    store.get_or_create("Other")
    with pytest.raises(ValueError):
        store.rename("Old", "other")
    store.rename("Old", "New")
    assert store.get("New").id == s.id
    assert store.forget("New")
    assert store.get("New") is None
    assert store.embeddings("m") == {}
    assert not clip.exists()
    assert not store.forget("Nobody")


def voice(name, vec):
    return ClusterVoice(name, unit(*vec), np.zeros((0, 2)), (0.0, 1.0), 10.0)


def test_similarity_top_k():
    refs = np.stack([unit(1, 0), unit(0, 1), unit(1, 1)])
    assert similarity(unit(1, 0), refs, top_k=1) == pytest.approx(1.0)
    assert similarity(unit(1, 0), refs, top_k=2) == pytest.approx((1 + 0.7071) / 2, abs=1e-3)


def test_match_is_one_to_one_with_thresholds():
    voices = {
        "S0": voice("S0", (1, 0, 0)),
        "S1": voice("S1", (0.95, 0.3, 0)),  # close to A too, but A is taken by S0
        "S2": voice("S2", (0, 0.8, 0.6)),  # moderately close to B -> suggestion
        "S3": voice("S3", (0, 0, 1)),
    }
    library = [
        LibraryEntry(1, "A", np.stack([unit(1, 0, 0)])),
        LibraryEntry(2, "B", np.stack([unit(0, 1, 0)])),
    ]
    out = match_clusters(voices, library, accept_threshold=0.9, suggest_threshold=0.5)
    assert (out["S0"].name, out["S0"].status) == ("A", "auto")
    assert out["S1"].status == "unknown" and out["S1"].unknown_label == "Unknown speaker 1"
    assert out["S2"].status == "suggested" and out["S2"].suggestion == "B"
    assert out["S2"].display_name == "B?" and out["S2"].unknown_label == "Unknown speaker 2"
    assert out["S3"].display_name == "Unknown speaker 3"
    assert out["S1"].score == pytest.approx(0.9535, abs=1e-3)  # best score kept for review
    assert list(out) == ["S0", "S1", "S2", "S3"]  # order of first speech, not of matching


def test_match_handles_missing_embeddings():
    voices = {"S0": ClusterVoice("S0", None, np.zeros((0, 2)), None)}
    out = match_clusters(voices, [], 0.6, 0.45)
    assert out["S0"].status == "unknown" and out["S0"].score is None
