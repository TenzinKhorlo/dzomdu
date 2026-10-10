"""Curated model downloads and selection. Downloading weights never changes a default."""

from __future__ import annotations

import gc
import json
import platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Config, is_installed


@dataclass(frozen=True)
class ModelOption:
    id: str
    name: str
    kind: str
    backend: str
    repo: str
    package: str
    size_gb: float
    description: str
    mac_only: bool = False
    languages: tuple[str, ...] = ("en",)
    speaker_limit: int | None = None
    dependencies: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()


ALIGNER = "qwen-aligner"
CATALOG = [
    ModelOption(
        "parakeet",
        "Parakeet TDT 0.6B v2",
        "asr",
        "parakeet",
        "mlx-community/parakeet-tdt-0.6b-v2",
        "parakeet_mlx",
        1.2,
        "English · word timestamps · current accuracy baseline",
        True,
    ),
    ModelOption(
        "whisper-turbo",
        "Whisper large-v3 Turbo",
        "asr",
        "mlx-whisper",
        "mlx-community/whisper-large-v3-turbo",
        "mlx_whisper",
        1.6,
        "English & Nepali · faster Whisper option",
        True,
        ("en", "ne", "auto"),
    ),
    ModelOption(
        "whisper-turbo-cuda",
        "Whisper Turbo (CPU / CUDA)",
        "asr",
        "faster-whisper",
        "dropbox-dash/faster-whisper-large-v3-turbo",
        "faster_whisper",
        1.6,
        "English & Nepali · Linux / Windows · NVIDIA GPU or CPU · word timestamps",
        languages=("en", "ne", "auto"),
        platforms=("Linux", "Windows"),
    ),
    ModelOption(
        "moonshine-medium",
        "Moonshine Medium Streaming",
        "asr",
        "moonshine",
        "medium-streaming",
        "moonshine_voice",
        0.3,
        "English · compact CPU model · word timestamps",
    ),
    ModelOption(
        "moonshine-small",
        "Moonshine Small Streaming",
        "asr",
        "moonshine",
        "small-streaming",
        "moonshine_voice",
        0.15,
        "English · smaller CPU model · word timestamps",
    ),
    ModelOption(
        "qwen-small",
        "Qwen3-ASR 0.6B",
        "asr",
        "mlx-audio",
        "mlx-community/Qwen3-ASR-0.6B-8bit",
        "mlx_audio",
        0.8,
        "English · 8-bit MLX · includes word aligner",
        True,
        dependencies=(ALIGNER,),
    ),
    ModelOption(
        "qwen-large",
        "Qwen3-ASR 1.7B",
        "asr",
        "mlx-audio",
        "mlx-community/Qwen3-ASR-1.7B-8bit",
        "mlx_audio",
        2.0,
        "English · 8-bit MLX · includes word aligner",
        True,
        dependencies=(ALIGNER,),
    ),
    ModelOption(
        "pyannote",
        "Pyannote Community-1",
        "diarization",
        "pyannote",
        "pyannote/speaker-diarization-community-1",
        "pyannote.audio",
        0.4,
        "Recommended for 15+ people · automatic clustering · Mac GPU / CPU",
    ),
    ModelOption(
        "nemotron-diarization",
        "Nemotron-3-Diarization",
        "diarization",
        "nemotron-mlx",
        "mlx-community/Nemotron-3-Diarization",
        "mlx_audio",
        0.25,
        "Experimental · up to 8 speakers · reuses Pyannote voice recognition",
        True,
        speaker_limit=8,
        dependencies=("pyannote",),
    ),
    ModelOption(
        ALIGNER,
        "Qwen3 word aligner",
        "alignment",
        "mlx-audio",
        "mlx-community/Qwen3-ForcedAligner-0.6B-8bit",
        "mlx_audio",
        0.8,
        "Downloaded once for Qwen timestamps",
        True,
    ),
]
OPTIONS = {m.id: m for m in CATALOG}
PATTERNS = [
    "*.json",
    "*.yaml",
    "*.yml",
    "*.safetensors",
    "*.bin",
    "*.npz",
    "*.model",
    "*.txt",
    "*.tiktoken",
    "*.pt",
]


def compatible(option: ModelOption) -> str | None:
    if option.platforms and platform.system() not in option.platforms:
        return f"Requires {' or '.join(option.platforms)}."
    if option.mac_only and not (platform.system() == "Darwin" and platform.machine() == "arm64"):
        return "Requires an Apple Silicon Mac."
    if option.backend == "moonshine" and platform.system() == "Darwin":
        if int(platform.mac_ver()[0].split(".")[0] or 0) < 15:
            return "Requires macOS 15 or newer."
    return None


def runtime_command(option: ModelOption) -> str:
    extra = {
        "parakeet": "mac",
        "mlx-whisper": "mac",
        "mlx-audio": "speech-models",
        "moonshine": "moonshine",
        "pyannote": "diarize",
        "nemotron-mlx": "speech-models,diarize",
        "faster-whisper": "whisper",
    }[option.backend]
    return f"python -m pip install -e '.[{extra}]'"


def current_id(cfg: Config, kind: str) -> str | None:
    section = cfg.asr if kind == "asr" else cfg.diarization
    model = section.model
    if model is None:
        model = {
            "parakeet": OPTIONS["parakeet"].repo,
            "mlx-whisper": OPTIONS["whisper-turbo"].repo,
            "faster-whisper": OPTIONS["whisper-turbo-cuda"].repo,
        }.get(section.backend)
    if section.backend == "faster-whisper" and model in (
        "large-v3-turbo", "turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
    ):
        model = OPTIONS["whisper-turbo-cuda"].repo
    return next(
        (
            m.id
            for m in CATALOG
            if m.kind == kind and m.backend == section.backend and m.repo == model
        ),
        None,
    )


class ModelLibrary:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.data_dir / "model-library"
        self.index = self.root / "downloads.json"
        try:
            self.receipts = json.loads(self.index.read_text())
        except (OSError, ValueError):
            self.receipts = {}
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dzomdu-downloads")
        self.job_file = self.root / "queue.json"
        self._last_save = 0.0
        try:
            previous = json.loads(self.job_file.read_text())
        except (OSError, ValueError):
            previous = {}
        resume = [
            key
            for key, job in previous.items()
            if key in OPTIONS
            and job.get("state") in ("queued", "downloading")
            and compatible(OPTIONS[key]) is None
        ]
        self.jobs = {
            key: job for key, job in previous.items() if key in OPTIONS and key not in resume
        }
        for key in resume:
            try:
                self.queue([key])
            except ValueError:
                self.jobs[key] = {
                    "state": "error",
                    "progress": 0.0,
                    "detail": "Install the runtime, then retry to resume.",
                }

    def shutdown(self):
        self.worker.shutdown(wait=False, cancel_futures=True)

    def downloaded(self, model_id: str) -> bool:
        # Another process (e.g. initial setup) may have finished a download since startup.
        try:
            self.receipts.update(json.loads(self.index.read_text()))
        except (OSError, ValueError):
            pass
        option = OPTIONS[model_id]
        receipt = self.receipts.get(model_id, {})
        if files := receipt.get("files"):
            return all(Path(p).is_file() and Path(p).stat().st_size == size for p, size in files)
        if option.backend == "moonshine":
            return False
        # Recognise models installed before the library existed, without network access.
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        try:
            path = Path(snapshot_download(option.repo, local_files_only=True))
        except LocalEntryNotFoundError:
            return False
        if option.id == "pyannote":
            return (
                (path / "config.yaml").is_file()
                and all(any((path / d).glob("*.bin")) for d in ("embedding", "segmentation"))
                and any((path / "plda").glob("*.npz"))
            )
        return (path / "config.json").is_file() and any(
            p.is_file()
            for pattern in ("*.safetensors", "*.npz", "*.bin")
            for p in path.glob(pattern)
        )

    def ready(self, model_id: str) -> bool:
        m = OPTIONS[model_id]
        return (
            not compatible(m)
            and is_installed(m.package)
            and self.downloaded(model_id)
            and all(self.ready(dep) for dep in m.dependencies)
        )

    def view(self) -> list[dict[str, Any]]:
        with self.lock:
            result = []
            for m in CATALOG:
                job = self.jobs.get(m.id, {})
                downloaded = self.downloaded(m.id)
                result.append(
                    {
                        **asdict(m),
                        "compatible": compatible(m) is None,
                        "compatibility_detail": compatible(m),
                        "runtime_installed": is_installed(m.package),
                        "install_command": runtime_command(m),
                        "downloaded": downloaded,
                        "ready": self.ready(m.id),
                        "state": job.get("state", "downloaded" if downloaded else "missing"),
                        "progress": job.get("progress", 1.0 if downloaded else 0.0),
                        "detail": job.get("detail", ""),
                        "default": current_id(self.cfg, m.kind) == m.id
                        if m.kind != "alignment"
                        else False,
                    }
                )
            return result

    def queue(self, ids: list[str]) -> None:
        for model_id in ids:
            if model_id not in OPTIONS:
                raise ValueError("Unknown model")
            if reason := compatible(OPTIONS[model_id]):
                raise ValueError(reason)
            if OPTIONS[model_id].backend == "moonshine" and not is_installed("moonshine_voice"):
                raise ValueError("Install the speech-models runtime before downloading Moonshine.")
        with self.lock:
            for model_id in ids:
                for dep in OPTIONS[model_id].dependencies:
                    self.queue([dep])
                if self.jobs.get(model_id, {}).get("state") in ("queued", "downloading"):
                    continue
                self.jobs[model_id] = {"state": "queued", "progress": 0.0, "detail": "Queued"}
                self._save_jobs()
                self.worker.submit(self._download, model_id)

    def _save_jobs(self):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.job_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.jobs))
        temporary.replace(self.job_file)
        self._last_save = time.monotonic()

    def _update(self, model_id: str, **values):
        with self.lock:
            self.jobs[model_id].update(values)
            if "state" in values or time.monotonic() - self._last_save > 1.0:
                self._save_jobs()

    def _download(self, model_id: str):
        option = OPTIONS[model_id]
        self._update(model_id, state="downloading", detail="Checking download files")
        try:
            if option.backend == "moonshine":
                from moonshine_voice import ModelArch
                from moonshine_voice.download import get_model_for_language

                arch = getattr(ModelArch, option.repo.upper().replace("-", "_"))
                path, _ = get_model_for_language(
                    "en",
                    arch,
                    include_word_timestamps=True,
                    on_progress=lambda fraction, name: self._update(
                        model_id, progress=fraction, detail=name
                    ),
                )
                paths = [p for p in Path(path).rglob("*") if p.is_file()]
            else:
                from fnmatch import fnmatch

                from huggingface_hub import HfApi, hf_hub_download
                from tqdm.auto import tqdm

                info = HfApi().model_info(option.repo, files_metadata=True)
                files = [f for f in info.siblings if any(fnmatch(f.rfilename, p) for p in PATTERNS)]
                if not files:
                    raise RuntimeError("The repository contains no supported model files.")
                total = sum(f.size or 0 for f in files) or len(files)
                done = 0
                paths = []
                for f in files:
                    self._update(model_id, detail=f.rfilename, progress=done / total)
                    library = self
                    base = done

                    class DownloadProgress(tqdm):
                        def __init__(self, *args, task_library=library, task_base=base, **kwargs):
                            self.library = task_library
                            self.base = task_base
                            kwargs["disable"] = True
                            super().__init__(*args, **kwargs)
                            self.completed = kwargs.get("initial", 0)
                            self.last_report = 0.0

                        def update(self, n=1):
                            self.completed += n
                            if time.monotonic() - self.last_report >= 0.5:
                                self.library._update(
                                    model_id,
                                    progress=min((self.base + self.completed) / total, 1.0),
                                )
                                self.last_report = time.monotonic()
                            return super().update(n)

                    path = hf_hub_download(
                        option.repo, f.rfilename, revision=info.sha, tqdm_class=DownloadProgress
                    )
                    paths.append(Path(path))
                    done += f.size or 1
                    self._update(model_id, progress=min(done / total, 1.0))
            self.root.mkdir(parents=True, exist_ok=True)
            with self.lock:
                try:
                    self.receipts.update(json.loads(self.index.read_text()))
                except (OSError, ValueError):
                    pass
                self.receipts[model_id] = {"files": [(str(p), p.stat().st_size) for p in paths]}
                temporary = self.index.with_suffix(".tmp")
                temporary.write_text(json.dumps(self.receipts))
                temporary.replace(self.index)
            self._update(model_id, state="downloaded", progress=1.0, detail="Download complete")
        except Exception as exc:
            self._update(model_id, state="error", detail=f"{type(exc).__name__}: {exc}")
        finally:
            gc.collect()
