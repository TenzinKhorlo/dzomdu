"""Evaluation metrics, implemented with numpy only."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ..models import SpeakerSegment

# -- WER --------------------------------------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s']")


def normalize_text(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    text = _PUNCT.sub(" ", text)
    return text.split()


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    """Word-level Levenshtein distance, vectorised per row (fast enough for hour-long
    transcripts)."""
    if not ref:
        return len(hyp)
    if not hyp:
        return len(ref)
    vocab: dict[str, int] = {}
    r = np.array([vocab.setdefault(w, len(vocab)) for w in ref])
    h = np.array([vocab.setdefault(w, len(vocab)) for w in hyp])
    m = len(h)
    idx = np.arange(m + 1)
    prev = idx.copy()
    for i in range(1, len(r) + 1):
        cur = np.empty(m + 1, dtype=np.int64)
        cur[0] = i
        # substitution/match and deletion
        cur[1:] = np.minimum(prev[:-1] + (h != r[i - 1]), prev[1:] + 1)
        # insertion: cur[j] = min_k<=j (cur[k] + j - k)  ->  running minimum
        cur = np.minimum.accumulate(cur - idx) + idx
        prev = cur
    return int(prev[-1])


def wer(reference: str, hypothesis: str) -> tuple[float, int, int]:
    """Returns (WER, errors, reference word count)."""
    ref, hyp = normalize_text(reference), normalize_text(hypothesis)
    errors = edit_distance(ref, hyp)
    return (errors / len(ref) if ref else float(bool(hyp))), errors, len(ref)


# -- DER --------------------------------------------------------------------------------------


@dataclass
class DERResult:
    der: float
    missed: float
    false_alarm: float
    confusion: float
    total: float  # seconds of reference speech (scored)
    mapping: dict[str, str]


def _frames(segments: list[SpeakerSegment], labels: list[str], n: int, step: float) -> np.ndarray:
    mat = np.zeros((len(labels), n), dtype=bool)
    index = {lab: i for i, lab in enumerate(labels)}
    for s in segments:
        a, b = int(round(s.start / step)), int(round(s.end / step))
        mat[index[s.speaker], max(0, a) : min(n, b)] = True
    return mat


def _assign(cost: np.ndarray) -> list[tuple[int, int]]:
    """Maximise total overlap; uses scipy if available, otherwise greedy."""
    try:
        from scipy.optimize import linear_sum_assignment

        rows, cols = linear_sum_assignment(-cost)
        return list(zip(rows.tolist(), cols.tolist(), strict=True))
    except ImportError:
        pairs = sorted(np.ndindex(cost.shape), key=lambda rc: -cost[rc])
        used_r: set[int] = set()
        used_c: set[int] = set()
        out = []
        for r, c in pairs:
            if r not in used_r and c not in used_c:
                out.append((r, c))
                used_r.add(r)
                used_c.add(c)
        return out


def der(
    reference: list[SpeakerSegment],
    hypothesis: list[SpeakerSegment],
    collar: float = 0.25,
    step: float = 0.01,
) -> DERResult:
    """Diarization error rate with an optimal one-to-one speaker mapping. Frames within
    `collar` seconds of a reference boundary are not scored (standard practice)."""
    end = max([s.end for s in reference + hypothesis] + [0.0])
    n = int(np.ceil(end / step)) + 1
    ref_labels = sorted({s.speaker for s in reference})
    hyp_labels = sorted({s.speaker for s in hypothesis})
    ref = _frames(reference, ref_labels, n, step)
    hyp = _frames(hypothesis, hyp_labels, n, step)

    scored = np.ones(n, dtype=bool)
    c = int(round(collar / step))
    if c:
        for s in reference:
            for t in (s.start, s.end):
                k = int(round(t / step))
                scored[max(0, k - c) : min(n, k + c)] = False
    ref, hyp = ref[:, scored], hyp[:, scored]

    mapping: dict[str, str] = {}
    n_correct = np.zeros(ref.shape[1])
    if ref_labels and hyp_labels:
        overlap = ref.astype(np.int32) @ hyp.T.astype(np.int32)
        for r, h in _assign(overlap.astype(float)):
            mapping[hyp_labels[h]] = ref_labels[r]
            n_correct += ref[r] & hyp[h]
    n_ref = ref.sum(axis=0)
    n_hyp = hyp.sum(axis=0)
    missed = np.maximum(0, n_ref - n_hyp).sum() * step
    fa = np.maximum(0, n_hyp - n_ref).sum() * step
    conf = (np.minimum(n_ref, n_hyp) - n_correct).sum() * step
    total = n_ref.sum() * step
    return DERResult(
        der=float((missed + fa + conf) / total) if total else 0.0,
        missed=float(missed),
        false_alarm=float(fa),
        confusion=float(conf),
        total=float(total),
        mapping=mapping,
    )


# -- speaker verification ---------------------------------------------------------------------


@dataclass
class VerificationResult:
    eer: float
    eer_threshold: float
    threshold_far_1pct: float  # lowest threshold with <= 1% false accepts
    frr_at_far_1pct: float
    genuine_mean: float
    impostor_mean: float
    n_genuine: int
    n_impostor: int


def verification(genuine: np.ndarray, impostor: np.ndarray) -> VerificationResult:
    genuine = np.sort(np.asarray(genuine, dtype=float))
    impostor = np.sort(np.asarray(impostor, dtype=float))
    thresholds = np.unique(np.concatenate([genuine, impostor]))
    # FAR(t) = P(impostor >= t), FRR(t) = P(genuine < t)
    far = 1.0 - np.searchsorted(impostor, thresholds, side="left") / max(len(impostor), 1)
    frr = np.searchsorted(genuine, thresholds, side="left") / max(len(genuine), 1)
    i = int(np.argmin(np.abs(far - frr)))
    ok = np.nonzero(far <= 0.01)[0]
    j = int(ok[0]) if len(ok) else len(thresholds) - 1
    return VerificationResult(
        eer=float((far[i] + frr[i]) / 2),
        eer_threshold=float(thresholds[i]),
        threshold_far_1pct=float(thresholds[j]),
        frr_at_far_1pct=float(frr[j]),
        genuine_mean=float(genuine.mean()) if len(genuine) else float("nan"),
        impostor_mean=float(impostor.mean()) if len(impostor) else float("nan"),
        n_genuine=len(genuine),
        n_impostor=len(impostor),
    )
