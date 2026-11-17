import numpy as np
import pytest

from dzomdu.audio import Audio
from dzomdu.config import DiarizationConfig
from dzomdu.diarize import get_diarizer
from dzomdu.diarize import who as who_module
from dzomdu.diarize.who import (
    REPO,
    Turn,
    WhoDiarizer,
    average_linkage,
    column_mask,
    exclusive,
    join_touching,
    number_by_appearance,
    voice_windows,
)
from dzomdu.model_library import OPTIONS, ModelLibrary, current_id


def unit(*rows):
    v = np.array(rows, np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_average_linkage_merges_similar_voices_in_order_of_appearance():
    voices = unit([1, 0, 0], [0, 1, 0], [0.99, 0.05, 0], [0, 0.98, 0.1], [0, 0, 1])
    assert average_linkage(voices, 0.65) == [0, 1, 0, 1, 2]
    assert average_linkage(voices[:1], 0.65) == [0]
    assert average_linkage(voices[:0], 0.65) == []


def test_turns_join_when_touching_and_number_by_first_appearance():
    turns = [Turn(5, 6, 9), Turn(0, 2, 4), Turn(2, 3, 4), Turn(2.5, 4, 9)]
    joined = join_touching(turns)
    assert Turn(0, 3, 4) in joined and Turn(2.5, 6, 9) not in joined
    assert [(t.start, t.label) for t in number_by_appearance(turns)] == [
        (0, 0),
        (2, 0),
        (2.5, 1),
        (5, 1),
    ]


def test_exclusive_gives_overlap_to_the_speaker_already_talking():
    turns = [Turn(0, 10, 0), Turn(4, 5, 1), Turn(8, 14, 1)]
    assert exclusive(turns) == [Turn(0, 10, 0), Turn(10, 14, 1)]
    assert exclusive([Turn(0, 1, 0), Turn(2, 3, 0)]) == [Turn(0, 1, 0), Turn(2, 3, 0)]


def test_voice_windows_cover_every_column_once():
    per, margin, width = 8, 128, 3256
    for frames in (800, 3256, 3257, 9000, 40000):
        covered = []
        for start, low, high, place in voice_windows(frames // per * per, width, margin, per):
            assert 0 <= start and low >= 0
            covered += list(range(place, place + high - low))
        assert covered == list(range(frames // per * per // per))


def test_column_mask_needs_half_the_frames_solo():
    solo = np.array([1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0], np.float32)
    assert column_mask(solo, 0, 2, 8).tolist() == [True, False]
    # a piece that starts mid-recording only marks the columns it covers
    assert column_mask(solo[8:], 8, 3, 8).tolist() == [False, False, False]
    assert column_mask(solo[:8], 8, 3, 8).tolist() == [False, True, False]
    assert column_mask(np.ones(8, np.float32), 8, 3, 8).tolist() == [False, True, False]


class FakeModel:
    def __init__(self, turns):
        self.turns = turns
        self.seen = []

    def diarize(self, samples):
        self.seen.append(samples.dtype)
        return self.turns, len(samples) / 16000


def audio(seconds, tmp_path):
    return Audio(np.zeros(int(seconds * 16000), np.float32), 16000, tmp_path / "a.wav")


def test_diarizer_returns_exclusive_labelled_segments(tmp_path):
    diarizer = get_diarizer(DiarizationConfig(backend="who", model=REPO))
    assert isinstance(diarizer, WhoDiarizer)
    diarizer._model = FakeModel([Turn(0, 6, 0), Turn(5, 9, 1), Turn(9, 30, 2)])
    segments = diarizer.diarize(audio(10, tmp_path))
    assert [(s.start, s.end, s.speaker) for s in segments] == [
        (0, 6, "SPEAKER_00"),
        (6, 9, "SPEAKER_01"),
        (9, 10, "SPEAKER_02"),
    ]
    assert diarizer._model.seen == [np.float32]


def test_speaker_limit_drops_the_least_present_speakers(tmp_path):
    diarizer = WhoDiarizer(DiarizationConfig(backend="who"))
    diarizer._model = FakeModel([Turn(0, 1, 0), Turn(1, 9, 1), Turn(9, 10, 2)])
    for kwargs in ({"max_speakers": 1}, {"num_speakers": 1}):
        segments = diarizer.diarize(audio(10, tmp_path), **kwargs)
        assert [(s.start, s.end, s.speaker) for s in segments] == [(1, 9, "SPEAKER_01")]
    # Who cannot enforce a minimum, so it is ignored rather than inventing speakers
    assert len(diarizer.diarize(audio(10, tmp_path), min_speakers=5)) == 3


def test_who_input_and_voiceprints(tmp_path, monkeypatch):
    diarizer = WhoDiarizer(DiarizationConfig(backend="who"))
    with pytest.raises(ValueError, match="16000 Hz"):
        diarizer.diarize(Audio(np.zeros(441, np.float32), 44100, tmp_path / "a.wav"))
    assert diarizer.diarize(Audio(np.zeros(0, np.float32), 16000, tmp_path / "a.wav")) == []
    # Voiceprints stay in Pyannote's embedding space, so existing speaker profiles still match.
    assert diarizer.embedding_id == diarizer.voice.embedding_id
    assert diarizer.model_id.startswith("who:") and diarizer.model_id != diarizer.embedding_id
    monkeypatch.setattr(diarizer.voice, "embed", lambda w, sr: np.ones((len(w), 3), np.float32))
    assert diarizer.embed([np.zeros(10, np.float32)], 16000).shape == (1, 3)


def test_who_library_entry_downloads_pinned_files(cfg, tmp_path, monkeypatch):
    option = OPTIONS["who"]
    assert option.kind == "diarization" and option.backend == "who"
    assert option.dependencies == ("pyannote",) and option.speaker_limit is None
    cfg.diarization = DiarizationConfig(backend="who", model=REPO)
    assert current_id(cfg, "diarization") == "who"
    library = ModelLibrary(cfg)
    try:
        monkeypatch.setattr("dzomdu.model_library.is_installed", lambda module: False)
        with pytest.raises(ValueError, match="who runtime"):
            library.queue(["who"])
        assert not library.downloaded("who")
        files = [tmp_path / "encoder_6000.onnx", tmp_path / "who_meta.json"]
        for f in files:
            f.write_bytes(b"x")
        monkeypatch.setattr(who_module, "download", lambda: files)
        library.jobs["who"] = {}
        library._download("who")
        assert library.jobs["who"]["state"] == "downloaded"
        assert library.downloaded("who")
    finally:
        library.shutdown()


def test_who_files_are_the_int8_onnx_graphs():
    names = who_module._file_names()
    assert len(names) == 9 and all(n.startswith("onnx-int8/") for n in names)
    assert {n.split("/")[1] for n in names} >= {"voice_3256.onnx", "who_meta.json", "who_embed.f16"}


@pytest.fixture(scope="module")
def real_model():
    cached = who_module._cached()
    if cached is None:
        pytest.skip("Who weights are not downloaded")
    return who_module.WhoModel(cached)


def test_too_short_audio_yields_no_segments(tmp_path):
    diarizer = WhoDiarizer(DiarizationConfig(backend="who"))
    diarizer._model = FakeModel([Turn(0, 1, 0)])
    for samples in (0, 1, 399):
        assert diarizer.diarize(audio(samples / 16000, tmp_path)) == []
    assert diarizer._model.seen == []


@pytest.mark.parametrize("seconds", [0.02, 5, 360])
def test_silence_has_no_speakers_even_across_pieces(real_model, seconds):
    turns, duration = real_model.diarize(np.zeros(int(seconds * 16000), np.float32))
    assert turns == [] and duration == pytest.approx(seconds)


def test_long_recording_without_a_voice_keeps_each_piece_apart(real_model, monkeypatch):
    # Each of the two pieces decides one query, but with 0.2 s of solo speech there is no
    # voice to learn: the join must skip the voice graph and keep the pieces' speakers apart.
    queries = real_model.meta["model"]["queries"]

    def logits(audio, piece, means):
        frames = piece[1] - piece[0]
        presence = np.zeros(queries)
        presence[0] = 1
        masks = np.zeros((queries, frames))
        masks[0, :20] = 1
        return presence, masks

    monkeypatch.setattr(real_model, "_logits", logits)
    monkeypatch.setattr(real_model, "_session", lambda name: pytest.fail("voice graph ran"))
    turns, _ = real_model.diarize(np.zeros(16000 * 400, np.float32))
    assert len(turns) == 2 and {t.label for t in turns} == {0, 1}
