"""Run the Phase 0 benchmarks described by a manifest file (see bench/manifest.example.yaml)."""

from __future__ import annotations

import copy
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import numpy as np
import yaml

from ..asr import get_asr_backend
from ..audio import file_sha256, prepare_audio
from ..config import Config
from ..diarize import Diarizer, get_diarizer, l2_normalize
from ..llm.client import LLMClient, LLMError
from ..notes.render import render_note
from ..pipeline import Pipeline
from ..speakers.matching import similarity
from .labels import read_speaker_labels
from .metrics import der, verification, wer

Log = Callable[[str], None]


@dataclass
class BenchMeeting:
    id: str
    audio: Path
    reference_text: Path | None = None
    reference_speakers: Path | None = None
    num_speakers: int | None = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class Manifest:
    meetings: list[BenchMeeting]
    asr_backends: list[str]
    llm_models: list[str]
    template: str


def load_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base = path.parent

    def rel(p: str | None) -> Path | None:
        return (base / p).expanduser() if p else None

    meetings = []
    for m in data.get("meetings", []):
        meetings.append(
            BenchMeeting(
                id=str(m["id"]),
                audio=rel(m["audio"]),  # type: ignore[arg-type]
                reference_text=rel(m.get("reference_text")),
                reference_speakers=rel(m.get("reference_speakers")),
                num_speakers=m.get("num_speakers"),
                tags={k: str(v) for k, v in (m.get("tags") or {}).items()},
            )
        )
    return Manifest(
        meetings=meetings,
        asr_backends=list(data.get("asr_backends", ["parakeet"])),
        llm_models=list(data.get("llm_models", [])),
        template=str(data.get("template", "standard")),
    )


def _audio(cfg: Config, path: Path):
    sha = file_sha256(path)
    return prepare_audio(path, cfg.cache_dir / sha[:16])


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _tags(m: BenchMeeting) -> str:
    return ", ".join(f"{k}={v}" for k, v in m.tags.items()) or "—"


# -- ASR --------------------------------------------------------------------------------------


def bench_asr(cfg: Config, manifest: Manifest, out: Path, log: Log) -> str:
    rows = []
    totals: dict[str, list[float]] = {}
    for backend in manifest.asr_backends:
        asr = get_asr_backend(_with_backend(cfg, backend))
        errs = refs = 0
        audio_s = proc_s = 0.0
        for m in manifest.meetings:
            if not m.reference_text:
                continue
            audio = _audio(cfg, m.audio)
            log(f"ASR {backend}: {m.id}")
            t0 = time.perf_counter()
            words = asr.transcribe(audio)
            elapsed = time.perf_counter() - t0
            hyp = " ".join(w.text for w in words)
            (out / "asr" / backend).mkdir(parents=True, exist_ok=True)
            (out / "asr" / backend / f"{m.id}.txt").write_text(hyp, encoding="utf-8")
            score, e, n = wer(m.reference_text.read_text(encoding="utf-8"), hyp)
            errs, refs = errs + e, refs + n
            audio_s, proc_s = audio_s + audio.duration, proc_s + elapsed
            speed = f"{audio.duration / elapsed:.0f}x"
            rows.append([backend, m.id, _tags(m), f"{score:.1%}", speed])
        if refs:
            totals[backend] = [errs / refs, audio_s / max(proc_s, 1e-9)]
    if not rows:
        return "## ASR\n\nNo meetings have `reference_text`, so WER cannot be measured.\n"
    summary = [
        [b, f"{w:.1%}", f"{s:.0f}x"]
        for b, (w, s) in sorted(totals.items(), key=lambda kv: kv[1][0])
    ]
    return (
        "## ASR (word error rate, lower is better)\n\n"
        + _table(["Backend", "Overall WER", "Speed (× real time)"], summary)
        + "\n\n### Per meeting\n\n"
        + _table(["Backend", "Meeting", "Tags", "WER", "Speed"], rows)
        + "\n"
    )


def _with_backend(cfg: Config, backend: str):
    a = copy.copy(cfg.asr)
    a.backend, a.model = backend, None
    return a


# -- Diarization ------------------------------------------------------------------------------


def bench_diarization(cfg: Config, manifest: Manifest, out: Path, log: Log) -> str:
    diarizer = get_diarizer(cfg.diarization)
    rows = []
    totals = np.zeros(4)  # missed, fa, confusion, total
    for m in manifest.meetings:
        if not m.reference_speakers:
            continue
        audio = _audio(cfg, m.audio)
        ref = read_speaker_labels(m.reference_speakers)
        for known in (False, True):
            if known and not m.num_speakers:
                continue
            log(f"Diarization: {m.id}{' (known speaker count)' if known else ''}")
            t0 = time.perf_counter()
            hyp = diarizer.diarize(audio, num_speakers=m.num_speakers if known else None)
            elapsed = time.perf_counter() - t0
            r = der(ref, hyp)
            if not known:
                totals += [r.missed, r.false_alarm, r.confusion, r.total]
            n_ref, n_hyp = len({s.speaker for s in ref}), len({s.speaker for s in hyp})
            rows.append(
                [
                    m.id + (" (n given)" if known else ""),
                    _tags(m),
                    f"{r.der:.1%}",
                    f"{r.missed / r.total:.1%}" if r.total else "—",
                    f"{r.false_alarm / r.total:.1%}" if r.total else "—",
                    f"{r.confusion / r.total:.1%}" if r.total else "—",
                    f"{n_ref} / {n_hyp}",
                    f"{audio.duration / elapsed:.0f}x",
                ]
            )
    if not rows:
        return "## Diarization\n\nNo meetings have `reference_speakers`.\n"
    overall = (totals[0] + totals[1] + totals[2]) / totals[3] if totals[3] else 0.0
    return (
        f"## Diarization ({diarizer.model_id})\n\n"
        f"Overall DER (speaker count not given): **{overall:.1%}** "
        "(collar 0.25 s; missed + false alarm + confusion)\n\n"
        + _table(
            [
                "Meeting",
                "Tags",
                "DER",
                "Missed",
                "False alarm",
                "Confusion",
                "Speakers ref/found",
                "Speed",
            ],
            rows,
        )
        + "\n"
    )


# -- Speaker identification ------------------------------------------------------------------


def _segment_embeddings(
    diarizer: Diarizer, cfg: Config, m: BenchMeeting, min_dur: float = 2.0, per_speaker: int = 20
) -> dict[str, np.ndarray]:
    audio = _audio(cfg, m.audio)
    ref = read_speaker_labels(m.reference_speakers)  # type: ignore[arg-type]
    by_name: dict[str, list] = {}
    for s in ref:
        if s.duration >= min_dur:
            by_name.setdefault(s.speaker, []).append(s)
    out = {}
    for name, segs in by_name.items():
        segs = sorted(segs, key=lambda s: s.duration, reverse=True)[:per_speaker]
        embs = diarizer.embed(
            [audio.slice(s.start, min(s.end, s.start + 20)) for s in segs], audio.sample_rate
        )
        embs = embs[np.all(np.isfinite(embs), axis=1)]
        if len(embs):
            out[name] = embs
    return out


def bench_speaker_id(cfg: Config, manifest: Manifest, out: Path, log: Log) -> str:
    """Score distributions for same-person vs different-person voice pairs, the thresholds
    they imply, and leave-one-meeting-out identification accuracy."""
    diarizer = get_diarizer(cfg.diarization)
    labelled = [m for m in manifest.meetings if m.reference_speakers]
    if not labelled:
        return "## Speaker identification\n\nNo meetings have `reference_speakers`.\n"
    per_meeting: dict[str, dict[str, np.ndarray]] = {}
    for m in labelled:
        log(f"Speaker embeddings: {m.id}")
        per_meeting[m.id] = _segment_embeddings(diarizer, cfg, m)

    # pairs of segment embeddings; cross-meeting pairs are what recognition actually faces
    cross = len(per_meeting) > 1
    genuine, impostor = [], []
    items = [
        (mid, name, e) for mid, d in per_meeting.items() for name, embs in d.items() for e in embs
    ]
    for (m1, n1, e1), (m2, n2, e2) in combinations(items, 2):
        if cross and m1 == m2:
            continue
        (genuine if n1 == n2 else impostor).append(float(e1 @ e2))
    if not genuine or not impostor:
        return (
            "## Speaker identification\n\nNeed the same people in at least two labelled "
            "meetings (and more than one person) to calibrate.\n"
        )
    v = verification(np.array(genuine), np.array(impostor))

    # leave-one-meeting-out: enrol from other meetings, identify each person in this one
    correct = total = seg_correct = seg_total = 0
    rows = []
    if cross:
        for mid, people in per_meeting.items():
            library = {}
            for other, d in per_meeting.items():
                if other != mid:
                    for name, embs in d.items():
                        library.setdefault(name, []).append(embs)
            library = {k: np.concatenate(v_) for k, v_ in library.items()}
            if not library:
                continue
            for name, embs in people.items():
                if name not in library:
                    continue
                cluster = l2_normalize(embs.mean(0))
                scores = {k: similarity(cluster, ref) for k, ref in library.items()}
                best = max(scores, key=scores.get)  # type: ignore[arg-type]
                total += 1
                correct += best == name
                for e in embs:
                    s = {k: similarity(e, ref) for k, ref in library.items()}
                    seg_total += 1
                    seg_correct += max(s, key=s.get) == name  # type: ignore[arg-type]
                rows.append(
                    [
                        mid,
                        name,
                        best,
                        f"{scores[best]:.3f}",
                        f"{scores.get(name, float('nan')):.3f}",
                    ]
                )

    (out / "speaker_id").mkdir(parents=True, exist_ok=True)
    (out / "speaker_id" / "scores.json").write_text(
        json.dumps({"genuine": genuine, "impostor": impostor})
    )
    lines = [
        f"## Speaker identification ({diarizer.model_id})",
        "",
        f"Pairs compared: {v.n_genuine} same-person, {v.n_impostor} different-person"
        + (" (across meetings only)" if cross else " (within one meeting; add more meetings)"),
        "",
        f"- Mean similarity: same person **{v.genuine_mean:.3f}**, "
        f"different people **{v.impostor_mean:.3f}**",
        f"- Equal error rate: **{v.eer:.1%}** at threshold {v.eer_threshold:.3f}",
        f"- Threshold for ≤1% false accepts: {v.threshold_far_1pct:.3f} "
        f"(rejects {v.frr_at_far_1pct:.1%} of genuine single segments)",
        "",
        "Suggested config (whole-speaker averages are more reliable than single segments, so "
        "these are conservative):",
        "",
        "```toml",
        "[speakers]",
        f"accept_threshold = {max(v.threshold_far_1pct, v.eer_threshold):.2f}",
        f"suggest_threshold = {min(v.eer_threshold, v.threshold_far_1pct) - 0.05:.2f}",
        "```",
    ]
    if total:
        lines += [
            "",
            f"Leave-one-meeting-out identification: **{correct}/{total}** speakers correct "
            f"({correct / total:.0%}); single segments {seg_correct}/{seg_total} "
            f"({seg_correct / max(seg_total, 1):.0%}).",
            "",
            _table(["Meeting", "True speaker", "Top match", "Top score", "True score"], rows),
        ]
    return "\n".join(lines) + "\n"


# -- LLM --------------------------------------------------------------------------------------


def bench_llm(cfg: Config, manifest: Manifest, out: Path, log: Log, seed: int = 7) -> str:
    """Generate notes with every model for every meeting, under shuffled letters, so they can
    be judged blind. The key is written separately."""
    if not manifest.llm_models:
        return "## LLM\n\nAdd `llm_models` to the manifest.\n"
    rng = random.Random(seed)
    key: dict[str, dict[str, str]] = {}
    rows = []
    base = Pipeline(cfg)
    template = base.template(manifest.template)
    for m in manifest.meetings:
        log(f"Transcribing for LLM comparison: {m.id}")
        analysis = base.analyze(m.audio, num_speakers=m.num_speakers)
        record = analysis.record
        letters = [chr(ord("A") + i) for i in range(len(manifest.llm_models))]
        rng.shuffle(letters)
        folder = out / "llm" / m.id
        folder.mkdir(parents=True, exist_ok=True)
        key[m.id] = {}
        for letter, model in zip(letters, manifest.llm_models, strict=True):
            llm_cfg = copy.copy(cfg.llm)
            llm_cfg.model = model
            pipe = Pipeline(
                cfg,
                asr=base.asr,
                diarizer=base.diarizer,
                llm=LLMClient(llm_cfg),
                store=base.store,
                vault=base.vault,
            )
            log(f"LLM {letter}: {m.id}")
            t0 = time.perf_counter()
            try:
                notes = pipe.summarize(record, template)
                status = "ok"
            except LLMError as exc:
                notes, status = None, f"failed: {exc}"[:80]
            elapsed = time.perf_counter() - t0
            rec = copy.deepcopy(record)
            rec.title = rec.title or f"{m.id} – version {letter}"
            text = render_note(rec, notes, template if notes else None, None)
            (folder / f"{letter}.md").write_text(text, encoding="utf-8")
            key[m.id][letter] = model
            rows.append([m.id, letter, f"{elapsed:.0f}s", status])
    (out / "llm" / "KEY-open-after-judging.json").write_text(json.dumps(key, indent=1))
    return (
        "## LLM (blind comparison)\n\n"
        f"Notes for each meeting are in `{out / 'llm'}/<meeting>/<letter>.md`. Read and rank "
        "them (accuracy first, then usefulness), then open `KEY-open-after-judging.json`.\n\n"
        + _table(["Meeting", "Version", "Time", "Status"], rows)
        + "\n"
    )


BENCHES = {
    "asr": bench_asr,
    "diarization": bench_diarization,
    "speaker-id": bench_speaker_id,
    "llm": bench_llm,
}
