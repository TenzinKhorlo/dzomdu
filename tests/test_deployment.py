"""Deployment settings and GPU failures, without downloading weights or needing CUDA."""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dzomdu.asr import get_asr_backend
from dzomdu.audio import Audio
from dzomdu.config import ASRConfig, load_config, save_config
from dzomdu.model_library import OPTIONS, compatible, current_id

ROOT = Path(__file__).resolve().parents[1]


def test_first_run_and_cpu_to_gpu_preserve_user_settings(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("DZOMDU_CONFIG", str(path))
    for name in (
        "DZOMDU_ASR_BACKEND", "DZOMDU_ASR_MODEL", "DZOMDU_ASR_LANGUAGE",
        "DZOMDU_ASR_DEVICE", "DZOMDU_ASR_COMPUTE_TYPE", "DZOMDU_DIARIZATION_DEVICE",
    ):
        monkeypatch.delenv(name, raising=False)
    main = runpy.run_path(str(ROOT / "docker/configure.py"))["main"]
    main()
    cfg = load_config(path)
    assert cfg.asr.backend == "faster-whisper"
    assert current_id(cfg, "asr") == "whisper-turbo-cuda"
    cfg.asr.language = "ne"
    cfg.llm.model = "my-local-llm"
    cfg.summary_instructions = "Keep my custom instructions"
    save_config(cfg, path)

    monkeypatch.setenv("DZOMDU_ASR_DEVICE", "cuda")
    monkeypatch.setenv("DZOMDU_ASR_COMPUTE_TYPE", "float16")
    monkeypatch.setenv("DZOMDU_DIARIZATION_DEVICE", "cuda")
    monkeypatch.setenv("DZOMDU_ASR_MODEL", "ignored-after-first-start")
    main()
    gpu = load_config(path)
    assert (gpu.asr.device, gpu.asr.compute_type, gpu.diarization.device) == (
        "cuda", "float16", "cuda"
    )
    assert gpu.asr.model == cfg.asr.model
    assert gpu.asr.language == "ne"
    assert gpu.llm.model == "my-local-llm"
    assert gpu.summary_instructions == cfg.summary_instructions

    monkeypatch.setenv("DZOMDU_ASR_DEVICE", "auto")
    monkeypatch.setenv("DZOMDU_ASR_COMPUTE_TYPE", "auto")
    monkeypatch.setenv("DZOMDU_DIARIZATION_DEVICE", "auto")
    main()
    assert load_config(path).asr.device == "auto"
    monkeypatch.setenv("DZOMDU_ASR_DEVICE", "invalid")
    with pytest.raises(ValueError, match="ASR device"):
        main()
    assert load_config(path).asr.device == "auto"  # invalid input never persisted


def test_cuda_asr_configuration_reaches_whisper_runtime(tmp_path, monkeypatch):
    calls = []

    def model(repo, **kwargs):
        calls.append((repo, kwargs))
        return SimpleNamespace(transcribe=lambda *a, **k: ([], None))

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=model))
    cfg = ASRConfig(backend="faster-whisper", device="cuda", compute_type="int8_float16")
    asr = get_asr_backend(cfg)
    audio = Audio(np.zeros(100, np.float32), 16000, tmp_path / "audio.wav")
    assert asr.transcribe(audio) == []
    assert calls == [("large-v3-turbo", {"device": "cuda", "compute_type": "int8_float16"})]


def test_linux_model_options_and_aliases(cfg, monkeypatch):
    monkeypatch.setattr("dzomdu.model_library.platform.system", lambda: "Linux")
    monkeypatch.setattr("dzomdu.model_library.platform.machine", lambda: "x86_64")
    assert compatible(OPTIONS["whisper-turbo-cuda"]) is None
    assert compatible(OPTIONS["pyannote"]) is None
    assert compatible(OPTIONS["parakeet"])
    assert compatible(OPTIONS["nemotron-diarization"])
    for alias in (None, "turbo", "large-v3-turbo", OPTIONS["whisper-turbo-cuda"].repo):
        cfg.asr = ASRConfig(backend="faster-whisper", model=alias)
        assert current_id(cfg, "asr") == "whisper-turbo-cuda"
    monkeypatch.setattr("dzomdu.model_library.platform.system", lambda: "Darwin")
    assert compatible(OPTIONS["whisper-turbo-cuda"])


def test_gpu_preflight_detects_missing_hardware_and_incompatible_settings(
    cfg, tmp_path, monkeypatch
):
    path = save_config(cfg, tmp_path / "config.toml")
    monkeypatch.setenv("DZOMDU_CONFIG", str(path))
    available = {"gpu": False}
    tensor = SimpleNamespace(sum=lambda: SimpleNamespace(item=lambda: 1))
    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: available["gpu"], get_device_name=lambda i: "Test NVIDIA GPU"
        ),
        ones=lambda *a, **k: tensor,
    )
    ct2 = SimpleNamespace(
        get_cuda_device_count=lambda: int(available["gpu"]),
        get_supported_compute_types=lambda d: {"float16", "int8_float16"},
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    libraries = []
    monkeypatch.setattr("ctypes.CDLL", lambda name: libraries.append(name))
    check = runpy.run_path(str(ROOT / "docker/check_gpu.py"))["check"]
    with pytest.raises(RuntimeError, match="No NVIDIA GPU"):
        check()
    available["gpu"] = True
    with pytest.raises(RuntimeError, match="Apple Silicon"):
        check()
    cfg.asr = ASRConfig(backend="faster-whisper", device="cuda", compute_type="float16")
    cfg.diarization.device = "cuda"
    save_config(cfg, path)
    assert "Test NVIDIA GPU" in check()
    assert set(libraries) == {"libcublas.so.12", "libcudnn.so.9"}
    cfg.asr.compute_type = "bfloat16"
    save_config(cfg, path)
    with pytest.raises(RuntimeError, match="not supported"):
        check()
