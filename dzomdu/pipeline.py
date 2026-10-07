"""The post-meeting pipeline: audio -> diarization + ASR -> speaker turns -> identification ->
LLM notes -> Markdown note in the vault."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .align import align
from .asr import ASRBackend, get_asr_backend
from .audio import Audio, file_sha256, prepare_audio, write_wav
from .config import Config
from .diarize import Diarizer, get_diarizer, l2_normalize
from .llm.client import LLMClient
from .llm.schema import MeetingNotes
from .llm.summarize import summarize
from .models import MeetingRecord, SpeakerAssignment, SpeakerSegment, Word
from .notes.render import render_note
from .notes.templates import MinutesTemplate, load_template
from .speakers.matching import ClusterVoice, LibraryEntry, cluster_voices, match_clusters
from .speakers.store import VoiceprintStore
from .vault import Vault

Progress = Callable[[str], None]


@dataclass
class Analysis:
    record: MeetingRecord
    audio: Audio
    voices: dict[str, ClusterVoice]
    predicted: dict[str, SpeakerAssignment] = field(default_factory=dict)


def _slug_key(model_id: str) -> str:
    return hashlib.sha1(model_id.encode()).hexdigest()[:10]


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        *,
        asr: ASRBackend | None = None,
        diarizer: Diarizer | None = None,
        llm: LLMClient | None = None,
        store: VoiceprintStore | None = None,
        vault: Vault | None = None,
        progress: Progress | None = None,
    ):
        self.cfg = cfg
        self._asr = asr
        self._diarizer = diarizer
        self._llm = llm
        self._store = store
        self.vault = vault or Vault(cfg.vault)
        self.progress = progress or (lambda _msg: None)

    # lazily constructed so commands that don't need a model don't load one
    @property
    def asr(self) -> ASRBackend:
        if self._asr is None:
            self._asr = get_asr_backend(self.cfg.asr)
        return self._asr

    @property
    def diarizer(self) -> Diarizer:
        if self._diarizer is None:
            self._diarizer = get_diarizer(self.cfg.diarization)
        return self._diarizer

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.cfg.llm)
        return self._llm

    @property
    def store(self) -> VoiceprintStore:
        if self._store is None:
            self._store = VoiceprintStore(self.cfg.db_path, self.cfg.clips_dir)
        return self._store

    # -- step 1: analyse audio ---------------------------------------------------------------

    def analyze(
        self,
        audio_path: Path,
        *,
        title: str | None = None,
        date: datetime | None = None,
        project: str | None = None,
        attendees: list[str] | None = None,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        fresh: bool = False,
    ) -> Analysis:
        audio_path = audio_path.expanduser().resolve()
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)
        self.progress("Reading audio")
        sha = file_sha256(audio_path)
        work = self.cfg.cache_dir / sha[:16]
        if fresh and work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        audio = prepare_audio(audio_path, work)

        segments = self._diarize(audio, work, num_speakers, min_speakers, max_speakers)
        words = self._transcribe(audio, work)
        self.progress("Aligning words with speakers")
        turns = align(words, segments)

        self.progress("Recognising speakers")
        speaking = [t.speaker for t in turns]
        order = list(dict.fromkeys(speaking))  # clusters in order of first speech
        cfg = self.cfg.speakers
        voices = cluster_voices(
            audio,
            [s for s in segments if s.speaker in order],
            self.diarizer,
            min_duration=cfg.min_segment_duration,
            max_segments=cfg.max_segments_per_cluster,
            clip_duration=cfg.clip_duration,
        )
        assignments = match_clusters(
            voices,
            self._library(attendees),
            cfg.accept_threshold,
            cfg.suggest_threshold,
            first_seen_order=order,
        )

        if date is None:  # file time is usually when recording stopped
            mtime = datetime.fromtimestamp(audio_path.stat().st_mtime)
            date = mtime - timedelta(seconds=audio.duration)
        record = MeetingRecord(
            id=f"{date:%Y%m%d-%H%M}-{sha[:6]}",
            title=title or "",
            date=date.isoformat(timespec="minutes"),
            source_audio=str(audio_path),
            audio_sha=sha,
            duration=round(audio.duration, 2),
            project=project,
            turns=turns,
            assignments=assignments,
            asr_model=self.asr.model_id,
            diarization_model=self.diarizer.model_id,
            attendees=list(attendees or []),
        )
        return Analysis(record, audio, voices, copy.deepcopy(assignments))

    def _diarize(
        self, audio: Audio, work: Path, num: int | None, lo: int | None, hi: int | None
    ) -> list[SpeakerSegment]:
        key = _slug_key(f"{self.diarizer.model_id}|{num}|{lo}|{hi}")
        cache = work / f"diarization-{key}.json"
        if cache.exists():
            return [SpeakerSegment(**s) for s in json.loads(cache.read_text())]
        self.progress(f"Diarizing ({self.diarizer.model_id})")
        segments = self.diarizer.diarize(audio, num, lo, hi)
        cache.write_text(json.dumps([asdict(s) for s in segments]))
        return segments

    def _transcribe(self, audio: Audio, work: Path) -> list[Word]:
        cache = work / f"asr-{_slug_key(self.asr.model_id)}.json"
        if cache.exists():
            return [Word(**w) for w in json.loads(cache.read_text())]
        self.progress(f"Transcribing ({self.asr.model_id})")
        words = self.asr.transcribe(audio)
        cache.write_text(json.dumps([asdict(w) for w in words]))
        return words

    def _library(self, attendees: list[str] | None) -> list[LibraryEntry]:
        """Known voices to match against. With attendees given, only those people are
        candidates (a small closed set is far more accurate than everyone ever enrolled)."""
        speakers = self.store.list(model=self.diarizer.model_id)
        if attendees:
            wanted = {a.strip().casefold() for a in attendees}
            speakers = [s for s in speakers if s.name.casefold() in wanted]
        vectors = self.store.embeddings(self.diarizer.model_id, [s.id for s in speakers])
        return [LibraryEntry(s.id, s.name, vectors[s.id]) for s in speakers if s.id in vectors]

    # -- step 2: apply the review, learn voices ---------------------------------------------

    def apply_review(self, analysis: Analysis, names: dict[str, str | None]) -> None:
        """`names` maps cluster -> confirmed person name (None = leave unidentified).
        Several clusters may map to the same person (diarization split one voice)."""
        for cluster, name in names.items():
            assignment = analysis.record.assignments[cluster]
            if name and name.strip():
                assignment.name = name.strip()
                assignment.status = "confirmed"
            else:
                assignment.name = None
                assignment.suggestion = None
                assignment.speaker_id = None
                assignment.status = "unknown"

    def learn(self, analysis: Analysis) -> list[str]:
        """Store voiceprints for confirmed speakers and log feedback. Returns names learned.
        Only human-confirmed clusters are learned, so mistakes don't creep into voiceprints."""
        record, model = analysis.record, self.diarizer.model_id
        cfg = self.cfg.speakers
        learned: dict[str, list[ClusterVoice]] = {}
        for cluster, assignment in record.assignments.items():
            predicted = analysis.predicted.get(cluster)
            final_id = None
            if assignment.status == "confirmed" and assignment.name:
                speaker = self.store.get_or_create(assignment.name)
                assignment.speaker_id = final_id = speaker.id
                voice = analysis.voices.get(cluster)
                if voice is not None and voice.embedding is not None:
                    learned.setdefault(assignment.name, []).append(voice)
            if predicted is not None:
                self.store.log_feedback(
                    record.id,
                    cluster,
                    model,
                    predicted.speaker_id,
                    predicted.score,
                    predicted.status,
                    final_id,
                )

        for name, voices in learned.items():
            speaker = self.store.get_or_create(name)
            # merge clusters of the same person, weighted by how much they spoke
            weights = np.array([max(v.speech_seconds, 1.0) for v in voices])
            emb = l2_normalize((np.stack([v.embedding for v in voices]) * weights[:, None]).sum(0))
            main = max(voices, key=lambda v: v.speech_seconds)
            clip_path = None
            if main.clip:
                clip_path = self.store.clip_path_for(speaker.id, f"{record.id}-{main.cluster}")
                write_wav(clip_path, analysis.audio.slice(*main.clip), analysis.audio.sample_rate)
            self.store.add_embedding(
                speaker.id,
                model,
                emb,
                source=record.id,
                clip_path=clip_path,
                max_per_speaker=cfg.max_embeddings_per_speaker,
            )
        for name in learned:
            self.vault.ensure_person(name)
        return sorted(learned)

    def enroll(
        self,
        name: str,
        audio_path: Path,
        start: float | None = None,
        end: float | None = None,
        consent: bool = False,
    ) -> int:
        """Explicit enrolment from a recording of one person speaking (20-30 s is plenty)."""
        sha = file_sha256(audio_path.expanduser())
        audio = prepare_audio(audio_path.expanduser(), self.cfg.cache_dir / sha[:16])
        samples = audio.slice(start or 0.0, end if end is not None else audio.duration)
        if len(samples) < 3 * audio.sample_rate:
            raise ValueError("Need at least 3 seconds of speech to enrol a voice")
        win = 8 * audio.sample_rate
        pieces = [samples[i : i + win] for i in range(0, len(samples), win)]
        pieces = [p for p in pieces if len(p) >= 2 * audio.sample_rate]
        embs = self.diarizer.embed(pieces, audio.sample_rate)
        embs = embs[np.all(np.isfinite(embs), axis=1)]
        if not len(embs):
            raise ValueError("Could not compute a voiceprint from this audio")
        speaker = self.store.get_or_create(name, consent=consent)
        clip_path = self.store.clip_path_for(speaker.id, f"enrol-{sha[:8]}")
        write_wav(clip_path, pieces[0], audio.sample_rate)
        self.store.add_embedding(
            speaker.id,
            self.diarizer.model_id,
            l2_normalize(embs.mean(0)),
            source=f"enrol:{audio_path.name}",
            clip_path=clip_path,
            max_per_speaker=self.cfg.speakers.max_embeddings_per_speaker,
        )
        self.vault.ensure_person(name)
        return speaker.id

    # -- step 3: notes ----------------------------------------------------------------------

    def context_for(self, record: MeetingRecord) -> str:
        lines = [f"Meeting date: {record.date[:10]}"]
        if record.project:
            lines.append(f"Project: {record.project}")
            if project := self.vault.project_context(record.project):
                lines.append(project)
        people = sorted(
            {a.name for a in record.assignments.values() if a.name} | set(record.attendees)
        )
        bios = [b for name in people if (b := self.vault.person_context(name))]
        if bios:
            lines.append("People in this meeting:\n" + "\n".join(bios))
        return "\n".join(lines)

    def summarize(
        self, record: MeetingRecord, template: MinutesTemplate, extra_instructions: str = ""
    ) -> MeetingNotes:
        instructions = "\n".join(x for x in (template.instructions, extra_instructions) if x)
        return summarize(
            self.llm,
            record.turns,
            record.name_for,
            context=self.context_for(record),
            instructions=instructions,
            max_chunk_tokens=self.cfg.llm.max_chunk_tokens,
            progress=self.progress,
        )

    def template(self, key: str | None) -> MinutesTemplate:
        return load_template(key or self.cfg.default_template, self.vault.templates_dir)

    def write_note(
        self,
        record: MeetingRecord,
        notes: MeetingNotes | None,
        template: MinutesTemplate | None,
        overwrite: bool = False,
    ) -> Path:
        if not record.title:
            record.title = (notes.title if notes and notes.title else None) or (
                f"Meeting {datetime.fromisoformat(record.date):%H%M}"
            )
        if record.project:
            self.vault.ensure_project(record.project)
        if overwrite and record.note_path:
            path = Path(record.note_path)
        else:
            path = self.vault.meeting_path(
                datetime.fromisoformat(record.date), record.title, record.project
            )
        text = render_note(record, notes, template, self.llm.model if notes else None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        record.note_path = str(path)
        self.save_record(record, note_sha=hashlib.sha256(text.encode()).hexdigest())
        return path

    # -- persistence -------------------------------------------------------------------------

    def save_record(self, record: MeetingRecord, note_sha: str | None = None) -> Path:
        self.cfg.meetings_dir.mkdir(parents=True, exist_ok=True)
        path = self.cfg.meetings_dir / f"{record.id}.json"
        data = record.to_dict()
        data["_note_sha"] = note_sha
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def load_record(self, meeting_id: str) -> tuple[MeetingRecord, str | None]:
        path = self.cfg.meetings_dir / f"{meeting_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No processed meeting with id {meeting_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        note_sha = data.pop("_note_sha", None)
        return MeetingRecord.from_dict(data), note_sha

    def note_was_edited(self, record: MeetingRecord, note_sha: str | None) -> bool:
        if not record.note_path or not Path(record.note_path).exists() or not note_sha:
            return False
        current = hashlib.sha256(Path(record.note_path).read_bytes()).hexdigest()
        return current != note_sha
