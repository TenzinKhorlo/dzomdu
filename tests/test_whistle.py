import sys
from types import SimpleNamespace

import numpy as np
import pytest

from dzomdu.asr import get_asr_backend
from dzomdu.asr.whistle import REPO, WhistleBackend
from dzomdu.audio import Audio
from dzomdu.config import ASRConfig
from dzomdu.model_library import OPTIONS, ModelLibrary, current_id


class FakeWhistle:
    def __init__(self, weights):
        self.weights = weights
        self.calls = []

    def transcribe(self, samples, language=None, word_timestamps=False):
        self.calls.append((samples.dtype, language, word_timestamps))
        words = [
            {"word": " Hello", "start": 0.1, "end": 0.4, "probability": 0.98765},
            {"word": " ", "start": 0.4, "end": 0.4, "probability": 0.5},
            {"word": " world.", "start": 0.5, "end": 0.45, "probability": 0.9},
        ]
        result = {"text": " Hello world.", "language": "en"}
        return {**result, "words": words} if word_timestamps else result


@pytest.fixture
def fake_needle(monkeypatch, tmp_path):
    weights = tmp_path / "whistle" / "whistle.cact"
    weights.parent.mkdir()
    weights.write_bytes(b"cact")
    fetch = SimpleNamespace(
        WHISTLE="whistle",
        cache_dir=lambda generation: str(tmp_path / str(generation)),
        base_weights=lambda generation: "whistle.cact",
        fetch_weights=lambda generation: pytest.fail("cached weights must not be fetched"),
    )
    agent = SimpleNamespace(fetch=fetch)
    monkeypatch.setitem(sys.modules, "needle", SimpleNamespace(agent=agent))
    monkeypatch.setitem(sys.modules, "needle.agent", agent)
    monkeypatch.setitem(sys.modules, "needle.agent.fetch", fetch)
    monkeypatch.setitem(
        sys.modules,
        "needle.agent.whistle",
        SimpleNamespace(LANGUAGES=("en", "de", "fr"), Whistle=FakeWhistle),
    )
    return weights


def test_whistle_words_keep_timestamps_and_confidence(fake_needle, tmp_path):
    backend = get_asr_backend(ASRConfig(backend="whistle", model=REPO))
    assert isinstance(backend, WhistleBackend) and backend.model_id == REPO
    audio = Audio(np.zeros(16000, np.float64), 16000, tmp_path / "audio.wav")
    words = backend.transcribe(audio)
    assert [(w.text, w.start, w.end, w.confidence) for w in words] == [
        ("Hello", 0.1, 0.4, 0.9877),
        ("world.", 0.5, 0.5, 0.9),
    ]
    assert backend._model.weights == fake_needle
    assert backend._model.calls == [(np.float32, "en", True)]
    preview = backend.transcribe_preview(audio)
    assert [(w.text, w.start, w.end) for w in preview] == [("Hello world.", 0.0, 1.0)]
    assert backend._model.calls[-1] == (np.float32, "en", False)


def test_whistle_language_and_custom_weights(fake_needle, tmp_path):
    cfg = ASRConfig(backend="whistle", model="/models/tuned.cact", language="auto")
    tuned = WhistleBackend(cfg)
    assert tuned.model_id == "/models/tuned.cact"
    tuned.transcribe(Audio(np.zeros(160, np.float32), 16000, tmp_path / "a.wav"))
    assert tuned._model.weights == "/models/tuned.cact"
    assert tuned._model.calls == [(np.float32, None, True)]
    with pytest.raises(RuntimeError, match="does not support language 'ne'"):
        WhistleBackend(ASRConfig(backend="whistle", language="ne"))._load()
    with pytest.raises(ValueError, match="16000 Hz"):
        tuned.transcribe(Audio(np.zeros(441, np.float32), 44100, tmp_path / "a.wav"))


def test_whistle_library_entry_downloads_through_needle(cfg, tmp_path, monkeypatch):
    option = OPTIONS["whistle"]
    assert option.backend == "whistle" and option.languages == ("en", "auto")
    cfg.asr = ASRConfig(backend="whistle")
    assert current_id(cfg, "asr") == "whistle"
    library = ModelLibrary(cfg)
    try:
        monkeypatch.setattr("dzomdu.model_library.is_installed", lambda module: False)
        with pytest.raises(ValueError, match="whistle runtime"):
            library.queue(["whistle"])
        assert not library.downloaded("whistle")
        files = [tmp_path / "whistle.cact", tmp_path / "libneedle.dylib"]
        for f in files:
            f.write_bytes(b"x")
        monkeypatch.setattr("dzomdu.asr.whistle.download", lambda: files)
        library.jobs["whistle"] = {}
        library._download("whistle")
        assert library.jobs["whistle"]["state"] == "downloaded"
        assert library.downloaded("whistle")
    finally:
        library.shutdown()
