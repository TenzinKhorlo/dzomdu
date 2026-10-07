"""Voiceprint library in SQLite.

Embeddings are biometric data: they live in the app data directory (never in the vault),
alongside short reference clips so everyone can be re-embedded if the model changes.
"""

from __future__ import annotations

import functools
import shutil
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS speakers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    consent     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    id          INTEGER PRIMARY KEY,
    speaker_id  INTEGER NOT NULL REFERENCES speakers(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    source      TEXT,
    clip_path   TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model, speaker_id);
-- Every review decision, used later to calibrate thresholds.
CREATE TABLE IF NOT EXISTS feedback (
    id                  INTEGER PRIMARY KEY,
    meeting_id          TEXT NOT NULL,
    cluster             TEXT NOT NULL,
    model               TEXT NOT NULL,
    predicted_speaker   INTEGER,
    predicted_score     REAL,
    predicted_status    TEXT,
    final_speaker       INTEGER,
    created_at          TEXT NOT NULL
);
"""


F = TypeVar("F", bound=Callable)


def _locked(method: F) -> F:
    """The web UI and the model worker use the store from different threads."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Speaker:
    id: int
    name: str
    consent: bool
    samples: int = 0


class VoiceprintStore:
    def __init__(self, db_path: Path, clips_dir: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clips_dir = clips_dir
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    @_locked
    def close(self) -> None:
        self.conn.close()

    # -- speakers ---------------------------------------------------------------------------

    @_locked
    def get(self, name: str) -> Speaker | None:
        row = self.conn.execute(
            "SELECT id, name, consent FROM speakers WHERE name = ?", (name.strip(),)
        ).fetchone()
        return Speaker(row["id"], row["name"], bool(row["consent"])) if row else None

    @_locked
    def get_by_id(self, speaker_id: int) -> Speaker | None:
        row = self.conn.execute(
            "SELECT id, name, consent FROM speakers WHERE id = ?", (speaker_id,)
        ).fetchone()
        return Speaker(row["id"], row["name"], bool(row["consent"])) if row else None

    @_locked
    def get_or_create(self, name: str, consent: bool = False) -> Speaker:
        name = name.strip()
        if not name:
            raise ValueError("Speaker name cannot be empty")
        if existing := self.get(name):
            if consent and not existing.consent:
                self.set_consent(existing.id, True)
                existing.consent = True
            return existing
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO speakers (name, consent, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, int(consent), now, now),
            )
        return Speaker(int(cur.lastrowid), name, consent)

    @_locked
    def set_consent(self, speaker_id: int, consent: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE speakers SET consent = ?, updated_at = ? WHERE id = ?",
                (int(consent), _now(), speaker_id),
            )

    @_locked
    def list(self, model: str | None = None) -> list[Speaker]:
        sql = """
            SELECT s.id, s.name, s.consent, COUNT(e.id) AS n
            FROM speakers s LEFT JOIN embeddings e
              ON e.speaker_id = s.id AND (? IS NULL OR e.model = ?)
            GROUP BY s.id ORDER BY s.name COLLATE NOCASE
        """
        rows = self.conn.execute(sql, (model, model)).fetchall()
        return [Speaker(r["id"], r["name"], bool(r["consent"]), r["n"]) for r in rows]

    @_locked
    def rename(self, old: str, new: str) -> None:
        speaker = self.get(old)
        if speaker is None:
            raise KeyError(old)
        if (other := self.get(new)) and other.id != speaker.id:
            raise ValueError(f"A speaker called {new!r} already exists")
        with self.conn:
            self.conn.execute(
                "UPDATE speakers SET name = ?, updated_at = ? WHERE id = ?",
                (new.strip(), _now(), speaker.id),
            )

    @_locked
    def forget(self, name: str) -> bool:
        """Delete a person's voiceprints and reference clips ("forget this voice")."""
        speaker = self.get(name)
        if speaker is None:
            return False
        with self.conn:
            self.conn.execute("DELETE FROM speakers WHERE id = ?", (speaker.id,))
            self.conn.execute(
                "UPDATE feedback SET predicted_speaker = NULL WHERE predicted_speaker = ?",
                (speaker.id,),
            )
            self.conn.execute(
                "UPDATE feedback SET final_speaker = NULL WHERE final_speaker = ?", (speaker.id,)
            )
        shutil.rmtree(self.clips_dir / str(speaker.id), ignore_errors=True)
        return True

    # -- embeddings -------------------------------------------------------------------------

    @_locked
    def add_embedding(
        self,
        speaker_id: int,
        model: str,
        vector: np.ndarray,
        source: str | None = None,
        clip_path: Path | None = None,
        max_per_speaker: int = 20,
    ) -> int:
        vec = np.asarray(vector, dtype=np.float32).ravel()
        if not np.all(np.isfinite(vec)):
            raise ValueError("Embedding contains NaN/inf")
        vec = vec / np.linalg.norm(vec)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO embeddings (speaker_id, model, dim, vector, source, clip_path,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    speaker_id,
                    model,
                    vec.size,
                    vec.tobytes(),
                    source,
                    str(clip_path) if clip_path else None,
                    _now(),
                ),
            )
        self._prune(speaker_id, model, max_per_speaker)
        return int(cur.lastrowid)

    def _prune(self, speaker_id: int, model: str, keep: int) -> None:
        """Keep at most `keep` embeddings, dropping the most redundant ones so the set stays
        diverse (different rooms, mics, days)."""
        rows = self.conn.execute(
            "SELECT id, vector, clip_path FROM embeddings WHERE speaker_id = ? AND model = ?"
            " ORDER BY id",
            (speaker_id, model),
        ).fetchall()
        if len(rows) <= keep:
            return
        ids = [r["id"] for r in rows]
        clips = {r["id"]: r["clip_path"] for r in rows}
        mat = np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        sims = mat @ mat.T
        np.fill_diagonal(sims, np.nan)
        alive = list(range(len(ids)))
        newest = len(ids) - 1  # never drop the sample we just added
        while len(alive) > keep:
            sub = sims[np.ix_(alive, alive)]
            redundancy = np.nanmean(sub, axis=1)
            order = np.argsort(-redundancy)
            victim = next(alive[k] for k in order if alive[k] != newest)
            alive.remove(victim)
        dropped = [ids[i] for i in range(len(ids)) if i not in alive]
        with self.conn:
            self.conn.executemany("DELETE FROM embeddings WHERE id = ?", [(i,) for i in dropped])
        for emb_id in dropped:
            if clips[emb_id]:
                Path(clips[emb_id]).unlink(missing_ok=True)

    @_locked
    def embeddings(self, model: str, speaker_ids: list[int] | None = None) -> dict[int, np.ndarray]:
        """speaker_id -> (k, dim) matrix of that speaker's embeddings in `model`'s space."""
        sql = "SELECT speaker_id, vector FROM embeddings WHERE model = ?"
        params: list[object] = [model]
        if speaker_ids is not None:
            if not speaker_ids:
                return {}
            sql += f" AND speaker_id IN ({','.join('?' * len(speaker_ids))})"
            params += speaker_ids
        out: dict[int, list[np.ndarray]] = {}
        for row in self.conn.execute(sql + " ORDER BY id", params):
            out.setdefault(row["speaker_id"], []).append(
                np.frombuffer(row["vector"], dtype=np.float32)
            )
        return {k: np.stack(v) for k, v in out.items()}

    def clip_path_for(self, speaker_id: int, tag: str) -> Path:
        path = self.clips_dir / str(speaker_id) / f"{tag}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # -- feedback ---------------------------------------------------------------------------

    @_locked
    def log_feedback(
        self,
        meeting_id: str,
        cluster: str,
        model: str,
        predicted_speaker: int | None,
        predicted_score: float | None,
        predicted_status: str,
        final_speaker: int | None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO feedback (meeting_id, cluster, model, predicted_speaker,"
                " predicted_score, predicted_status, final_speaker, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    meeting_id,
                    cluster,
                    model,
                    predicted_speaker,
                    predicted_score,
                    predicted_status,
                    final_speaker,
                    _now(),
                ),
            )
