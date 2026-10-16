"""Meeting sessions behind the web UI.

A session moves through: recording -> processing -> review -> summarizing -> done
(or error / cancelled). All model work runs on ONE worker thread, in order, so the speech,
speaker and LLM models never compete for memory and are only touched from one thread.
"""

from __future__ import annotations

import re
import secrets
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from ..align import assign_speakers, build_turns
from ..audio import SAMPLE_RATE, Audio, write_wav
from ..config import Config
from ..live import LiveSpeakerTracker, LiveTranscriber
from ..llm.client import LLMError
from ..models import SpeakerAssignment, SpeakerSegment
from ..noise import NoiseSuppressor
from ..pipeline import Analysis, Pipeline
from ..speakers.matching import cluster_voices
from ..transcript import LiveSpeakerEdit, TranscriptConflict, clean_name

ACTIVE_STATES = {"recording", "processing", "summarizing"}


@dataclass
class SessionMeta:
    title: str | None = None
    project: str | None = None
    attendees: list[str] = field(default_factory=list)
    template: str | None = None
    instructions: str = ""
    num_speakers: int | None = None
    live: bool = True
    summarize: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMeta:
        def text(key: str) -> str | None:
            value = data.get(key)
            return str(value).strip() or None if value is not None else None

        attendees = data.get("attendees") or []
        if isinstance(attendees, str):
            attendees = attendees.split(",")
        num = data.get("num_speakers")
        return cls(
            title=text("title"),
            project=text("project"),
            attendees=[a.strip() for a in attendees if str(a).strip()],
            template=text("template"),
            instructions=text("instructions") or "",
            num_speakers=int(num) if num not in (None, "", 0, "0") else None,
            live=bool(data.get("live", True)),
            summarize=bool(data.get("summarize", True)),
        )


class Session:
    def __init__(self, sid: str, meta: SessionMeta, kind: str):
        self.id = sid
        self.meta = meta
        self.kind = kind  # recording | upload | existing
        self.state = "new"
        self.messages: list[str] = []
        self.error: str | None = None
        self.warning: str | None = None
        self.live_segments: list[dict[str, Any]] = []
        self.live_rev = 0  # bumped on every change, so clients can fetch only what changed
        self._live_index: dict[int, int] = {}  # segment id → position in live_segments
        self.live_names: dict[str, str] = {}
        self.live_overrides: dict[int, str] = {}
        self.created = datetime.now()
        self.started_at: datetime | None = None
        self.audio_path: Path | None = None
        self.samples = 0
        self.analysis: Analysis | None = None
        self.record = None
        self.note_path: Path | None = None
        self.cancelled = False
        self._pcm: BinaryIO | None = None
        self._live: LiveTranscriber | None = None
        self.lock = threading.Lock()

    def put_live(self, seg: dict[str, Any]) -> None:
        """Add a live segment, or replace an earlier version of it (same id)."""
        with self.lock:
            key = seg.get("speaker")
            seg = seg | {"speaker_key": key}
            self._store_live(seg)

    def _store_live(self, seg: dict[str, Any]) -> None:
        """Called under the session lock; late model results cannot overwrite human labels."""
        self.live_rev += 1
        key = seg.get("speaker_key")
        seg = seg | {
            "speaker": self.live_overrides.get(seg["id"], self.live_names.get(key, key)),
            "corrected": seg["id"] in self.live_overrides or key in self.live_names,
            "rev": self.live_rev,
        }
        i = self._live_index.get(seg["id"])
        if i is None:
            self._live_index[seg["id"]] = len(self.live_segments)
            self.live_segments.append(seg)
        else:
            self.live_segments[i] = seg

    def edit_live(self, edit: LiveSpeakerEdit) -> None:
        name = clean_name(edit.name)
        with self.lock:
            if self.state != "recording":
                raise TranscriptConflict("Live corrections are available while recording")
            if any(sid not in self._live_index for sid in edit.segment_ids):
                raise ValueError("This transcript segment no longer exists")
            selected = [self.live_segments[self._live_index[sid]] for sid in edit.segment_ids]
            if any(seg.get("partial") or not seg.get("text") for seg in selected):
                raise TranscriptConflict("Wait for this sentence to finish before assigning it")
            if any(
                seg["id"] in edit.revisions and edit.revisions[seg["id"]] != seg["rev"]
                for seg in selected
            ):
                raise TranscriptConflict("This sentence was updated. Try the correction again.")
            if edit.rename_speaker:
                if len(selected) != 1 or not selected[0].get("speaker"):
                    raise ValueError("Choose one labelled speaker to rename")
                old = selected[0]["speaker"]
                keys = {key for key, value in self.live_names.items() if value == old} | {
                    seg["speaker_key"] for seg in self.live_segments
                    if seg.get("speaker_key") and seg["id"] not in self.live_overrides
                    and seg.get("speaker") == old
                }
                for key in keys:
                    self.live_names[key] = name
                for sid, previous in list(self.live_overrides.items()):
                    if previous == old:
                        self.live_overrides[sid] = name
                changed = [seg for seg in self.live_segments if seg.get("speaker") == old]
                # Preserve an explicit human assignment even if a late model changes its
                # provisional cluster key. Future utterances still use the voice-name map.
                for seg in changed:
                    self.live_overrides[seg["id"]] = name
            else:
                for seg in selected:
                    self.live_overrides[seg["id"]] = name
                changed = selected
            for seg in changed:
                self._store_live(seg)

    def log(self, message: str) -> None:
        with self.lock:
            if not self.messages or self.messages[-1] != message:
                self.messages.append(message)

    @property
    def elapsed(self) -> float:
        return self.samples / SAMPLE_RATE


class SessionManager:
    def __init__(self, cfg: Config, pipeline: Pipeline):
        self.cfg = cfg
        self.pipeline = pipeline
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dzomdu-models")
        self.sessions: dict[str, Session] = {}
        self.recordings_dir = cfg.data_dir / "recordings"
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.recovered = self._recover_orphans()
        self._warm: Future[Any] | None = None

    def warm_up(self) -> None:
        """Load the speech and voice models in the background, so the first words of a
        recording are transcribed straight away instead of waiting for models to load."""
        w = self._warm
        if w is not None and not (w.done() and (w.cancelled() or w.exception() is not None)):
            return  # loading, or already loaded (a failed attempt is retried)
        self._warm = self.submit(self._warm_job)

    def _warm_job(self) -> None:
        work = self.cfg.cache_dir / "live"
        work.mkdir(parents=True, exist_ok=True)
        path = work / "warm-up.wav"
        quiet = np.random.default_rng(0).normal(0, 0.003, SAMPLE_RATE * 2).astype(np.float32)
        try:
            write_wav(path, quiet, SAMPLE_RATE)
            self.pipeline.asr.transcribe(Audio(quiet, SAMPLE_RATE, path))
        finally:
            path.unlink(missing_ok=True)
        try:
            self.pipeline.diarizer.embed([quiet], SAMPLE_RATE)
        except Exception:  # live labels are optional; recording reports the problem itself
            pass

    def shutdown(self) -> None:
        self.worker.shutdown(wait=False, cancel_futures=True)

    def get(self, sid: str) -> Session:
        return self.sessions[sid]

    def create(self, meta: SessionMeta, kind: str) -> Session:
        sid = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
        session = Session(sid, meta, kind)
        self.sessions[sid] = session
        return session

    def submit(self, fn) -> Future[Any]:
        return self.worker.submit(fn)

    # -- recording --------------------------------------------------------------------------

    def start_recording(self, s: Session) -> None:
        if s.state != "new":
            raise ValueError(f"Session is {s.state}")
        s.audio_path = self.recordings_dir / f"{s.id}.pcm"
        s._pcm = s.audio_path.open("ab")
        s.started_at = datetime.now()
        s.state = "recording"
        if s.meta.live:
            self.warm_up()
            try:
                s._live = self._live_transcriber(s)
            except Exception as exc:  # live preview is optional
                s.warning = f"Live transcript unavailable: {exc}"

    def _live_transcriber(self, s: Session) -> LiveTranscriber:
        pipe = self.pipeline
        library = pipe._library(s.meta.attendees or None)
        tracker = LiveSpeakerTracker(library, self.cfg.speakers.suggest_threshold)
        work = self.cfg.cache_dir / "live" / s.id
        work.mkdir(parents=True, exist_ok=True)

        def on_error(msg: str) -> None:
            s.warning = msg

        noise = None
        if self.cfg.noise.enabled:
            try:
                noise = NoiseSuppressor(self.cfg.noise.strength)
            except Exception as exc:
                on_error(f"Noise suppression unavailable; using original audio: {exc}")
        return LiveTranscriber(
            pipe.asr, pipe.diarizer, tracker, work, self.submit, s.put_live, on_error,
            noise=noise,
        )

    def add_audio(self, s: Session, pcm: bytes) -> None:
        """16-bit little-endian mono PCM at 16 kHz from the browser."""
        pcm = pcm[: len(pcm) - len(pcm) % 2]
        with s.lock:
            if s.state != "recording" or s._pcm is None:
                return
            s._pcm.write(pcm)
            s.samples += len(pcm) // 2
        if s._live is not None:
            s._live.feed(np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0)

    def stop_recording(self, s: Session) -> None:
        with s.lock:
            if s.state != "recording":
                return
            s.state = "processing"
            if s._pcm is not None:
                s._pcm.close()
                s._pcm = None
        if s._live is not None:
            s._live.cancel()  # the full pass supersedes the preview
            # Finished sessions must not retain speech models after Settings switches them.
            s._live = None
        if s.cancelled:
            if s.audio_path:
                s.audio_path.unlink(missing_ok=True)
            s.state = "cancelled"
            return
        s.log("Saving the recording")
        s.audio_path = self._pcm_to_wav(s.audio_path)
        if s.samples < SAMPLE_RATE:
            s.state, s.error = "error", "The recording is empty or shorter than one second."
            return
        self._analyze(s)

    def cancel(self, s: Session) -> None:
        s.cancelled = True
        if s.state == "recording":
            self.stop_recording(s)
        elif s.state == "new":
            s.state = "cancelled"

    def _pcm_to_wav(self, pcm_path: Path | None) -> Path:
        assert pcm_path is not None
        wav = pcm_path.with_suffix(".wav")
        data = np.fromfile(pcm_path, dtype="<i2").astype(np.float32) / 32768.0
        write_wav(wav, data)
        pcm_path.unlink(missing_ok=True)
        return wav

    def _recover_orphans(self) -> list[Path]:
        """Recordings interrupted by a crash are left as .pcm; turn them into WAV files."""
        recovered = []
        for pcm in self.recordings_dir.glob("*.pcm"):
            if pcm.stat().st_size >= 2 * SAMPLE_RATE:
                recovered.append(self._pcm_to_wav(pcm))
        return recovered

    # -- uploads ----------------------------------------------------------------------------

    def start_upload(self, s: Session, path: Path) -> None:
        s.audio_path = path
        self._analyze(s)

    # -- processing -------------------------------------------------------------------------

    def _analyze(self, s: Session) -> None:
        s.state = "processing"
        s.log("Waiting for the model worker")
        self.submit(lambda: self._analyze_job(s))

    def _analyze_job(self, s: Session) -> None:
        pipe = self.pipeline
        pipe.progress = s.log
        try:
            analysis = pipe.analyze(
                s.audio_path,  # type: ignore[arg-type]
                title=s.meta.title,
                date=s.started_at,
                project=s.meta.project,
                attendees=s.meta.attendees or None,
                num_speakers=s.meta.num_speakers,
            )
            self._apply_live_review(s, analysis)
        except Exception as exc:
            s.state, s.error = "error", f"{exc.__class__.__name__}: {exc}"
            return
        s.analysis, s.record = analysis, analysis.record
        if analysis.record.turns:
            s.state = "review"
        else:
            s.warning = "No speech was found in this recording."
            self._summarize_job(s, s.meta.template, s.meta.instructions, overwrite=False)

    def _apply_live_review(self, s: Session, analysis: Analysis) -> None:
        """Carry timed human labels into pass 2 using word timestamps, not text guessing.

        A live voice can split or merge in the full pass. Assign the overlapping words,
        rebuild the turns and voice clips, then let the ordinary review confirm names.
        """
        with s.lock:
            corrections = [dict(seg) for seg in s.live_segments
                           if seg.get("corrected") and not seg.get("partial")
                           and seg.get("text") and seg.get("speaker")]
        if not corrections or not analysis.words:
            return
        s.log("Carrying live speaker corrections into review")
        record = analysis.record
        labels = assign_speakers(analysis.words, [
            SpeakerSegment(t.start, t.end, t.speaker) for t in record.turns
        ])
        targets: dict[str, str] = {}
        for i, word in enumerate(analysis.words):
            match = max(corrections, key=lambda seg: min(word.end, seg["end"])
                        - max(word.start, seg["start"]))
            if min(word.end, match["end"]) <= max(word.start, match["start"]):
                continue
            name = match["speaker"]
            if name not in targets:
                key = f"LIVE_{len(targets)}"
                while key in record.assignments:
                    key += "_"
                targets[name] = key
                record.assignments[key] = SpeakerAssignment(
                    cluster=key,
                    suggestion=None if re.fullmatch(r"Speaker \d+", name) else name,
                    status="unknown" if re.fullmatch(r"Speaker \d+", name) else "suggested",
                    unknown_label=name if re.fullmatch(r"Speaker \d+", name)
                    else f"Live speaker {len(targets)}",
                )
            labels[i] = targets[name]
        record.turns = build_turns(analysis.words, labels)
        used = {turn.speaker for turn in record.turns}
        record.assignments = {key: a for key, a in record.assignments.items() if key in used}
        cfg = self.cfg.speakers
        # Voiceprints must be based on the corrected audio spans, never the old mixed cluster.
        analysis.voices = cluster_voices(
            analysis.audio, [SpeakerSegment(t.start, t.end, t.speaker) for t in record.turns],
            self.pipeline.diarizer, min_duration=cfg.min_segment_duration,
            max_segments=cfg.max_segments_per_cluster, clip_duration=cfg.clip_duration,
        )

    def submit_review(self, s: Session, names: dict[str, str | None]) -> None:
        if s.state != "review" or s.analysis is None:
            raise ValueError(f"Session is {s.state}, not waiting for review")
        unknown = set(names) - set(s.analysis.record.assignments)
        if unknown:
            raise ValueError(f"Unknown speaker cluster(s): {', '.join(sorted(unknown))}")
        s.state = "summarizing"
        s.messages.clear()

        def job() -> None:
            try:
                self.pipeline.apply_review(s.analysis, names)  # type: ignore[arg-type]
                learned = self.pipeline.learn(s.analysis)  # type: ignore[arg-type]
                if learned:
                    s.log(f"Remembered voices: {', '.join(learned)}")
            except Exception as exc:
                s.state, s.error = "error", f"Saving speakers failed: {exc}"
                return
            self._summarize_job(s, s.meta.template, s.meta.instructions, overwrite=False)

        self.submit(job)

    def regenerate(
        self, s: Session, template: str | None, instructions: str, force: bool = False
    ) -> None:
        retryable = s.state == "error" and s.note_path is not None
        if (s.state != "done" and not retryable) or s.record is None:
            raise ValueError("Notes can be regenerated once the meeting is processed")
        _record, note_sha = self.pipeline.load_record(s.record.id)
        if not force and self.pipeline.note_was_edited(s.record, note_sha):
            raise PermissionError(f"{s.record.note_path} was edited after it was generated")
        s.meta.template, s.meta.instructions, s.meta.summarize = template, instructions, True
        s.state, s.warning, s.error = "summarizing", None, None
        s.messages.clear()
        self.submit(lambda: self._summarize_job(s, template, instructions, overwrite=True))

    def _summarize_job(
        self, s: Session, template: str | None, instructions: str, overwrite: bool
    ) -> None:
        pipe = self.pipeline
        pipe.progress = s.log
        try:
            tmpl = pipe.template(template)
            notes = None
            if overwrite and not s.record.turns:
                raise ValueError("This meeting has no transcript to generate notes from")
            if s.meta.summarize and s.record.turns:
                s.log(f"Writing notes with {self.cfg.llm.model}")
                try:
                    notes = pipe.summarize(s.record, tmpl, instructions)
                except LLMError as exc:
                    if overwrite:
                        raise LLMError(
                            f"Rewriting failed. Your existing notes were kept. {exc}"
                        ) from exc
                    s.warning = f"Summary skipped: {exc}"
            s.note_path = pipe.write_note(s.record, notes, tmpl if notes else None, overwrite)
            s.state = "done"
        except Exception as exc:
            s.state, s.error = "error", f"{exc.__class__.__name__}: {exc}"

    # -- existing meetings ------------------------------------------------------------------

    def open_existing(self, meeting_id: str) -> Session:
        for s in self.sessions.values():
            if s.record is not None and s.record.id == meeting_id and s.state == "done":
                return s
        record, _sha = self.pipeline.load_record(meeting_id)
        s = self.create(SessionMeta(title=record.title, project=record.project), "existing")
        s.record = record
        s.note_path = Path(record.note_path) if record.note_path else None
        s.state = "done"
        return s

    # -- views ------------------------------------------------------------------------------

    def snapshot(
        self, s: Session, live_since: int = 0, live_rev: int | None = None
    ) -> dict[str, Any]:
        """`live_rev`: return live segments changed since that revision, interim text
        included. `live_since` (older clients): final segments with a higher id."""
        with s.lock:
            if live_rev is not None:
                live = [seg for seg in s.live_segments if seg["rev"] > live_rev]
            else:
                live = [
                    seg
                    for seg in s.live_segments
                    if seg["id"] > live_since and not seg.get("partial")
                ]
            data: dict[str, Any] = {
                "id": s.id,
                "kind": s.kind,
                "state": s.state,
                "meta": asdict(s.meta),
                "messages": s.messages[-12:],
                "error": s.error,
                "warning": s.warning,
                "elapsed": round(s.elapsed, 1),
                "live": live,
                "live_rev": s.live_rev,
            }
        if s.record is not None:
            data["meeting_id"] = s.record.id
            data["title"] = s.record.title
            data["duration"] = s.record.duration
        if s.state in ("review", "summarizing", "done") and s.record is not None:
            data["speakers"] = self._speakers(s)
        if s.state == "done" and s.note_path is not None:
            data["note_path"] = str(s.note_path)
        return data

    def _speakers(self, s: Session) -> list[dict[str, Any]]:
        record = s.record
        talk = record.speaking_time()
        out = []
        for cluster in dict.fromkeys(t.speaker for t in record.turns):
            a = record.assignments[cluster]
            turns = [t for t in record.turns if t.speaker == cluster]
            longest = sorted(turns, key=lambda t: len(t.text), reverse=True)[:2]
            quotes = sorted(longest, key=lambda t: t.start)
            voice = s.analysis.voices.get(cluster) if s.analysis else None
            out.append(
                {
                    "cluster": cluster,
                    "status": a.status,
                    "name": a.name,
                    "suggestion": a.suggestion,
                    "score": a.score,
                    "label": a.display_name,
                    "unknown_label": a.unknown_label,
                    "talk_seconds": round(talk.get(cluster, 0.0), 1),
                    "turns": len(turns),
                    "quotes": [{"start": q.start, "text": q.text} for q in quotes],
                    "has_clip": bool(voice and voice.clip),
                    "live_assigned": cluster.startswith("LIVE_"),
                }
            )
        return out

    def clip(self, s: Session, cluster: str) -> np.ndarray | None:
        if s.analysis is None:
            return None
        voice = s.analysis.voices.get(cluster)
        if voice is None or voice.clip is None:
            return None
        return s.analysis.audio.slice(*voice.clip)
