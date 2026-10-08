"""HTTP + WebSocket API for the local web UI. Binds to localhost only by default."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from .. import dashboard
from ..audio import wav_bytes
from ..config import (
    ASR_PACKAGES,
    Config,
    LLMConfig,
    default_config_path,
    is_installed,
    save_config,
)
from ..llm.client import LLMClient
from ..notes.templates import list_templates
from ..pipeline import Pipeline
from ..vault import Vault, safe_filename
from .markdown import note_to_html
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


class ProjectBody(BaseModel):
    name: str


class RenameBody(BaseModel):
    old: str
    new: str


def create_app(
    cfg: Config, pipeline: Pipeline | None = None, config_path: Path | None = None
) -> FastAPI:
    pipeline = pipeline or Pipeline(cfg)
    pipeline.vault.init()
    manager = SessionManager(cfg, pipeline)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(title="Dzomdu", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager
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
        projects = sorted(p.name for p in vault.projects_dir.glob("*") if p.is_dir())
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
                "asr": cfg.asr.backend,
                "diarization": cfg.diarization.model,
                "llm": cfg.llm.model,
            },
            "status": {
                "llm": {"ok": llm_ok, "detail": llm_detail},
                "asr": {"ok": asr_pkg is None or is_installed(asr_pkg)},
                "diarization": {
                    "ok": cfg.diarization.backend != "pyannote" or is_installed("pyannote.audio")
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

    # -- sessions ---------------------------------------------------------------------------

    @app.post("/api/sessions")
    def create_session(meta: dict[str, Any]) -> dict[str, str]:
        if any(s.state == "recording" for s in manager.sessions.values()):
            raise HTTPException(409, "A recording is already in progress")
        return {"id": manager.create(SessionMeta.from_dict(meta), "recording").id}

    @app.websocket("/api/sessions/{sid}/audio")
    async def audio(ws: WebSocket, sid: str) -> None:
        await ws.accept()
        try:
            s = manager.get(sid)
            manager.start_recording(s)
        except (KeyError, ValueError) as exc:
            await ws.close(code=4400, reason=str(exc))
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
        try:
            await ws.close()
        except RuntimeError:
            pass

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
        s = manager.create(SessionMeta.from_dict(meta_dict), "upload")
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
    def dashboard_data(days: int = 30) -> dict[str, Any]:
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
    def meeting_detail(meeting_id: str) -> dict[str, Any]:
        r = record_or_404(meeting_id)
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
    def set_task(meeting_id: str, line: int, body: TaskBody) -> dict[str, Any]:
        r = record_or_404(meeting_id)
        note_path = r.get("note_path")
        if not note_path or not Path(note_path).exists():
            raise HTTPException(404, "This meeting has no note")
        try:
            dashboard.set_task_done(Path(note_path), line, body.done)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        pipeline.note_changed_by_app(meeting_id)
        return {"done": body.done}

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
            names |= {p.name for p in vault.projects_dir.iterdir() if p.is_dir()}
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
        return sorted(out, key=lambda p: (p["last"] or "", p["name"]), reverse=True)

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

    # mounted last so the API routes above take precedence
    if web is not None:
        app.mount("/", StaticFiles(directory=web, html=True), name="web")

    return app
