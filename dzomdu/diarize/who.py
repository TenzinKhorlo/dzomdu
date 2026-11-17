"""Desert Ant Labs Who: on-device speaker diarization from ONNX graphs, in numpy.

A Python port of the pipeline in desert-ant-core's `Sources/Who`: a Kaldi log-mel frontend, an
encoder and query graph per window (60 s and 300 s), a decision rule, and, past five minutes,
a voice graph whose per-speaker embeddings join the five-minute pieces by clustering.

Who labels up to four speakers per five-minute piece (more across a longer recording) and
marks overlapping speech for both speakers. It takes no speaker count, so `num_speakers` and
`max_speakers` only drop the least present extra speakers and `min_speakers` is ignored.
Voiceprints stay on Pyannote: Who has no general embedding.

Weights: https://huggingface.co/desert-ant-labs/who (Desert Ant Labs Source-Available License
1.0; credit Desert Ant Labs, and do not train a competing on-device model on its outputs).
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..audio import SAMPLE_RATE, Audio
from ..config import DiarizationConfig
from ..models import SpeakerSegment
from . import Diarizer
from .pyannote import PyannoteDiarizer

REPO = "desert-ant-labs/who"
# The Hub revision the port was checked against; each revision caches separately.
REVISION = "097d29a140dd19e220cff132e455e515d0e47e59"
DIRECTORY = "onnx-int8"
FRAME_SAMPLES = 400  # one 25 ms frame; less audio than this cannot be labelled
SIDECARS = ("who_meta.json", "who_mel_banks.f32", "who_voice_banks.f32", "who_embed.f16")


def _file_names() -> list[str]:
    graphs = ["encoder_6000", "queries_6000", "encoder_30000", "queries_30000", "voice_3256"]
    return [f"{DIRECTORY}/{n}.onnx" for n in graphs] + [f"{DIRECTORY}/{n}" for n in SIDECARS]


def download() -> list[Path]:
    """Fetch the ONNX int8 graphs and sidecars (about 99 MB) into the Hugging Face cache."""
    from huggingface_hub import hf_hub_download

    return [Path(hf_hub_download(REPO, name, revision=REVISION)) for name in _file_names()]


def _cached() -> list[Path] | None:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return [
            Path(hf_hub_download(REPO, n, revision=REVISION, local_files_only=True))
            for n in _file_names()
        ]
    except LocalEntryNotFoundError:
        return None


# ---------------------------------------------------------------- frontend


@dataclass(frozen=True)
class Frontend:
    """The Kaldi log-mel filterbank the trunk was trained on (`Frontend.swift`)."""

    frame: int
    shift: int
    n_fft: int
    preemphasis: float
    scale: float
    log_floor: float
    banks: np.ndarray  # [bins, mels]
    window: np.ndarray

    @classmethod
    def create(cls, info: dict, banks_file: Path) -> Frontend:
        raw = banks_file.read_bytes()
        mels, bins = struct.unpack_from("<II", raw)
        banks = np.frombuffer(raw, dtype="<f4", count=mels * bins, offset=8).reshape(mels, bins)
        if mels != info["n_mels"] or bins != info["n_fft"] // 2 + 1:
            raise RuntimeError(f"mel bank table is {mels} x {bins}, the metadata disagrees")
        n = info["frame_samples"]
        # symmetric Hamming (Kaldi's, torch's periodic=False)
        window = (0.54 - 0.46 * np.cos(2 * np.pi * np.arange(n) / (n - 1))).astype(np.float32)
        return cls(
            n,
            info["shift_samples"],
            info["n_fft"],
            float(info["preemphasis"]),
            float(info["scale"]),
            float(info["log_floor"]),
            np.ascontiguousarray(banks.T, dtype=np.float32),
            window,
        )

    @property
    def mels(self) -> int:
        return self.banks.shape[1]

    def frames(self, samples: int) -> int:
        """Only frames that fit completely (Kaldi's snip_edges)."""
        return 0 if samples < self.frame else 1 + (samples - self.frame) // self.shift

    def _log_mel(self, samples: np.ndarray, first: int, count: int) -> np.ndarray:
        if count <= 0:
            return np.zeros((0, self.mels), np.float32)
        start = first * self.shift
        span = samples[start : start + (count - 1) * self.shift + self.frame]
        index = np.arange(count)[:, None] * self.shift + np.arange(self.frame)[None, :]
        frames = span[index].astype(np.float64) * self.scale
        frames -= frames.mean(axis=1, keepdims=True)
        previous = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
        frames = (frames - self.preemphasis * previous) * self.window
        power = np.abs(np.fft.rfft(frames, n=self.n_fft, axis=1)) ** 2
        mel = power.astype(np.float32) @ self.banks
        return np.log(np.maximum(mel, self.log_floor))

    def means(self, samples: np.ndarray, piece: int = 6000) -> tuple[np.ndarray, int]:
        """Each mel's mean over the whole recording, then the frame count."""
        total = self.frames(len(samples))
        sums = np.zeros(self.mels, np.float64)
        for first in range(0, total, piece):
            sums += self._log_mel(samples, first, min(piece, total - first)).sum(
                axis=0, dtype=np.float64
            )
        return ((sums / total).astype(np.float32) if total else sums.astype(np.float32)), total

    def features(
        self, samples: np.ndarray, first: int, count: int, means: np.ndarray
    ) -> np.ndarray:
        out = np.empty((count, self.mels), np.float32)
        for at in range(0, count, 6000):
            n = min(6000, count - at)
            out[at : at + n] = self._log_mel(samples, first + at, n) - means
        return out


# ---------------------------------------------------------------- decision and join


@dataclass(frozen=True)
class Turn:
    start: float
    end: float
    label: int


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))


def _stretches(
    presence: np.ndarray, masks: np.ndarray, decision: dict
) -> list[tuple[int, int, int]]:
    """(query, first frame, end frame) where a present query's mask is above the threshold."""
    out = []
    for query in np.flatnonzero(presence > decision["presence_threshold"]):
        row = masks[query]
        activity = row * presence[query] if decision["rule"] == "product" else row
        pool = decision.get("pool", 1)
        if pool > 1:
            grouped = activity.copy()
            for a in range(0, len(activity), pool):
                grouped[a : a + pool] = activity[a : a + pool].mean()
            activity = grouped
        on = np.r_[False, activity > decision["mask_threshold"], False]
        edges = np.flatnonzero(on[1:] != on[:-1])
        out += [(int(query), int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True)]
    return out


def _bounds(first: int, end: int, step: float, centre: float) -> tuple[float, float]:
    """Half a frame either side of the first and last centres, never before zero."""
    return max(centre + step * first - step / 2, 0.0), centre + step * (end - 1) + step / 2


def join_touching(turns: list[Turn]) -> list[Turn]:
    """A speaker's turns that touch make one turn, so one cut at a piece's edge reads as one."""
    out: list[Turn] = []
    for turn in sorted(turns, key=lambda t: (t.label, t.start)):
        if out and out[-1].label == turn.label and turn.start <= out[-1].end + 1e-6:
            out[-1] = Turn(out[-1].start, max(out[-1].end, turn.end), turn.label)
        else:
            out.append(turn)
    return out


def number_by_appearance(turns: list[Turn]) -> list[Turn]:
    """Speakers numbered by when each is first heard, so labels repeat from run to run."""
    label: dict[int, int] = {}
    out = []
    for t in sorted(turns, key=lambda t: (t.start, t.label)):
        out.append(Turn(t.start, t.end, label.setdefault(t.label, len(label))))
    return out


def average_linkage(unit: np.ndarray, cosine: float) -> list[int]:
    """Average-linkage clustering on cosine distance, merged while under 1 - cosine."""
    n = len(unit)
    if n <= 1:
        return [0] * n
    threshold = 1 - cosine
    distance = 1 - unit @ unit.T
    np.fill_diagonal(distance, np.inf)
    size = np.ones(n)
    alive = np.ones(n, bool)
    member = np.arange(n)
    while True:
        masked = np.where(alive[:, None] & alive[None, :], distance, np.inf)
        a, b = np.unravel_index(np.argmin(masked), masked.shape)
        if not masked[a, b] < threshold:
            break
        a, b = min(a, b), max(a, b)
        merged = (size[a] * distance[a] + size[b] * distance[b]) / (size[a] + size[b])
        distance[a, :] = merged
        distance[:, a] = merged
        distance[a, a] = np.inf
        size[a] += size[b]
        alive[b] = False
        member[member == b] = a
    numbered: dict[int, int] = {}
    return [numbered.setdefault(int(m), len(numbered)) for m in member]


def _nearest(turns: list[Turn], candidates: list[list[Turn]], lanes: list[int]) -> int:
    """Of the voiced lanes, the one nearest `turns` in time (an overlap counts as no gap, the
    most overlap decides among equals, the first wins a tie)."""
    best, best_gap, best_overlap = lanes[0], np.inf, -np.inf
    for candidate, lane in zip(candidates, lanes, strict=True):
        gap, overlap = np.inf, 0.0
        for a in turns:
            for b in candidate:
                shared = min(a.end, b.end) - max(a.start, b.start)
                gap = min(gap, max(0.0, -shared))
                overlap += max(0.0, shared)
        if gap < best_gap or (gap == best_gap and overlap > best_overlap):
            best, best_gap, best_overlap = lane, gap, overlap
    return best


def voice_windows(
    frames: int, width: int, margin: int, per_column: int
) -> list[tuple[int, int, int, int]]:
    """(start, keep_low, keep_high, place_low) for each voice-graph window over `frames`."""
    columns = frames // per_column
    if frames <= width:
        return [(0, 0, columns, 0)]
    out, kept, start = [], 0, 0
    while kept < columns:
        last = start + width >= frames
        if last:
            start = frames - width
        end = columns if last else (start + width - margin) // per_column
        out.append((start, kept - start // per_column, end - start // per_column, kept))
        kept = end
        start += width - 2 * margin
    return out


def column_mask(solo: np.ndarray, offset: int, columns: int, per_column: int) -> np.ndarray:
    """A column is the lane's when at least half its frames are solo frames of the lane."""
    padded = np.zeros(columns * per_column, bool)
    a = max(offset, 0)
    b = min(offset + len(solo), len(padded))
    if a < b:
        padded[a:b] = solo[a - offset : b - offset] > 0
    return 2 * padded.reshape(columns, per_column).sum(axis=1) >= per_column


@dataclass
class Lane:
    turns: list[Turn]
    solo: np.ndarray
    offset: int


# ---------------------------------------------------------------- the model


class WhoModel:
    def __init__(self, files: list[Path], threads: int | None = None):
        import onnxruntime as ort

        by_name = {p.name: p for p in files}
        self.meta: dict[str, Any] = json.loads(by_name["who_meta.json"].read_text())
        meta = self.meta
        if meta.get("schema") != 2 or meta["model"]["architecture"] != "eend_m2f":
            raise RuntimeError("Unsupported Who model metadata")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads or min(os.cpu_count() or 1, 8)
        self._sessions: dict[str, Any] = {}

        def session(name: str) -> Any:
            if name not in self._sessions:
                self._sessions[name] = ort.InferenceSession(
                    str(by_name[name]), options, providers=["CPUExecutionProvider"]
                )
            return self._sessions[name]

        self._session = session
        self.windows = sorted(meta["windows"], key=lambda w: w["frames"])
        self.frontend = Frontend.create(meta["frontend"], by_name["who_mel_banks.f32"])
        voice = meta["voice"]
        self.voice_frontend = Frontend.create(voice["frontend"], by_name["who_voice_banks.f32"])
        raw = by_name["who_embed.f16"].read_bytes()
        out, inner = struct.unpack_from("<II", raw)
        values = np.frombuffer(raw, dtype="<f2", offset=8).astype(np.float32)
        if len(values) != out * inner + out:
            raise RuntimeError("embedding sidecar does not match its header")
        self.embed_weight = values[: out * inner].reshape(out, inner)
        self.embed_bias = values[out * inner :]
        self.columns = inner // 2

    # one piece through the encoder and query graphs
    def _logits(self, audio, piece: tuple[int, int], means) -> tuple[np.ndarray, np.ndarray]:
        first, end = piece
        count = end - first
        window = next((w for w in self.windows if w["frames"] >= count), self.windows[-1])
        mel = self.frontend.features(audio, first, count, means)
        padded = np.empty((window["frames"], self.frontend.mels), np.float32)
        padded[:count] = mel
        padded[count:] = mel[-1]
        enc = self._session(window["encoder"]["compiled"].split("/")[-1])
        memory, frames = enc.run(
            window["encoder"]["outputs"], {window["encoder"]["inputs"][0]: padded[None]}
        )
        dim = self.meta["model"]["dim"]
        feeds = {window["queries"]["inputs"][0]: memory.reshape(1, window["low"], dim)}
        at = 0
        frames = frames.reshape(window["frames"], dim)
        for name, chunk in zip(window["queries"]["inputs"][1:], window["chunks"], strict=True):
            feeds[name] = frames[None, at : at + chunk]
            at += chunk
        queries = self._session(window["queries"]["compiled"].split("/")[-1])
        out = queries.run(window["queries"]["outputs"], feeds)
        n = self.meta["model"]["queries"]
        masks = np.concatenate(
            [o.reshape(n, chunk) for o, chunk in zip(out[2:], window["chunks"], strict=True)],
            axis=1,
        )
        return sigmoid(out[0].reshape(n)), sigmoid(masks[:, :count])

    def _embed(self, total: np.ndarray, squares: np.ndarray, n: int) -> np.ndarray | None:
        if n < 2:
            return None
        mean = total / n
        std = np.sqrt(np.maximum((squares - n * mean * mean) / (n - 1), 0))
        v = self.embed_bias + self.embed_weight @ np.r_[mean, std].astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-8)

    def diarize(self, audio: np.ndarray) -> tuple[list[Turn], float]:
        meta = self.meta
        step = meta["frames"]["step_s"]
        centre = meta["frames"]["first_centre_s"]
        decision = meta["decision"]
        seconds = len(audio) / SAMPLE_RATE
        means, total = self.frontend.means(audio)
        if total == 0:  # shorter than one 25 ms frame: nothing to label
            return [], seconds
        longest = self.windows[-1]["frames"]
        pieces = [(a, min(a + longest, total)) for a in range(0, total, longest)] or [(0, total)]

        lanes: list[Lane] = []
        for index, piece in enumerate(pieces):
            presence, masks = self._logits(audio, piece, means)
            stretches = _stretches(presence, masks, decision)
            offset = piece[0] * step
            queries = sorted({q for q, _, _ in stretches})
            if len(pieces) == 1:
                turns = [Turn(*_bounds(a, b, step, centre), q) for q, a, b in stretches]
                return number_by_appearance(turns), seconds
            on = masks[queries] > decision["mask_threshold"] if queries else np.zeros((0, 0), bool)
            for row, query in enumerate(queries):
                solo = (on[row] & (on.sum(axis=0) == 1)).astype(np.float32)
                turns = []
                for q, a, b in stretches:
                    if q == query:
                        s, e = _bounds(a, b, step, centre)
                        turns.append(
                            Turn(s + offset, e + offset, index * meta["model"]["queries"] + q)
                        )
                lanes.append(Lane(turns, solo, piece[0]))

        if not lanes:  # a long recording with no speech at all
            return [], seconds
        labels = self._join(lanes, audio, total)
        turns = [
            Turn(t.start, t.end, label)
            for lane, label in zip(lanes, labels, strict=True)
            for t in lane.turns
        ]
        return number_by_appearance(join_touching(turns)), seconds

    def _join(self, lanes: list[Lane], audio: np.ndarray, mel_frames: int) -> list[int]:
        meta = self.meta
        voice, join = meta["voice"], meta["join"]
        per = voice["mel_frames_per_column"]
        voice_means, voice_total = self.voice_frontend.means(audio)
        used = min(voice_total, mel_frames) // per * per
        columns = used // per
        minimum = round(join["min_solo_s"] / meta["frames"]["step_s"])
        masks = [
            column_mask(lane.solo, lane.offset, columns, per)
            if lane.solo.sum() >= minimum
            else None
            for lane in lanes
        ]
        sums = [None if m is None else np.zeros(self.columns) for m in masks]
        squares = [None if m is None else np.zeros(self.columns) for m in masks]
        counts = [0] * len(lanes)
        width, mels = voice["mel_frames"], self.voice_frontend.mels
        windows = (
            voice_windows(used, width, voice["margin_mel_frames"], per)
            if any(m is not None for m in masks)  # no lane has a voice: skip the voice graph
            else []
        )
        session = self._session(voice["compiled"].split("/")[-1]) if windows else None
        for start, low, high, place in windows:
            available = min(width, used - start)
            feed = np.zeros((width, mels), np.float32)
            feed[:available] = self.voice_frontend.features(audio, start, available, voice_means)
            out = session.run(voice["outputs"], {voice["inputs"][0]: feed[None]})[0]
            out = out.reshape(width // per, self.columns).astype(np.float64)
            rows = np.arange(low, high)
            cols = place + (rows - low)
            for g, mask in enumerate(masks):
                if mask is None:
                    continue
                picked = out[rows[mask[cols]]]
                sums[g] += picked.sum(axis=0)
                squares[g] += (picked**2).sum(axis=0)
                counts[g] += len(picked)

        voices, voiced = [], []
        for g in range(len(lanes)):
            if (
                masks[g] is not None
                and (v := self._embed(sums[g], squares[g], counts[g])) is not None
            ):
                voices.append(v)
                voiced.append(g)
        labels = [-1] * len(lanes)
        clustered = average_linkage(
            np.array(voices, np.float32) if voices else np.zeros((0, 1), np.float32),
            join["cosine"],
        )
        for g, label in zip(voiced, clustered, strict=True):
            labels[g] = label
        if join.get("voiceless") == "fold" and voiced:
            for g in range(len(lanes)):
                if labels[g] < 0:
                    labels[g] = labels[
                        _nearest(lanes[g].turns, [lanes[v].turns for v in voiced], voiced)
                    ]
            numbered: dict[int, int] = {}
            return [numbered.setdefault(label, len(numbered)) for label in labels]
        nxt = max(clustered, default=-1) + 1
        for g in range(len(lanes)):
            if labels[g] < 0:
                labels[g], nxt = nxt, nxt + 1
        return labels


# ---------------------------------------------------------------- diarizer


def exclusive(turns: list[Turn]) -> list[Turn]:
    """Non-overlapping turns: where speakers overlap, the one whose turn began first keeps the
    floor, so a short interjection never takes words from the person talking."""
    turns = join_touching(turns)
    cuts = sorted({t.start for t in turns} | {t.end for t in turns})
    out: list[Turn] = []
    for a, b in zip(cuts[:-1], cuts[1:], strict=True):
        active = [t for t in turns if t.start <= a and t.end >= b]
        if not active:
            continue
        who = min(active, key=lambda t: (t.start, t.label))
        if out and out[-1].label == who.label and out[-1].end >= a - 1e-9:
            out[-1] = Turn(out[-1].start, b, who.label)
        else:
            out.append(Turn(a, b, who.label))
    return out


class WhoDiarizer(Diarizer):
    name = "who"

    def __init__(self, cfg: DiarizationConfig):
        self.cfg = cfg
        self._model: WhoModel | None = None
        # Who has no general embedding; voiceprints stay in Pyannote's space.
        self.voice = PyannoteDiarizer(device=cfg.device, token_env=cfg.hf_token_env)

    @property
    def model_id(self) -> str:
        return f"who:{REVISION[:8]}"

    @property
    def embedding_id(self) -> str:
        return self.voice.embedding_id

    def _load(self) -> WhoModel:
        if self._model is None:
            try:
                import onnxruntime  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "onnxruntime is not installed. Run: pip install -e '.[who]'"
                ) from exc
            # Load cached files directly: the Hub lookup stalls or fails when working offline.
            self._model = WhoModel(_cached() or download())
        return self._model

    def diarize(
        self,
        audio: Audio,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[SpeakerSegment]:
        if audio.sample_rate != SAMPLE_RATE:
            raise ValueError(f"Who needs {SAMPLE_RATE} Hz audio, got {audio.sample_rate} Hz")
        if len(audio.samples) < FRAME_SAMPLES:
            return []
        turns, _ = self._load().diarize(np.asarray(audio.samples, dtype=np.float32))
        limit = num_speakers or max_speakers
        if limit:
            share: dict[int, float] = {}
            for t in turns:
                share[t.label] = share.get(t.label, 0.0) + t.end - t.start
            keep = set(sorted(share, key=share.__getitem__)[-limit:])
            turns = [t for t in turns if t.label in keep]
        return [
            SpeakerSegment(t.start, min(t.end, audio.duration), f"SPEAKER_{t.label:02d}")
            for t in exclusive(turns)
            if t.start < audio.duration
        ]

    def embed(self, waveforms: list[np.ndarray], sample_rate: int) -> np.ndarray:
        return self.voice.embed(waveforms, sample_rate)
