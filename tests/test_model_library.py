import sys
from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dzomdu.asr.alternatives import MLXAudioBackend
from dzomdu.audio import Audio, write_wav
from dzomdu.config import ASRConfig, load_config
from dzomdu.diarize.nemotron import NemotronDiarizer
from dzomdu.model_library import OPTIONS, ModelLibrary, current_id
from dzomdu.pipeline import Pipeline
from dzomdu.server.app import create_app
from dzomdu.server.sessions import SessionMeta


def test_catalog_keeps_current_defaults_and_download_does_not_change_them(cfg, tmp_path):
    library = ModelLibrary(cfg)
    try:
        assert current_id(cfg, "asr") == "parakeet"
        assert current_id(cfg, "diarization") == "pyannote"
        assert OPTIONS["pyannote"].speaker_limit is None
        assert OPTIONS["nemotron-diarization"].speaker_limit == 8
        with pytest.raises(ValueError, match="Unknown model"):
            library.queue(["arbitrary/repository"])
        weights = tmp_path / "model.safetensors"
        weights.write_bytes(b"weights")
        library.receipts["qwen-small"] = {"files": [(str(weights), 7)]}
        assert library.downloaded("qwen-small")
        weights.unlink()
        assert not library.downloaded("qwen-small")
        assert cfg.asr.backend == "parakeet" and cfg.asr.model is None
    finally:
        library.shutdown()


def test_model_settings_persist_block_active_meetings_and_reject_wrong_language(
    cfg, tmp_path, fake_llm, monkeypatch
):
    monkeypatch.setattr("dzomdu.server.app.compatible", lambda m: None)
    monkeypatch.setattr(ModelLibrary, "ready", lambda self, key: True)
    config = tmp_path / "config.toml"
    pipe = Pipeline(cfg, llm=fake_llm)
    with TestClient(create_app(cfg, pipe, config_path=config)) as client:
        defaults = {
            "asr_id": "qwen-large",
            "diarization_id": "pyannote",
            "language": "en",
            "max_speakers": 32,
        }
        res = client.put("/api/settings/models", json=defaults)
        assert res.status_code == 200, res.text
        saved = load_config(config)
        assert saved.asr.model == OPTIONS["qwen-large"].repo
        assert saved.diarization.max_speakers == 32
        assert pipe._asr is None and pipe._diarizer is None
        assert client.post("/api/sessions", json={"num_speakers": 20}).status_code == 200
        assert client.post("/api/sessions", json={"num_speakers": 40}).status_code == 400
        assert client.post("/api/sessions", json={"num_speakers": -1}).status_code == 400
        assert (
            client.put("/api/settings/models", json={**defaults, "language": "ne"}).status_code
            == 400
        )
        nemotron = {**defaults, "diarization_id": "nemotron-diarization"}
        assert client.put("/api/settings/models", json=nemotron).status_code == 400
        automatic = client.put("/api/settings/models", json={**nemotron, "max_speakers": None})
        assert automatic.status_code == 200, automatic.text
        assert automatic.json()["max_speakers"] == 8
        assert load_config(config).diarization.max_speakers == 8
        lower = client.put("/api/settings/models", json={**nemotron, "max_speakers": 4})
        assert lower.status_code == 200, lower.text
        assert lower.json()["max_speakers"] == 4
        assert (
            client.put("/api/settings/models", json={**nemotron, "max_speakers": 8}).status_code
            == 200
        )
        assert client.post("/api/sessions", json={"num_speakers": 16}).status_code == 400
        assert (
            client.post(
                "/api/sessions", json={"attendees": [f"Person {i}" for i in range(16)]}
            ).status_code
            == 400
        )
        # Switching back to Pyannote restores unrestricted automatic clustering.
        automatic = client.put("/api/settings/models", json={**defaults, "max_speakers": None})
        assert automatic.status_code == 200, automatic.text
        assert automatic.json()["max_speakers"] is None
        # A pending review must keep the model used to learn the voices.
        session = client.app.state.manager.create(SessionMeta(), "upload")
        session.state = "review"
        assert client.put("/api/settings/models", json=defaults).status_code == 409
        session.state = "done"
        client.app.state.manager._warm = Future()
        assert client.put("/api/settings/models", json=defaults).status_code == 409


def test_unready_selection_and_failed_config_save_leave_models_unchanged(
    cfg, tmp_path, fake_llm, monkeypatch
):
    monkeypatch.setattr("dzomdu.server.app.compatible", lambda m: None)
    monkeypatch.setattr(ModelLibrary, "ready", lambda self, key: False)
    original = cfg.asr
    pipe = Pipeline(cfg, llm=fake_llm)
    with TestClient(create_app(cfg, pipe, config_path=tmp_path / "config.toml")) as client:
        body = {"asr_id": "qwen-small", "diarization_id": "pyannote"}
        assert client.put("/api/settings/models", json=body).status_code == 400
        assert cfg.asr is original
        monkeypatch.setattr(ModelLibrary, "ready", lambda self, key: True)

        def fail(*args):
            raise OSError("disk full")

        monkeypatch.setattr("dzomdu.server.app.save_config", fail)
        assert client.put("/api/settings/models", json=body).status_code == 500
        assert cfg.asr is original


def test_alternative_final_alignment_offsets_chunks_and_preview_skips_aligner(tmp_path):
    path = tmp_path / "audio.wav"
    samples = np.zeros(31 * 16000, np.float32)
    write_wav(path, samples)
    backend = MLXAudioBackend(ASRConfig(backend="mlx-audio", model=OPTIONS["qwen-small"].repo))
    backend._model = SimpleNamespace(generate=lambda *a, **k: SimpleNamespace(text="Hello world"))
    backend._aligner = SimpleNamespace(
        generate=lambda **k: SimpleNamespace(
            items=[
                SimpleNamespace(text="Hello", start_time=0.1, end_time=0.5),
                SimpleNamespace(text="world", start_time=0.6, end_time=0.9),
            ]
        )
    )
    words = backend.transcribe(Audio(samples, 16000, path))
    assert [w.start for w in words] == [0.1, 0.6, 30.1, 30.6]
    assert not list(tmp_path.glob("*.alternative-*.wav"))
    assert backend.transcribe_preview(Audio(samples, 16000, path))[0].text == "Hello world"


def test_alternative_load_reuses_cached_weights(tmp_path, monkeypatch):
    from pathlib import Path

    calls = []
    model = object()
    monkeypatch.setitem(
        sys.modules,
        "mlx_audio.stt",
        SimpleNamespace(load=lambda *a, **k: calls.append((a, k)) or model),
    )

    def cached(repo, **kwargs):
        assert repo == OPTIONS["qwen-small"].repo
        assert kwargs == {"local_files_only": True}
        return str(tmp_path)

    monkeypatch.setattr("huggingface_hub.snapshot_download", cached)
    backend = MLXAudioBackend(ASRConfig(model=OPTIONS["qwen-small"].repo))
    assert backend._load() is model
    assert backend._load() is model
    assert calls == [((Path(tmp_path),), {})]


@pytest.mark.parametrize("model_id", ["voxtral", "nemotron", "whisper-large", "whisper-cpu"])
def test_removed_transcription_model_cannot_be_queued(cfg, model_id):
    assert model_id not in OPTIONS
    assert "whisper-turbo" in OPTIONS
    assert MLXAudioBackend(ASRConfig()).model_id == OPTIONS["qwen-small"].repo
    library = ModelLibrary(cfg)
    try:
        with pytest.raises(ValueError, match="Unknown model"):
            library.queue([model_id])
    finally:
        library.shutdown()


def test_nemotron_keeps_voiceprint_space_and_guards_speaker_capacity(cfg, tmp_path):
    backend = NemotronDiarizer(cfg.diarization)
    assert backend.embedding_id == "pyannote:pyannote/speaker-diarization-community-1"
    audio = Audio(np.zeros(100, np.float32), 16000, tmp_path / "audio.wav")
    with pytest.raises(ValueError, match="at most 8"):
        backend.diarize(audio, num_speakers=16)


def test_live_recognition_has_no_fifteen_speaker_cap():
    from dzomdu.live import LiveSpeakerTracker
    from dzomdu.speakers.matching import LibraryEntry

    vectors = np.eye(20, dtype=np.float32)
    library = [LibraryEntry(str(i), f"Person {i}", vectors[i : i + 1]) for i in range(20)]
    known = LiveSpeakerTracker(library, match_threshold=0.6)
    assert [known.label(v) for v in vectors] == [f"Person {i}" for i in range(20)]
    unknown = LiveSpeakerTracker([], match_threshold=0.6)
    assert [unknown.label(v) for v in vectors] == [f"Speaker {i + 1}" for i in range(20)]


def test_auto_language_survives_restart(cfg, tmp_path):
    from dzomdu.asr import get_asr_backend
    from dzomdu.config import save_config

    cfg.asr = ASRConfig(backend="mlx-whisper", language="auto")
    path = save_config(cfg, tmp_path / "config.toml")
    loaded = load_config(path)
    assert loaded.asr.language == "auto"
    assert get_asr_backend(loaded.asr).language is None
