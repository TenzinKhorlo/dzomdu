"""HTTP + WebSocket API for the local web UI. Binds to localhost only by default."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import queue
import re
import shutil
import sqlite3
import time
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime
from pathlib import Path
from threading import Event, RLock
from typing import Annotated, Any
from urllib.parse import quote

import jinja2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect
from yaml import YAMLError

from .. import dashboard
from ..audio import wav_bytes
from ..chat import ChatConflict, ChatCreate, ChatQuestion, ChatStore, ChatUpdate, answer_question
from ..config import (
    ASR_PACKAGES,
    Config,
    LLMConfig,
    NoiseConfig,
    default_config_path,
    is_installed,
    save_config,
)
from ..llm.client import LLMClient, LLMError
from ..llm.schema import SECTION_TYPES, SectionSpec
from ..model_library import OPTIONS, ModelLibrary, compatible, current_id
from ..noise import INSTALL_COMMAND, MODEL_ID, NoiseSuppressor
from ..notes.render import check_template_body
from ..notes.templates import (
    builtin_text,
    list_templates,
    load_template,
    section_key,
    template_key,
    template_text,
)
from ..persistence import meeting_locked
from ..pipeline import Pipeline
from ..projects import ProjectConflict, ProjectManager
from ..tasks import TaskConflict, TaskManager
from ..vault import Vault, safe_filename
from .markdown import chat_to_html, note_to_html
from .sessions import ACTIVE_STATES, SessionManager, SessionMeta

STATIC = Path(__file__).parent / "static"  # the original single-page UI, kept at /classic/


def _audio_type(path: Path) -> str:
    types = {
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    return types.get(path.suffix.lower(), "application/octet-stream")


def web_dir() -> Path | None:
    """The built Next.js dashboard (`npm run build` in web/), if present."""
    env = os.environ.get("DZOMDU_WEB_DIR")
    path = Path(env) if env else Path(__file__).resolve().parents[2] / "web" / "out"
    return path if (path / "index.html").exists() else None


UPLOAD_SUFFIXES = {
    ".wav",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mov",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".webm",
    ".mkv",
    ".wma",
    ".aiff",
    ".aif",
}


class ReviewBody(BaseModel):
    names: dict[str, str | None]


class RegenerateBody(BaseModel):
    template: str | None = None
    instructions: str = ""
    force: bool = False


class TaskBody(BaseModel):
    done: bool


class TaskUpdate(BaseModel):
    done: bool | None = None
    reminder_date: date | None = None


class PersonBody(BaseModel):
    name: str
    role: str | None = None
    organisation: str | None = None
    bio: str | None = None


class LLMSettings(BaseModel):
    api: str = "ollama"  # "ollama" (local or Ollama Cloud) | "openai" (any compatible server)
    base_url: str
    model: str
    api_key: str | None = None  # None/empty keeps the saved key
    clear_api_key: bool = False


class SettingsBody(BaseModel):
    llm: LLMSettings | None = None
    vault: str | None = None
    default_template: str | None = None
    summary_instructions: str | None = None


class ModelSettingsBody(BaseModel):
    asr_id: str
    diarization_id: str
    language: str = "en"
    max_speakers: int | None = Field(default=None, ge=1, le=100)


class ModelDownloadBody(BaseModel):
    model_ids: list[str] = Field(min_length=1, max_length=30)


class NoiseSettingsBody(BaseModel):
    enabled: bool
    strength: float = Field(default=0.5, ge=0, le=0.75)


SECTION_KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")


class SectionBody(BaseModel):
    key: str | None = None  # kept when editing, so layouts that use it keep working
    title: str
    type: str = "text"
    description: str = ""


class TemplateBody(BaseModel):
    name: str
    description: str = ""
    instructions: str = ""
    body: str
    sections: list[SectionBody] = []


class ProjectBody(BaseModel):
    name: str


class MeetingTitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ProjectMembersBody(BaseModel):
    members: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=100)


class DeleteProjectBody(BaseModel):
    meeting_ids: list[str]


class RenameBody(BaseModel):
    old: str
    new: str


def create_app(
    cfg: Config, pipeline: Pipeline | None = None, config_path: Path | None = None
) -> FastAPI:
    pipeline = pipeline or Pipeline(cfg)
    pipeline.vault.init()
    manager = SessionManager(cfg, pipeline)
    chats = ChatStore(cfg.data_dir / "chats.sqlite")
    answering: set[str] = set()
    project_manager = ProjectManager(cfg, pipeline.vault, manager.recordings_dir, chats)
    project_lock = RLock()
    task_manager = TaskManager(cfg)
    model_library = ModelLibrary(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        manager.shutdown()
        model_library.shutdown()

    app = FastAPI(title="Dzomdu", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager
    app.state.model_library = model_library
    # `next dev` runs the dashboard on :3000 during development and calls this API directly
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    web = web_dir()

    def session_or_404(sid: str):
        try:
            return manager.get(sid)
        except KeyError:
            raise HTTPException(404, "No such session") from None

    # -- app shell --------------------------------------------------------------------------

    @app.get("/classic/")
    def classic() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    if web is None:  # dashboard not built: the classic UI is the home page

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        vault = pipeline.vault
        people = {s.name for s in pipeline.store.list()}
        if vault.people_dir.is_dir():
            people |= {p.stem for p in vault.people_dir.glob("*.md")}
        projects = sorted(
            p.name
            for p in vault.projects_dir.glob("*")
            if p.is_dir() and not p.name.startswith(".")
        )
        llm_ok, llm_detail = await asyncio.to_thread(LLMClient(cfg.llm).ping)
        asr_pkg = ASR_PACKAGES.get(cfg.asr.backend)
        return {
            "templates": [
                {"key": t.key, "name": t.name, "description": t.description}
                for t in list_templates(vault.templates_dir)
            ],
            "default_template": cfg.default_template,
            "people": sorted(people, key=str.casefold),
            "projects": projects,
            "vault": str(cfg.vault),
            "models": {
                "asr": cfg.asr.model or cfg.asr.backend,
                "diarization": cfg.diarization.model,
                "llm": cfg.llm.model,
            },
            "status": {
                "llm": {"ok": llm_ok, "detail": llm_detail},
                "asr": {"ok": asr_pkg is None or is_installed(asr_pkg)},
                "diarization": {
                    "ok": is_installed("pyannote.audio")
                    and (cfg.diarization.backend == "pyannote" or is_installed("mlx_audio"))
                },
            },
            "recovered": [str(p) for p in manager.recovered],
        }

    # -- settings ---------------------------------------------------------------------------

    def settings_view() -> dict[str, Any]:
        llm = cfg.llm
        return {
            "llm": {
                "api": llm.api,
                "base_url": llm.base_url,
                "model": llm.model,
                "api_key_set": bool(llm.api_key),  # the key itself is never sent back
            },
            "vault": str(cfg.vault),
            "default_template": cfg.default_template,
            "summary_instructions": cfg.summary_instructions,
        }

    def candidate_llm(body: LLMSettings) -> LLMConfig:
        if body.api not in ("ollama", "openai"):
            raise HTTPException(400, "api must be 'ollama' or 'openai'")
        if not body.base_url.strip() or not body.model.strip():
            raise HTTPException(400, "A server URL and a model name are required")
        if not body.base_url.strip().startswith(("http://", "https://")):
            raise HTTPException(400, "The server URL must start with http:// or https://")
        key = "" if body.clear_api_key else (body.api_key or cfg.llm.api_key)
        return LLMConfig(
            **{
                **vars(cfg.llm),
                "api": body.api,
                "base_url": body.base_url.strip(),
                "model": body.model.strip(),
                "api_key": key,
            }
        )

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return settings_view()

    def model_settings_view() -> dict[str, Any]:
        return {
            "asr_id": current_id(cfg, "asr"),
            "diarization_id": current_id(cfg, "diarization"),
            "asr_model": cfg.asr.model or cfg.asr.backend,
            "diarization_model": cfg.diarization.model,
            "language": cfg.asr.language or "auto",
            "max_speakers": cfg.diarization.max_speakers,
        }

    def noise_settings_view() -> dict[str, Any]:
        return {
            "enabled": cfg.noise.enabled,
            "strength": cfg.noise.strength,
            "model": MODEL_ID,
            "runtime_installed": is_installed("pyrnnoise") and is_installed("scipy"),
            "install_command": INSTALL_COMMAND,
            "license": "BSD-3-Clause (RNNoise); Apache-2.0 (Python wrapper)",
            "algorithmic_delay_ms": NoiseSuppressor.delay_samples / 16,
        }

    @app.get("/api/settings/noise")
    def get_noise_settings() -> dict[str, Any]:
        return noise_settings_view()

    @app.put("/api/settings/noise")
    def select_noise_settings(body: NoiseSettingsBody) -> dict[str, Any]:
        if any(s.state in ACTIVE_STATES | {"review"} for s in manager.sessions.values()):
            raise HTTPException(
                409, "Finish or cancel the current meeting before changing audio settings"
            )
        if body.enabled:
            try:
                # Validate native library availability, not merely package metadata.
                probe = NoiseSuppressor(body.strength)
                probe.close()
            except (RuntimeError, ImportError, OSError) as exc:
                raise HTTPException(400, str(exc)) from exc
        candidate = copy.deepcopy(cfg)
        candidate.noise = NoiseConfig(enabled=body.enabled, strength=body.strength)
        try:
            save_config(candidate, config_path or default_config_path())
        except OSError as exc:
            raise HTTPException(500, f"Could not save the settings: {exc}") from exc
        cfg.noise = candidate.noise
        return noise_settings_view()

    @app.get("/api/models")
    def models_view() -> dict[str, Any]:
        return {"models": model_library.view(), "settings": model_settings_view()}

    @app.post("/api/models/download")
    def download_models(body: ModelDownloadBody) -> dict[str, bool]:
        try:
            model_library.queue(body.model_ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"queued": True}

    @app.put("/api/settings/models")
    def select_models(body: ModelSettingsBody) -> dict[str, Any]:
        asr = OPTIONS.get(body.asr_id)
        diar = OPTIONS.get(body.diarization_id)
        if not asr or asr.kind != "asr" or not diar or diar.kind != "diarization":
            raise HTTPException(400, "Choose a transcription and speaker model from the library")
        for option in (asr, diar):
            if reason := compatible(option):
                raise HTTPException(400, reason)
            if not model_library.ready(option.id):
                raise HTTPException(400, f"Set up and download {option.name} before selecting it")
        if body.language not in asr.languages:
            raise HTTPException(400, "This model does not support the selected language")
        max_speakers = body.max_speakers if body.max_speakers is not None else diar.speaker_limit
        if diar.speaker_limit and max_speakers > diar.speaker_limit:
            raise HTTPException(
                400, "Nemotron requires a maximum of 8 speakers. Use Pyannote for 15+."
            )
        if any(s.state in ACTIVE_STATES | {"review"} for s in manager.sessions.values()):
            raise HTTPException(409, "Finish or cancel the current meeting before changing models")
        if manager._warm is not None and not manager._warm.done():
            raise HTTPException(
                409, "Models are warming up. Wait for them before changing defaults"
            )
        candidate = copy.deepcopy(cfg)
        candidate.asr.backend, candidate.asr.model = asr.backend, asr.repo
        candidate.asr.language = body.language
        candidate.diarization.backend, candidate.diarization.model = diar.backend, diar.repo
        candidate.diarization.max_speakers = max_speakers
        try:
            save_config(candidate, config_path or default_config_path())
        except OSError as exc:
            raise HTTPException(500, f"Could not save the settings: {exc}") from exc

        def apply_models():
            old = pipeline._asr
            if old is not None and hasattr(old, "close"):
                old.close()
            pipeline._asr = pipeline._diarizer = None
            cfg.asr, cfg.diarization = candidate.asr, candidate.diarization
            manager._warm = None
            import gc

            gc.collect()

        manager.submit(apply_models).result()
        return model_settings_view()

    @app.post("/api/settings/llm/test")
    async def test_llm(body: LLMSettings) -> dict[str, Any]:
        ok, detail = await asyncio.to_thread(LLMClient(candidate_llm(body)).ping)
        return {"ok": ok, "detail": detail}

    @app.put("/api/settings")
    def save_settings(body: SettingsBody) -> dict[str, Any]:
        new_llm = candidate_llm(body.llm) if body.llm else None
        new_vault: Path | None = None
        if body.vault is not None and body.vault.strip():
            new_vault = Path(body.vault.strip()).expanduser().resolve()
            if new_vault != cfg.vault:
                if new_vault.exists() and not new_vault.is_dir():
                    raise HTTPException(400, "The vault location is a file, not a folder")
                if any(s.state in ACTIVE_STATES for s in manager.sessions.values()):
                    raise HTTPException(409, "Finish or cancel the current meeting first")
                try:
                    Vault(new_vault).init()
                except OSError as exc:
                    raise HTTPException(400, f"Cannot use that folder: {exc}") from exc
        if body.default_template is not None:
            try:
                load_template(body.default_template, pipeline.vault.templates_dir)
            except KeyError as exc:
                raise HTTPException(400, str(exc.args[0])) from exc
            cfg.default_template = body.default_template
        if body.summary_instructions is not None:
            cfg.summary_instructions = body.summary_instructions.strip()
        if new_llm is not None:
            cfg.llm = new_llm
            pipeline._llm = None  # rebuilt with the new server and key on next use
        if new_vault is not None and new_vault != cfg.vault:
            cfg.vault = new_vault
            pipeline.vault = Vault(new_vault)
        try:
            save_config(cfg, config_path or default_config_path())
        except OSError as exc:
            raise HTTPException(500, f"Could not save the settings: {exc}") from exc
        return settings_view()

    # -- minutes formats --------------------------------------------------------------------

    def template_view(t: Any) -> dict[str, Any]:
        shipped = builtin_text(t.key)
        path = pipeline.vault.templates_dir / f"{t.key}.md"
        return {
            "key": t.key,
            "name": t.name,
            "description": t.description,
            "instructions": t.instructions,
            "body": t.body.strip("\n"),
            "sections": [
                {"key": x.key, "title": x.title, "type": x.type, "description": x.description}
                for x in t.sections
            ],
            "builtin": shipped is not None,
            # a built-in the user has changed, so "reset" does something
            "edited": shipped is not None
            and path.is_file()
            and path.read_text(encoding="utf-8").strip() != shipped.strip(),
            "default": t.key == cfg.default_template,
        }

    def validated_template(body: TemplateBody) -> str:
        if not body.name.strip():
            raise HTTPException(400, "Give the format a name")
        if not body.body.strip():
            raise HTTPException(400, "The layout cannot be empty")
        specs: list[SectionSpec] = []
        for sec in body.sections:
            key = sec.key if sec.key and SECTION_KEY.fullmatch(sec.key) else section_key(sec.title)
            if not sec.title.strip() or not key or sec.type not in SECTION_TYPES:
                raise HTTPException(400, f"Extra field “{sec.title}” needs a name and a valid type")
            if key in {s.key for s in specs}:
                raise HTTPException(400, f"Two extra fields would both be called “{key}”")
            specs.append(SectionSpec(key, sec.title.strip(), sec.type, sec.description.strip()))
        try:
            check_template_body(body.body, specs)
        except jinja2.TemplateSyntaxError as exc:
            raise HTTPException(400, f"Layout error on line {exc.lineno}: {exc.message}") from exc
        except jinja2.TemplateError as exc:
            raise HTTPException(400, f"Layout error: {exc}") from exc
        return template_text(body.name, body.description, body.instructions, body.body, specs)

    def write_template(key: str, text: str) -> None:
        folder = pipeline.vault.templates_dir
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.md").write_text(text, encoding="utf-8")

    @app.get("/api/templates")
    def get_templates() -> list[dict[str, Any]]:
        return [template_view(t) for t in list_templates(pipeline.vault.templates_dir)]

    @app.post("/api/templates")
    def create_template(body: TemplateBody) -> dict[str, Any]:
        text = validated_template(body)
        key = template_key(body.name)
        if not key:
            raise HTTPException(400, "The name needs letters or numbers")
        if (pipeline.vault.templates_dir / f"{key}.md").exists() or builtin_text(key):
            raise HTTPException(409, f"A format with the key “{key}” already exists")
        write_template(key, text)
        return template_view(load_template(key, pipeline.vault.templates_dir))

    @app.put("/api/templates/{key}")
    def update_template(key: str, body: TemplateBody) -> dict[str, Any]:
        known = {t.key for t in list_templates(pipeline.vault.templates_dir)}
        if key not in known:
            raise HTTPException(404, f"No format called {key}")
        write_template(key, validated_template(body))
        return template_view(load_template(key, pipeline.vault.templates_dir))

    @app.delete("/api/templates/{key}")
    def delete_template(key: str) -> dict[str, Any]:
        """Delete a custom format, or put a built-in one back to how it shipped."""
        path = pipeline.vault.templates_dir / f"{key}.md"
        shipped = builtin_text(key)
        if shipped is not None:
            write_template(key, shipped)
            return {"reset": True}
        if not path.is_file():
            raise HTTPException(404, f"No format called {key}")
        if key == cfg.default_template:
            raise HTTPException(409, "This is the default format. Choose another default first")
        path.unlink()
        return {"deleted": True}

    # -- sessions ---------------------------------------------------------------------------

    def meeting_meta(raw: dict[str, Any]) -> SessionMeta:
        try:
            meta = SessionMeta.from_dict(raw)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Enter a valid whole number of speakers") from exc
        if meta.num_speakers is not None and not 1 <= meta.num_speakers <= 100:
            raise HTTPException(400, "The number of speakers must be between 1 and 100")
        if cfg.diarization.backend == "nemotron-mlx" and (
            (meta.num_speakers or 0) > 8 or len(meta.attendees) > 8
        ):
            raise HTTPException(
                400, "Choose Pyannote in Settings for meetings with more than 8 people"
            )
        if (
            cfg.diarization.max_speakers is not None
            and meta.num_speakers is not None
            and meta.num_speakers > cfg.diarization.max_speakers
        ):
            raise HTTPException(400, "Increase the maximum speakers in Settings for this meeting")
        return meta

    @app.post("/api/sessions")
    def create_session(meta: dict[str, Any]) -> dict[str, str]:
        if any(s.state == "recording" for s in manager.sessions.values()):
            raise HTTPException(409, "A recording is already in progress")
        return {"id": manager.create(meeting_meta(meta), "recording").id}

    async def close_audio_socket(ws: WebSocket, code: int = 1000, reason: str = "") -> None:
        # The browser can disappear between receiving its final message and sending
        # our close frame. Both transport loss and an already-closed socket are normal.
        with suppress(WebSocketDisconnect, RuntimeError):
            await ws.close(code=code, reason=reason)

    @app.websocket("/api/sessions/{sid}/audio")
    async def audio(ws: WebSocket, sid: str) -> None:
        await ws.accept()
        try:
            s = manager.get(sid)
            manager.start_recording(s)
        except (KeyError, ValueError) as exc:
            await close_audio_socket(ws, code=4400, reason=str(exc))
            return
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    manager.add_audio(s, msg["bytes"])
                elif msg.get("text") == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            # also runs if the tab is closed: the recording is kept and processed
            await asyncio.to_thread(manager.stop_recording, s)
        await close_audio_socket(ws)

    @app.post("/api/upload")
    def upload(
        file: Annotated[UploadFile, File()], meta: Annotated[str, Form()] = "{}"
    ) -> dict[str, str]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in UPLOAD_SUFFIXES:
            raise HTTPException(400, f"Unsupported file type {suffix or '(none)'}")
        try:
            meta_dict = json.loads(meta)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "meta must be JSON") from exc
        if not isinstance(meta_dict, dict):
            raise HTTPException(400, "meta must be a JSON object")
        s = manager.create(meeting_meta(meta_dict), "upload")
        dest = manager.recordings_dir / f"{s.id}{suffix}"
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        manager.start_upload(s, dest)
        return {"id": s.id}

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str, live_since: int = 0, live_rev: int | None = None) -> dict[str, Any]:
        return manager.snapshot(session_or_404(sid), live_since, live_rev)

    @app.post("/api/warmup")
    def warmup() -> dict[str, bool]:
        """Called when the Record page opens, so models are ready before the first word."""
        manager.warm_up()
        return {"ok": True}

    @app.post("/api/sessions/{sid}/cancel")
    def cancel(sid: str) -> dict[str, str]:
        s = session_or_404(sid)
        manager.cancel(s)
        return {"state": s.state}

    @app.get("/api/sessions/{sid}/clips/{cluster}")
    def clip(sid: str, cluster: str) -> Response:
        samples = manager.clip(session_or_404(sid), cluster)
        if samples is None:
            raise HTTPException(404, "No clip for this speaker")
        return Response(wav_bytes(samples), media_type="audio/wav")

    @app.post("/api/sessions/{sid}/review")
    def review(sid: str, body: ReviewBody) -> dict[str, str]:
        s = session_or_404(sid)
        try:
            manager.submit_review(s, body.names)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"state": s.state}

    @app.post("/api/sessions/{sid}/regenerate")
    def regenerate(sid: str, body: RegenerateBody) -> dict[str, str]:
        with project_lock:
            s = session_or_404(sid)
            try:
                manager.regenerate(s, body.template, body.instructions, body.force)
            except PermissionError as exc:
                raise HTTPException(409, f"edited:{exc}") from exc
            except (ValueError, FileNotFoundError, KeyError) as exc:
                raise HTTPException(400, str(exc)) from exc
            return {"state": s.state}

    @app.get("/api/sessions/{sid}/note")
    def note(sid: str) -> dict[str, Any]:
        s = session_or_404(sid)
        if s.note_path is None or not s.note_path.exists():
            raise HTTPException(404, "The note has not been written yet")
        text = s.note_path.read_text(encoding="utf-8")
        return {
            "path": str(s.note_path),
            "markdown": text,
            "html": note_to_html(text),
            "obsidian_url": "obsidian://open?path=" + quote(str(s.note_path)),
        }

    # -- meetings, voices -------------------------------------------------------------------

    @app.get("/api/meetings")
    def meetings() -> dict[str, list[dict[str, Any]]]:
        rows = [dashboard.meeting_row(r) for r in dashboard.load_records(cfg.meetings_dir)]
        active = [
            {"id": s.id, "title": s.meta.title or "New meeting", "state": s.state}
            for s in manager.sessions.values()
            if s.state in ACTIVE_STATES | {"review"}
        ]
        return {"meetings": rows, "active": active}

    @app.get("/api/dashboard")
    @meeting_locked
    def dashboard_data(days: int = 30) -> dict[str, Any]:
        task_manager.list()
        records = dashboard.load_records(cfg.meetings_dir)
        data = dashboard.build_dashboard(records, len(pipeline.store.list()), days=days)
        data["active"] = [
            {"id": s.id, "title": s.meta.title or "New meeting", "state": s.state}
            for s in manager.sessions.values()
            if s.state in ACTIVE_STATES | {"review"}
        ]
        return data

    def record_or_404(meeting_id: str) -> dict[str, Any]:
        path = cfg.meetings_dir / f"{meeting_id}.json"
        if not path.exists():
            raise HTTPException(404, f"No meeting with id {meeting_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/meetings/{meeting_id}")
    @meeting_locked
    def meeting_detail(meeting_id: str) -> dict[str, Any]:
        r = record_or_404(meeting_id)
        task_manager.sync(r)
        talk: dict[str, float] = {}
        for t in r.get("turns", []):
            talk[t["speaker"]] = talk.get(t["speaker"], 0.0) + t["end"] - t["start"]

        def label(a: dict[str, Any]) -> str:
            if a.get("name"):
                return a["name"]
            return f"{a['suggestion']}?" if a.get("suggestion") else a["unknown_label"]

        assignments = r.get("assignments", {})
        speakers = [
            {
                "cluster": c,
                "label": label(a),
                "name": a.get("name"),
                "status": a.get("status"),
                "talk_seconds": round(talk.get(c, 0.0), 1),
                "turns": sum(1 for t in r.get("turns", []) if t["speaker"] == c),
            }
            for c, a in assignments.items()
            if talk.get(c)
        ]
        speakers.sort(key=lambda x: x["talk_seconds"], reverse=True)
        note = None
        note_path = r.get("note_path")
        if note_path and Path(note_path).exists():
            text = Path(note_path).read_text(encoding="utf-8")
            note = {
                "path": note_path,
                "markdown": text,
                "html": note_to_html(text),
                "obsidian_url": "obsidian://open?path=" + quote(note_path),
            }
        notes = r.get("_notes") or {}
        return {
            **dashboard.meeting_row(r),
            "attendees": r.get("attendees", []),
            "speakers": speakers,
            "turns": [
                {
                    **t,
                    "label": label(assignments[t["speaker"]])
                    if t["speaker"] in assignments
                    else t["speaker"],
                }
                for t in r.get("turns", [])
            ],
            "decisions": notes.get("decisions", []),
            "topics": notes.get("topics", []),
            "open_questions": notes.get("open_questions", []),
            "tasks": [vars(t) for t in dashboard.meeting_tasks(r)],
            "note": note,
            "models": {"asr": r.get("asr_model"), "diarization": r.get("diarization_model")},
        }

    @app.patch("/api/meetings/{meeting_id}")
    def rename_meeting(meeting_id: str, body: MeetingTitleBody) -> dict[str, str]:
        with project_lock:
            related = [
                s
                for s in manager.sessions.values()
                if s.record is not None and s.record.id == meeting_id
            ]
            if any(s.state in ACTIVE_STATES | {"review"} for s in related):
                raise HTTPException(409, "Finish processing this meeting before renaming it")
            try:
                title = pipeline.rename_meeting(meeting_id, body.title)
            except FileNotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            for session in related:
                session.record.title = title
                session.record.title_pending = False
                session.meta.title = title
            return {"id": meeting_id, "title": title}

    @app.get("/api/meetings/{meeting_id}/audio")
    def meeting_audio(meeting_id: str) -> FileResponse:
        """The meeting recording, with range support so the player can seek."""
        r = record_or_404(meeting_id)
        candidates = [Path(r.get("source_audio") or "")]
        if sha := r.get("audio_sha"):
            candidates.append(cfg.cache_dir / sha[:16] / "audio.wav")  # normalised copy
        for path in candidates:
            if path.is_file():
                return FileResponse(path, media_type=_audio_type(path))
        raise HTTPException(404, "The recording for this meeting is no longer on disk")

    @app.post("/api/meetings/{meeting_id}/tasks/{line}")
    @meeting_locked
    def set_task(meeting_id: str, line: int, body: TaskBody) -> dict[str, Any]:
        r = record_or_404(meeting_id)
        task_manager.sync(r)
        task = next((task for task in dashboard.meeting_tasks(r) if task.line == line), None)
        if task is None:
            raise HTTPException(409, "That task no longer exists. Refresh the task list")
        try:
            task_manager.update(task.id, done=body.done)
        except (TaskConflict, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"done": body.done}

    @app.get("/api/tasks")
    def tasks() -> list[dict[str, Any]]:
        return task_manager.list()

    @app.patch("/api/tasks/{task_id}")
    def update_task(task_id: str, body: TaskUpdate) -> dict[str, Any]:
        if body.done is None and body.reminder_date is None:
            raise HTTPException(400, "Choose a completion state or reminder date")
        try:
            return task_manager.update(
                task_id,
                done=body.done,
                reminder_date=body.reminder_date.isoformat() if body.reminder_date else None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (TaskConflict, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, "Could not save the task. Check storage permissions") from exc

    @app.get("/api/projects")
    def projects() -> list[dict[str, Any]]:
        stats = {
            p["name"]: p
            for p in dashboard.build_dashboard(dashboard.load_records(cfg.meetings_dir), 0)[
                "projects"
            ]
        }
        vault = pipeline.vault
        names = set(stats)
        if vault.projects_dir.is_dir():
            names |= {
                p.name
                for p in vault.projects_dir.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            }
        out = []
        for name in names:
            st = stats.get(name, {"meetings": 0, "minutes": 0.0, "last": None})
            out.append(
                {
                    "name": name,
                    "meetings": st["meetings"],
                    "minutes": round(st["minutes"], 1),
                    "last": st["last"],
                    "overview": vault.project_context(name),
                }
            )

        def recent(project):
            folder = vault.project_dir(project["name"])
            overview = folder / f"{safe_filename(project['name'])}.md"
            modified = max((p.stat().st_mtime for p in (folder, overview) if p.exists()), default=0)
            try:
                last = datetime.fromisoformat(project["last"]).timestamp() if project["last"] else 0
            except ValueError:
                last = 0
            return max(modified, last), project["name"]

        return sorted(out, key=recent, reverse=True)

    @app.post("/api/projects")
    def create_project(body: ProjectBody) -> dict[str, Any]:
        """Create a project folder with its overview note. Creating an existing one is a no-op,
        so the caller can simply select it."""
        name = safe_filename(body.name.strip())
        if not body.name.strip() or len(name) > 100:
            raise HTTPException(400, "Give the project a name of up to 100 characters")
        vault = pipeline.vault
        created = not (vault.project_dir(name) / f"{name}.md").exists()
        vault.ensure_project(name)
        return {"name": name, "created": created}

    def project_idle(name: str) -> None:
        for session in manager.sessions.values():
            project = session.record.project if session.record else session.meta.project
            if (
                project
                and safe_filename(project) == name
                and session.state
                not in {
                    "done",
                    "error",
                    "cancelled",
                }
            ):
                raise HTTPException(409, "Finish or cancel this project's active meeting first")

    def project_error(exc: Exception) -> HTTPException:
        if isinstance(exc, FileNotFoundError):
            return HTTPException(404, str(exc))
        if isinstance(exc, ProjectConflict):
            return HTTPException(409, str(exc))
        if isinstance(exc, ValueError):
            return HTTPException(400, str(exc))
        return HTTPException(
            500, "Could not change this project. Check vault file permissions and retry"
        )

    @app.get("/api/projects/{name}")
    def project_details(name: str) -> dict[str, Any]:
        try:
            return project_manager.details(name)
        except (ValueError, OSError) as exc:
            raise project_error(exc) from exc

    @app.get("/api/projects/{name}/overview")
    def project_overview(name: str) -> dict[str, Any]:
        with project_lock:
            try:
                return project_manager.overview(name, task_manager)
            except (ValueError, OSError, YAMLError) as exc:
                raise project_error(exc) from exc

    @app.put("/api/projects/{name}/members")
    def project_members(name: str, body: ProjectMembersBody) -> dict[str, list[str]]:
        with project_lock:
            try:
                return {"members": project_manager.set_members(name, body.members)}
            except (ValueError, OSError) as exc:
                raise project_error(exc) from exc

    @app.patch("/api/projects/{name}")
    def rename_project(name: str, body: ProjectBody) -> dict[str, Any]:
        with project_lock:
            project_idle(name)
            try:
                result = project_manager.rename(name, body.name)
            except (ValueError, OSError, sqlite3.Error) as exc:
                raise project_error(exc) from exc
            for session in manager.sessions.values():
                project = session.record.project if session.record else session.meta.project
                if project and safe_filename(project) == name:
                    session.meta.project = result["name"]
                    if session.record:
                        updated, _ = pipeline.load_record(session.record.id)
                        session.record.project = updated.project
                        session.record.note_path = updated.note_path
                        session.record.source_audio = updated.source_audio
                        session.note_path = Path(updated.note_path) if updated.note_path else None
            return result

    @app.delete("/api/projects/{name}")
    def delete_project(name: str, body: DeleteProjectBody) -> dict[str, Any]:
        with project_lock:
            project_idle(name)
            try:
                result = project_manager.delete(name, body.meeting_ids)
            except (ValueError, OSError, sqlite3.Error) as exc:
                raise project_error(exc) from exc
            ids = set(result["meeting_ids"])
            for sid, session in list(manager.sessions.items()):
                if (session.record and session.record.id in ids) or (
                    session.meta.project and safe_filename(session.meta.project) == name
                ):
                    del manager.sessions[sid]
            return result

    @app.post("/api/meetings/{meeting_id}/open")
    def open_meeting(meeting_id: str) -> dict[str, str]:
        try:
            return {"id": manager.open_existing(meeting_id).id}
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.delete("/api/meetings/{meeting_id}")
    def delete_meeting(meeting_id: str) -> dict[str, bool]:
        if any(
            s.record is not None and s.record.id == meeting_id and s.state in ACTIVE_STATES
            for s in manager.sessions.values()
        ):
            raise HTTPException(409, "This meeting is still being processed")
        try:
            pipeline.delete_record(meeting_id, manager.recordings_dir)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        for sid in [
            sid
            for sid, s in manager.sessions.items()
            if s.record is not None and s.record.id == meeting_id
        ]:
            del manager.sessions[sid]
        return {"deleted": True}

    @app.get("/api/speakers")
    def speakers() -> list[dict[str, Any]]:
        talk: dict[str, float] = {}
        meetings_with: dict[str, int] = {}
        for r in dashboard.load_records(cfg.meetings_dir):
            for name, seconds in dashboard.speaking_by_name(r).items():
                talk[name] = talk.get(name, 0.0) + seconds
                meetings_with[name] = meetings_with.get(name, 0) + 1
        return [
            {
                "name": s.name,
                "samples": s.samples,
                "consent": s.consent,
                "minutes": round(talk.get(s.name, 0.0) / 60, 1),
                "meetings": meetings_with.get(s.name, 0),
                **pipeline.vault.person_profile(s.name),
            }
            for s in pipeline.store.list()
        ]

    @app.post("/api/people")
    def save_person(body: PersonBody) -> dict[str, Any]:
        if not body.name.strip():
            raise HTTPException(400, "A name is required")
        pipeline.vault.ensure_person(
            body.name.strip(), role=body.role, organisation=body.organisation, bio=body.bio
        )
        return {"name": body.name.strip(), **pipeline.vault.person_profile(body.name.strip())}

    @app.post("/api/speakers/rename")
    def rename_speaker(body: RenameBody) -> dict[str, str]:
        try:
            pipeline.store.rename(body.old, body.new)
        except KeyError as exc:
            raise HTTPException(404, f"No voice called {body.old}") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        pipeline.vault.rename_person(body.old, body.new)
        return {"name": body.new}

    @app.delete("/api/speakers/{name}")
    def forget_speaker(name: str) -> dict[str, bool]:
        if not pipeline.store.forget(name):
            raise HTTPException(404, f"No voice called {name}")
        return {"forgotten": True}

    def chat_or_404(chat_id: str) -> dict[str, Any]:
        chat = chats.get(chat_id)
        if chat is None:
            raise HTTPException(404, "This conversation was not found")
        return chat

    def chat_response(chat: dict[str, Any]) -> dict[str, Any]:
        for message in chat["messages"]:
            if message["role"] == "assistant":
                message["html"] = chat_to_html(message["content"], message["sources"])
        return chat

    @app.get("/api/chats")
    def list_chats() -> list[dict[str, Any]]:
        return chats.list()

    @app.post("/api/chats", status_code=201)
    def create_chat(body: ChatCreate) -> dict[str, Any]:
        available = {r["id"] for r in dashboard.load_records(cfg.meetings_dir)}
        if set(body.meeting_ids) - available:
            raise HTTPException(400, "One of the selected meetings no longer exists")
        return chats.create(body.meeting_ids)

    @app.get("/api/chats/{chat_id}")
    def get_chat(chat_id: str) -> dict[str, Any]:
        return chat_response(chat_or_404(chat_id))

    @app.patch("/api/chats/{chat_id}")
    def update_chat(chat_id: str, body: ChatUpdate) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True)
        for field in ("title", "pinned"):
            if field in changes and changes[field] is None:
                raise HTTPException(400, f"{field.capitalize()} cannot be empty")
        if "title" in changes:
            changes["title"] = changes["title"].strip()
            if not changes["title"]:
                raise HTTPException(400, "Give the conversation a name")
        with project_lock:
            chat_or_404(chat_id)
            if changes.get("project") is not None:
                try:
                    project_manager.details(changes["project"])
                except (ValueError, OSError) as exc:
                    raise project_error(exc) from exc
            chat = chats.update(chat_id, changes)
        if chat is None:
            raise HTTPException(404, "This conversation was not found")
        return chat_response(chat)

    @app.delete("/api/chats/{chat_id}")
    def delete_chat(chat_id: str) -> dict[str, bool]:
        if chat_id in answering:
            raise HTTPException(409, "Wait for this conversation's answer before deleting it")
        if not chats.delete(chat_id):
            raise HTTPException(404, "This conversation was not found")
        return {"deleted": True}

    @app.post("/api/chats/{chat_id}/messages")
    async def ask_chat(chat_id: str, body: ChatQuestion) -> dict[str, Any]:
        question = body.message.strip()
        if not question:
            raise HTTPException(400, "Write a question first")
        chat = chat_or_404(chat_id)
        if chat_id in answering:
            raise HTTPException(409, "An answer is already being prepared for this conversation")
        answering.add(chat_id)
        try:
            result = await asyncio.to_thread(
                answer_question,
                pipeline.llm,
                cfg.meetings_dir,
                chat,
                question,
            )
            saved = await asyncio.to_thread(
                chats.append,
                chat_id,
                question,
                result,
                len(chat["messages"]),
            )
            return chat_response(saved)
        except LLMError as exc:
            raise HTTPException(
                502,
                "The configured model could not answer. Check Settings and try again.",
            ) from exc
        except ChatConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            answering.discard(chat_id)

    @app.post("/api/chats/{chat_id}/messages/stream")
    async def stream_chat(chat_id: str, body: ChatQuestion) -> StreamingResponse:
        question = body.message.strip()
        if not question:
            raise HTTPException(400, "Write a question first")
        chat = chat_or_404(chat_id)
        if chat_id in answering:
            raise HTTPException(409, "An answer is already being prepared for this conversation")
        answering.add(chat_id)
        events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=8)
        stopped = Event()

        def emit(event: dict[str, Any]) -> None:
            while not stopped.is_set():
                try:
                    events.put(event, timeout=0.2)
                    return
                except queue.Full:
                    continue
            raise LLMError("The answer stream was closed")

        def generate() -> None:
            text, last_update = "", 0.0

            def delta(part: str) -> None:
                nonlocal text, last_update
                if stopped.is_set():
                    raise LLMError("The answer stream was closed")
                text += part
                now = time.monotonic()
                if now - last_update >= 0.05:
                    emit({"type": "answer", "content": text, "html": chat_to_html(text, [])})
                    last_update = now

            try:
                result = answer_question(pipeline.llm, cfg.meetings_dir, chat, question, delta)
                if stopped.is_set():
                    return
                saved = chats.append(chat_id, question, result, len(chat["messages"]))
                emit({"type": "complete", "chat": chat_response(saved)})
            except (LLMError, ChatConflict) as exc:
                if not stopped.is_set():
                    emit(
                        {
                            "type": "error",
                            "message": str(exc)
                            if isinstance(exc, ChatConflict)
                            else (
                                "The configured model could not finish the answer. "
                                "Check Settings and try again."
                            ),
                        }
                    )
            except Exception:
                if not stopped.is_set():
                    emit(
                        {
                            "type": "error",
                            "message": "Could not save this answer. Please try again.",
                        }
                    )
            finally:
                answering.discard(chat_id)

        async def stream():
            worker = asyncio.create_task(asyncio.to_thread(generate))
            try:
                yield (
                    json.dumps({"type": "status", "message": "Reading your meeting notes…"}) + "\n"
                )
                while True:
                    try:
                        event = await asyncio.to_thread(events.get, True, 0.5)
                    except queue.Empty:
                        continue
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                    if event["type"] in {"complete", "error"}:
                        break
            finally:
                stopped.set()
                # The worker owns the reservation until the model connection is closed.
                # Observe its task without cancelling the underlying synchronous request.
                worker.add_done_callback(
                    lambda task: task.exception() if not task.cancelled() else None
                )

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # mounted last so the API routes above take precedence
    if web is not None:
        app.mount("/", StaticFiles(directory=web, html=True), name="web")

    return app
