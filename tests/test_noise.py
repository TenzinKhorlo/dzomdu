from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from conftest import FakeASR, FakeDiarizer, make_meeting
from fastapi.testclient import TestClient

from dzomdu.audio import SAMPLE_RATE, Audio, write_wav
from dzomdu.config import NoiseConfig, load_config, save_config
from dzomdu.live import LiveSpeakerTracker, LiveTranscriber
from dzomdu.models import Word
from dzomdu.noise import NoiseSuppressor, enhance_audio
from dzomdu.pipeline import Pipeline
from dzomdu.server.app import create_app
from dzomdu.server.sessions import SessionMeta


@pytest.fixture
def native_runtime():
    pytest.importorskip("pyrnnoise")
    pytest.importorskip("scipy")


def process(samples, chunk, strength=0.5):
    suppressor = NoiseSuppressor(strength)
    try:
        blocks = [suppressor.feed(samples[i : i + chunk]) for i in range(0, len(samples), chunk)]
        blocks.append(suppressor.finish())
        return tuple(np.concatenate([b[i] for b in blocks]) for i in range(2))
    finally:
        suppressor.close()


def test_stream_preserves_timeline_and_tail_independent_of_chunk_boundaries(native_runtime):
    rng = np.random.default_rng(4)
    audio = rng.normal(0, 0.02, 16000 + 97).astype(np.float32)
    expected, dry = process(audio, len(audio))
    assert np.array_equal(dry, audio)
    for chunk in (1, 159, 731):
        cleaned, original = process(audio, chunk)
        assert np.array_equal(original, audio)
        assert len(cleaned) == len(audio)
        assert np.isfinite(cleaned).all()
        assert np.allclose(cleaned, expected, atol=1e-6)
    for size in (0, 1, 159, 160, 321):
        cleaned, original = process(audio[:size], 17)
        assert len(cleaned) == size
        assert np.array_equal(original, audio[:size])


def test_native_delay_is_compensated_before_mixing(native_runtime):
    from scipy.signal import correlate, correlation_lags

    t = np.arange(SAMPLE_RATE * 3) / SAMPLE_RATE
    audio = (0.15 * np.sin(2 * np.pi * (150 * t + 600 * t * t))).astype(np.float32)
    cleaned, original = process(audio, 731, strength=0.75)
    wet = (cleaned - 0.25 * original) / 0.75
    correlation = correlate(wet, original, method="fft")
    lag = correlation_lags(len(wet), len(original))[np.argmax(correlation)]
    assert abs(lag) < SAMPLE_RATE * 0.001  # under 1 ms, rather than a 20 ms offset


def test_enhanced_cache_retains_original_and_changes_with_settings(native_runtime, tmp_path):
    raw = np.random.default_rng(0).normal(0, 0.02, 20003).astype(np.float32)
    source = tmp_path / "audio.wav"
    write_wav(source, raw)
    original_bytes = source.read_bytes()
    audio = Audio(raw, SAMPLE_RATE, source)
    light = enhance_audio(audio, tmp_path, NoiseConfig(True, 0.5))
    balanced = enhance_audio(audio, tmp_path, NoiseConfig(True, 0.75))
    assert light.path != balanced.path and light.path != source
    assert light.duration == balanced.duration == audio.duration
    assert source.read_bytes() == original_bytes
    cached = enhance_audio(audio, tmp_path, NoiseConfig(True, 0.5))
    assert cached.path == light.path
    assert np.allclose(cached.samples, light.samples, atol=1 / 32767 + 1e-6)
    assert enhance_audio(audio, tmp_path, NoiseConfig(False)).path == source


def test_pipeline_uses_raw_overlapping_voices_and_distinct_asr_caches(cfg, tmp_path, monkeypatch):
    source = tmp_path / "meeting.wav"
    segments, words = make_meeting(
        source,
        [
            ("Alice", 0, 2, "First speaker talking"),
            ("Bob", 1, 3, "Second speaker talking"),
        ],
    )
    cfg.speakers.split_mixed_clusters = False
    diar = FakeDiarizer({3: segments})
    asr = FakeASR({3: words})
    raw_inputs = []
    original_diarize = diar.diarize

    def diarize(audio, *args):
        raw_inputs.append(audio.samples.copy())
        return original_diarize(audio, *args)

    def enhance(audio, work, settings):
        path = work / f"audio-clean-{settings.strength}.wav"
        write_wav(path, audio.samples * 0.5)
        return Audio(audio.samples * 0.5, audio.sample_rate, path)

    monkeypatch.setattr(diar, "diarize", diarize)
    monkeypatch.setattr("dzomdu.pipeline.enhance_audio", enhance)
    pipe = Pipeline(cfg, asr=asr, diarizer=diar)
    baseline = pipe.analyze(source)
    original_bytes = baseline.audio.path.read_bytes()
    cfg.noise = NoiseConfig(True, 0.5)
    cleaned = pipe.analyze(source)
    # prepare_audio's first decode and its cached PCM differ by one quantisation step.
    assert np.allclose(baseline.audio.samples, cleaned.audio.samples, atol=2 / 32767)
    assert np.array_equal(raw_inputs[0], baseline.audio.samples)
    assert cleaned.audio.path.read_bytes() == original_bytes
    assert diar.calls == 1 and asr.calls == 2
    assert len(cleaned.voices) == 2
    pipe.analyze(source)
    assert asr.calls == 2
    cfg.noise.strength = 0.75
    pipe.analyze(source)
    assert asr.calls == 3


def test_live_embeddings_use_original_samples_while_transcription_is_cleaned(tmp_path):
    class QuietDenoiser:
        def feed(self, samples):
            return samples * 0.5, samples

        def finish(self):
            return np.zeros(0, np.float32), np.zeros(0, np.float32)

        def close(self):
            pass

    class CaptureASR:
        def transcribe_preview(self, audio):
            captured_asr.append(audio.samples.copy())
            return [Word("Speech", 0, 1)]

    class CaptureEmbedder:
        def embed(self, samples, sr):
            captured_voice.append(samples[0].copy())
            return np.ones((1, 32), np.float32)

    captured_asr, captured_voice = [], []
    t = np.arange(2 * SAMPLE_RATE) / SAMPLE_RATE
    raw = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    raw = np.concatenate([raw, np.zeros(SAMPLE_RATE, np.float32)])
    with ThreadPoolExecutor(max_workers=1) as worker:
        live = LiveTranscriber(
            CaptureASR(),
            CaptureEmbedder(),
            LiveSpeakerTracker([], 0.6),
            tmp_path,
            worker.submit,
            lambda _: None,
            partial_every=None,
            noise=QuietDenoiser(),
        )
        for i in range(0, len(raw), 731):
            live.feed(raw[i : i + 731])
        live.finish()
    assert captured_asr and captured_voice
    assert np.allclose(captured_asr[0] * 2, captured_voice[0])
    assert len(live._raw) <= 12 * SAMPLE_RATE


def test_settings_validate_persist_and_block_active_meetings(cfg, tmp_path, monkeypatch):
    class Probe:
        delay_samples = 340

        def __init__(self, strength):
            if strength == 0.25:
                raise RuntimeError("Runtime unavailable")

        def close(self):
            pass

    monkeypatch.setattr("dzomdu.server.app.NoiseSuppressor", Probe)
    config = tmp_path / "config.toml"
    with TestClient(create_app(cfg, config_path=config)) as client:
        assert client.get("/api/settings/noise").json()["enabled"] is False
        response = client.put("/api/settings/noise", json={"enabled": True, "strength": 0.5})
        assert response.status_code == 200
        assert load_config(config).noise == NoiseConfig(True, 0.5)
        assert (
            client.put("/api/settings/noise", json={"enabled": True, "strength": 1}).status_code
            == 422
        )
        assert (
            client.put("/api/settings/noise", json={"enabled": True, "strength": 0.25}).status_code
            == 400
        )
        assert cfg.noise == NoiseConfig(True, 0.5)
        session = client.app.state.manager.create(SessionMeta(), "record")
        session.state = "recording"
        assert client.put("/api/settings/noise", json={"enabled": False}).status_code == 409
        session.state = "done"

        def fail_save(*_):
            raise OSError("Disk full")

        monkeypatch.setattr("dzomdu.server.app.save_config", fail_save)
        assert client.put("/api/settings/noise", json={"enabled": False}).status_code == 500
        assert cfg.noise.enabled


@pytest.mark.parametrize("failure", ["feed", "finish"])
def test_live_denoiser_failure_keeps_pending_audio_on_its_original_timeline(tmp_path, failure):
    class FailingDenoiser:
        def feed(self, samples):
            if failure == "feed":
                raise RuntimeError("Processing failed")
            return np.zeros(0, np.float32), np.zeros(0, np.float32)

        def finish(self):
            raise RuntimeError("Processing failed")

        def close(self):
            pass

    errors = []
    live = LiveTranscriber(
        None,
        None,
        LiveSpeakerTracker([], 0.6),
        tmp_path,
        lambda _: None,
        lambda _: None,
        errors.append,
        partial_every=None,
        noise=FailingDenoiser(),
    )
    # Silence avoids scheduling ASR: check exactly what reaches the segmenter.
    raw = np.full(197, 0.0001, np.float32)
    live.feed(raw)
    live.finish()
    assert live._output_samples == len(raw)
    assert live.noise is None
    assert errors and "using original audio" in errors[0]


def test_config_rejects_unsafe_strength_and_preserves_existing_settings(cfg, tmp_path):
    with pytest.raises(ValueError):
        NoiseConfig(True, 1)
    cfg.noise = NoiseConfig(True, 0.75)
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.noise == cfg.noise
    assert loaded.asr == cfg.asr and loaded.diarization == cfg.diarization
