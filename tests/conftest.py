"""Test doubles: synthetic meetings where each "person" is a tone at their own pitch.

The fake diarizer's embedding is derived from the dominant frequency of the audio, so the same
person produces similar voiceprints across different recordings, just like a real model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
import pytest

from dzomdu.asr import ASRBackend
from dzomdu.audio import SAMPLE_RATE, Audio, write_wav
from dzomdu.config import Config, LLMConfig
from dzomdu.diarize import Diarizer, l2_normalize
from dzomdu.llm.client import LLMClient
from dzomdu.models import SpeakerSegment, Word

PITCH = {"Alice": 220.0, "Bob": 440.0, "Carol": 660.0, "Dawa": 880.0}


def make_meeting(
    path: Path, script: list[tuple[str, float, float, str]], seed: int = 0
) -> tuple[list[SpeakerSegment], list[Word]]:
    """script: (person, start, end, text). Writes a WAV and returns the ground truth with
    anonymous labels in order of first appearance."""
    rng = np.random.default_rng(seed)
    end = max(e for _, _, e, _ in script) + 0.4
    samples = rng.normal(0, 0.002, int(end * SAMPLE_RATE)).astype(np.float32)
    labels: dict[str, str] = {}
    segments, words = [], []
    for person, start, stop, text in script:
        label = labels.setdefault(person, f"SPEAKER_{len(labels):02d}")
        t = np.arange(int((stop - start) * SAMPLE_RATE)) / SAMPLE_RATE
        a = int(start * SAMPLE_RATE)
        samples[a : a + len(t)] += 0.3 * np.sin(2 * np.pi * PITCH[person] * t).astype(np.float32)
        segments.append(SpeakerSegment(start, stop, label))
        toks = text.split()
        step = (stop - start) / len(toks)
        for i, tok in enumerate(toks):
            words.append(Word(tok, round(start + i * step, 3), round(start + (i + 0.8) * step, 3)))
    write_wav(path, samples)
    return segments, words


class FakeASR(ASRBackend):
    name = "fake"

    def __init__(self, words_by_duration: dict[int, list[Word]] | None = None):
        self.words_by_duration = words_by_duration or {}
        self.calls = 0

    @property
    def model_id(self) -> str:
        return "fake-asr"

    def transcribe(self, audio: Audio) -> list[Word]:
        self.calls += 1
        return self.words_by_duration[round(audio.duration)]


class FakeDiarizer(Diarizer):
    name = "fake"

    def __init__(self, segments_by_duration: dict[int, list[SpeakerSegment]] | None = None):
        self.segments_by_duration = segments_by_duration or {}
        self.calls = 0

    @property
    def model_id(self) -> str:
        return "fake-diarizer"

    def diarize(self, audio, num_speakers=None, min_speakers=None, max_speakers=None):
        self.calls += 1
        return self.segments_by_duration[round(audio.duration)]

    def embed(self, waveforms, sample_rate):
        rows = []
        bins = np.arange(32)
        for wav in waveforms:
            if len(wav) < sample_rate // 4:
                rows.append(np.full(32, np.nan))
                continue
            spectrum = np.abs(np.fft.rfft(wav))
            freq = np.argmax(spectrum) * sample_rate / len(wav)
            rows.append(np.exp(-((bins - freq / 50.0) ** 2) / 2.0) + 0.01)
        return l2_normalize(np.array(rows, dtype=np.float32))


def notes_reply(turn_ids: list[str]) -> dict:
    first, last = turn_ids[0], turn_ids[-1]
    return {
        "title": "Budget review",
        "summary": "The team reviewed the survey budget.",
        "topics": [{"title": "Budget", "points": ["Costs were reviewed"], "source_turns": [first]}],
        "decisions": [{"decision": "Proceed with the survey", "source_turns": [last, "t999"]}],
        "action_items": [
            {
                "task": "Draft the budget",
                "owner": "Bob",
                "due": "2026-10-14",
                "source_turns": [last],
            },
            {
                "task": "Book the venue",
                "owner": "Someone else",
                "due": "next week",
                "source_turns": [],
            },
        ],
        "open_questions": ["Who approves the final budget?"],
        "next_meeting": None,
    }


def ollama_transport(
    reply: Callable[[dict], dict] | None = None, log: list[dict] | None = None
) -> httpx.MockTransport:
    """An Ollama /api/chat stand-in that answers with notes citing real turn ids."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if log is not None:
            log.append(payload)
        prompt = payload["messages"][-1]["content"]
        ids = [tok[1:] for tok in prompt.split() if tok.startswith("[t")]
        body = reply(payload) if reply else notes_reply(ids or ["t1"])
        return httpx.Response(200, json={"message": {"content": json.dumps(body)}})

    return httpx.MockTransport(handler)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(vault=tmp_path / "vault", data_dir=tmp_path / "data")


@pytest.fixture
def fake_llm() -> LLMClient:
    return LLMClient(LLMConfig(model="test-model"), http=httpx.Client(transport=ollama_transport()))
