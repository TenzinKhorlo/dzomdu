"""HTTP + WebSocket API for the local web UI. Binds to localhost only by default."""

from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from ..audio import wav_bytes
from ..config import ASR_PACKAGES, Config, is_installed
from ..llm.client import LLMClient
from ..notes.templates import list_templates
from ..pipeline import Pipeline
from .markdown import note_to_html
from .sessions import ACTIVE_STATES, SessionManager, SessionMeta

STATIC = Path(__file__).parent / "static"
UPLOAD_SUFFIXES = {".wav", ".m4a", ".mp3", ".mp4", ".mov", ".aac", ".flac", ".ogg", ".opus",
                   ".webm", ".mkv", ".wma", ".aiff", ".aif"}  # fmt: skip


class ReviewBody(BaseModel):
    names: dict[str, str | None]


class RegenerateBody(BaseModel):
    template: str | None = None
    instructions: str = ""
    force: bool = False


class RenameBody(BaseModel):
    old: str
    new: str


def create_app(cfg: Config, pipeline: Pipeline | None = None) -> FastAPI:
    pipeline = pipeline or Pipeline(cfg)
    pipeline.vault.init()
    manager = SessionManager(cfg, pipeline)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        manager.shutdown()

    app = FastAPI(title="Dzomdu", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.manager = manager

    def session_or_404(sid: str):
        try:
            return manager.get(sid)
        except KeyError:
            raise HTTPException(404, "No such session") from None

    # -- app shell --------------------------------------------------------------------------

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
    def get_session(sid: str, live_since: int = 0) -> dict[str, Any]:
        return manager.snapshot(session_or_404(sid), live_since)

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
        done = []
        for path in cfg.meetings_dir.glob("*.json") if cfg.meetings_dir.is_dir() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            assignments = data.get("assignments", {}).values()
            done.append(
                {
                    "id": data["id"],
                    "title": data.get("title") or "Untitled",
                    "date": data.get("date"),
                    "project": data.get("project"),
                    "duration": data.get("duration"),
                    "people": sorted({a["name"] for a in assignments if a.get("name")}),
                }
            )
        active = [
            {"id": s.id, "title": s.meta.title or "New meeting", "state": s.state}
            for s in manager.sessions.values()
            if s.state in ACTIVE_STATES | {"review"}
        ]
        done.sort(key=lambda m: m["date"] or "", reverse=True)
        return {"meetings": done, "active": active}

    @app.post("/api/meetings/{meeting_id}/open")
    def open_meeting(meeting_id: str) -> dict[str, str]:
        try:
            return {"id": manager.open_existing(meeting_id).id}
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/speakers")
    def speakers() -> list[dict[str, Any]]:
        return [
            {"name": s.name, "samples": s.samples, "consent": s.consent}
            for s in pipeline.store.list()
        ]

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

    return app
