"""Command-line interface.

dzomdu init --vault ~/DzomduVault
dzomdu process meeting.m4a --project "Solar Microgrid" -a "Karma Wangmo" -a "Tenzin Dorji"
dzomdu regenerate <meeting-id> --template board
dzomdu speakers list | enroll | rename | forget
dzomdu people add "Karma Wangmo" --role "Project manager"
dzomdu bench all --manifest bench/manifest.yaml
dzomdu doctor
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .audio import write_wav
from .config import (
    ASR_PACKAGES,
    Config,
    default_config_path,
    dump_config,
    is_installed,
    load_config,
)
from .llm.client import LLMClient, LLMError
from .models import format_duration, format_timestamp
from .pipeline import Analysis, Pipeline
from .vault import Vault

app = typer.Typer(
    help="Dzomdu: offline meeting notes with speaker recognition.",
    no_args_is_help=True,
    add_completion=False,
)
speakers_app = typer.Typer(help="Manage remembered voices.", no_args_is_help=True)
people_app = typer.Typer(help="Manage people profiles in the vault.", no_args_is_help=True)
app.add_typer(speakers_app, name="speakers")
app.add_typer(people_app, name="people")

console = Console()
err = Console(stderr=True)

ConfigOpt = Annotated[
    Path | None, typer.Option("--config", "-c", help="Config file (default: ~/.config/dzomdu)")
]


def _cfg(path: Path | None) -> Config:
    try:
        return load_config(path)
    except (ValueError, OSError) as exc:
        err.print(f"[red]Config error:[/] {exc}")
        raise typer.Exit(2) from exc


def _fail(msg: str, code: int = 1) -> typer.Exit:
    err.print(f"[red]Error:[/] {msg}")
    return typer.Exit(code)


# -- init -------------------------------------------------------------------------------------


DEFAULT_VAULT = Path.home() / "DzomduVault"


@app.command()
def init(
    vault: Annotated[
        Path, typer.Option(help="Where meeting notes are stored (Obsidian vault)")
    ] = DEFAULT_VAULT,
    config: ConfigOpt = None,
    force: Annotated[bool, typer.Option(help="Overwrite an existing config file")] = False,
) -> None:
    """Create the config file and the vault folders."""
    path = config or default_config_path()
    if path.exists() and not force:
        cfg = _cfg(path)
        console.print(f"Config already exists at [bold]{path}[/] (use --force to replace).")
    else:
        cfg = Config(vault=vault.expanduser().resolve())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_config(cfg), encoding="utf-8")
        console.print(f"Wrote config to [bold]{path}[/]")
    Vault(cfg.vault).init()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"Vault ready at [bold]{cfg.vault}[/] (open this folder in Obsidian)")
    console.print(f"App data (voiceprints, caches) at [bold]{cfg.data_dir}[/]")
    console.print("Next: run [bold]dzomdu doctor[/] to check models and the LLM.")


# -- process ----------------------------------------------------------------------------------


def _play(analysis: Analysis, cluster: str) -> None:
    voice = analysis.voices.get(cluster)
    if not voice or not voice.clip:
        console.print("  (no clip available)")
        return
    player = next(
        (
            [p, *args]
            for p, args in (
                ("afplay", []),
                ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
                ("aplay", ["-q"]),
            )
            if shutil.which(p)
        ),
        None,
    )
    if player is None:
        console.print("  (no audio player found: install ffmpeg)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "clip.wav"
        write_wav(path, analysis.audio.slice(*voice.clip), analysis.audio.sample_rate)
        subprocess.run([*player, str(path)], check=False)


def _review(analysis: Analysis, pipe: Pipeline) -> dict[str, str | None]:
    """Ask who each speaker is. Enter accepts the suggestion, p plays a clip, - skips."""
    record = analysis.record
    known = {s.name.casefold(): s.name for s in pipe.store.list()}
    known |= {a.casefold(): a for a in record.attendees}
    talk = record.speaking_time()
    clusters = list(dict.fromkeys(t.speaker for t in record.turns))
    decisions: dict[str, str | None] = {}
    console.rule("Who said what?")
    console.print(
        "[dim]Enter = accept · type a name · p = play voice clip · - = leave unidentified[/]"
    )
    for n, cluster in enumerate(clusters, 1):
        a = record.assignments[cluster]
        quotes = sorted(
            (t for t in record.turns if t.speaker == cluster),
            key=lambda t: len(t.text),
            reverse=True,
        )[:2]
        guess = {
            "auto": f"[green]{escape(a.name or '')}[/] (match {a.score:.2f})",
            "suggested": f"[yellow]{escape(a.suggestion or '')}?[/] (match {a.score:.2f})",
        }.get(a.status, "[red]unknown voice[/]" + (f" (best {a.score:.2f})" if a.score else ""))
        console.print(
            f"\n[bold]Speaker {n}/{len(clusters)}[/] · spoke "
            f"{format_duration(talk.get(cluster, 0))} · {guess}"
        )
        for q in quotes:
            snippet = q.text if len(q.text) < 160 else q.text[:157] + "…"
            console.print(f"  [dim]{format_timestamp(q.start)}[/] “{escape(snippet)}”")
        default = a.name or a.suggestion or ""
        while True:
            answer = typer.prompt("  Who is this?", default=default or "-", show_default=True)
            answer = answer.strip()
            if answer.lower() in ("p", "play"):
                _play(analysis, cluster)
                continue
            break
        if answer in ("-", ""):
            decisions[cluster] = None
            continue
        name = known.get(answer.casefold(), answer)
        if name.casefold() not in known:
            console.print(f"  New person: [bold]{escape(name)}[/] (profile created in People/)")
            known[name.casefold()] = name
        decisions[cluster] = name
    return decisions


@app.command()
def process(
    audio: Annotated[Path, typer.Argument(help="Recording (any format ffmpeg can read)")],
    project: Annotated[str | None, typer.Option("--project", "-p")] = None,
    title: Annotated[str | None, typer.Option("--title", "-t")] = None,
    attendee: Annotated[
        list[str] | None,
        typer.Option(
            "--attendee",
            "-a",
            help="Expected attendee (repeatable). Narrows voice matching to these people.",
        ),
    ] = None,
    date: Annotated[str | None, typer.Option(help="Meeting start, e.g. 2026-10-07T10:00")] = None,
    template: Annotated[str | None, typer.Option("--template", "-T")] = None,
    instructions: Annotated[
        str | None, typer.Option("--instructions", "-i", help="Extra style request for the LLM")
    ] = None,
    num_speakers: Annotated[int | None, typer.Option(help="Exact number of speakers")] = None,
    min_speakers: Annotated[int | None, typer.Option()] = None,
    max_speakers: Annotated[int | None, typer.Option()] = None,
    review: Annotated[bool, typer.Option(help="Confirm speakers interactively")] = True,
    llm: Annotated[bool, typer.Option(help="Generate summary and minutes")] = True,
    fresh: Annotated[bool, typer.Option(help="Ignore cached transcription/diarization")] = False,
    config: ConfigOpt = None,
) -> None:
    """Transcribe a recording, identify speakers and write meeting notes to the vault."""
    cfg = _cfg(config)
    try:
        when = datetime.fromisoformat(date) if date else None
    except ValueError as exc:
        raise _fail(f"Invalid --date {date!r} (use YYYY-MM-DDTHH:MM)") from exc
    with console.status("Starting…") as status:
        pipe = Pipeline(cfg, progress=lambda m: status.update(m))
        try:
            tmpl = pipe.template(template)
        except KeyError as exc:
            raise _fail(str(exc.args[0])) from exc
        try:
            analysis = pipe.analyze(
                audio,
                title=title,
                date=when,
                project=project,
                attendees=attendee,
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                fresh=fresh,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise _fail(str(exc)) from exc

    record = analysis.record
    n_speakers = len({t.speaker for t in record.turns})
    console.print(
        f"Transcribed [bold]{format_duration(record.duration)}[/]: {len(record.turns)} turns, "
        f"{n_speakers} speaker(s)."
    )
    if not record.turns:
        console.print("[yellow]No speech found.[/]")

    if review and record.turns and sys.stdin.isatty():
        pipe.apply_review(analysis, _review(analysis, pipe))
        learned = pipe.learn(analysis)
        if learned:
            console.print(f"Remembered voices: {', '.join(learned)}")
    else:
        pipe.learn(analysis)  # logs feedback only; nothing unconfirmed is learned
        for a in record.assignments.values():
            if a.status == "suggested":
                console.print(
                    f"[yellow]Unconfirmed:[/] {a.unknown_label} might be "
                    f"{a.suggestion} ({a.score:.2f})"
                )

    notes = None
    if llm and record.turns:
        with console.status(f"Writing notes with {cfg.llm.model}…") as status:
            pipe.progress = lambda m: status.update(m)
            try:
                notes = pipe.summarize(record, tmpl, instructions or "")
            except LLMError as exc:
                err.print(f"[yellow]Summary skipped:[/] {exc}")
                err.print(f"Fix the LLM, then run: dzomdu regenerate {record.id}")
    path = pipe.write_note(record, notes, tmpl if notes else None)
    console.print(f"\n[green]Saved[/] {path}")
    console.print(f"[dim]Meeting id: {record.id}[/]")


@app.command()
def regenerate(
    meeting_id: Annotated[str, typer.Argument(help="Id printed by `process`")],
    template: Annotated[str | None, typer.Option("--template", "-T")] = None,
    instructions: Annotated[str | None, typer.Option("--instructions", "-i")] = None,
    new_file: Annotated[bool, typer.Option(help="Write a new note instead of replacing")] = False,
    force: Annotated[bool, typer.Option(help="Replace even if the note was edited")] = False,
    config: ConfigOpt = None,
) -> None:
    """Re-run the summary (e.g. with another template) without re-processing the audio."""
    cfg = _cfg(config)
    pipe = Pipeline(cfg)
    try:
        record, note_sha = pipe.load_record(meeting_id)
        tmpl = pipe.template(template)
    except (FileNotFoundError, KeyError) as exc:
        raise _fail(str(exc)) from exc
    if not new_file and not force and pipe.note_was_edited(record, note_sha):
        raise _fail(
            f"{record.note_path} was edited since it was generated. Use --new-file to "
            "keep both, or --force to replace it."
        )
    with console.status(f"Writing notes with {cfg.llm.model}…") as status:
        pipe.progress = lambda m: status.update(m)
        try:
            notes = pipe.summarize(record, tmpl, instructions or "")
        except LLMError as exc:
            raise _fail(str(exc)) from exc
    path = pipe.write_note(record, notes, tmpl, overwrite=not new_file)
    console.print(f"[green]Saved[/] {path}")


@app.command()
def templates(config: ConfigOpt = None) -> None:
    """List minutes templates (add your own in the vault's Templates/Minutes folder)."""
    from .notes.templates import list_templates

    cfg = _cfg(config)
    table = Table("Key", "Name", "Description", "Source")
    for t in list_templates(Vault(cfg.vault).templates_dir):
        source = "vault" if t.source != "built-in" else "built-in"
        table.add_row(t.key, t.name, t.description, source)
    console.print(table)


# -- speakers ---------------------------------------------------------------------------------


@speakers_app.command("list")
def speakers_list(config: ConfigOpt = None) -> None:
    """Show remembered voices."""
    cfg = _cfg(config)
    pipe = Pipeline(cfg)
    table = Table("Name", "Voice samples", "Consent")
    for s in pipe.store.list():
        table.add_row(s.name, str(s.samples), "yes" if s.consent else "—")
    console.print(table)


@speakers_app.command("enroll")
def speakers_enroll(
    name: str,
    audio: Path,
    start: Annotated[float | None, typer.Option(help="Start (s) of this person's speech")] = None,
    end: Annotated[float | None, typer.Option(help="End (s) of this person's speech")] = None,
    consent: Annotated[bool, typer.Option(help="Person agreed to voice storage")] = False,
    config: ConfigOpt = None,
) -> None:
    """Add a voice sample from a recording of one person (20-30 s of natural speech)."""
    cfg = _cfg(config)
    pipe = Pipeline(cfg)
    try:
        with console.status("Computing voiceprint…"):
            pipe.enroll(name, audio, start, end, consent)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    console.print(f"[green]Enrolled[/] {name}")


@speakers_app.command("rename")
def speakers_rename(old: str, new: str, config: ConfigOpt = None) -> None:
    """Rename a person (voiceprints and People note)."""
    cfg = _cfg(config)
    pipe = Pipeline(cfg)
    try:
        pipe.store.rename(old, new)
    except (KeyError, ValueError) as exc:
        raise _fail(f"Cannot rename: {exc}") from exc
    pipe.vault.rename_person(old, new)
    console.print(f"Renamed {old} → {new}. Existing meeting notes keep the old name.")


@speakers_app.command("forget")
def speakers_forget(
    name: str,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    config: ConfigOpt = None,
) -> None:
    """Delete a person's voiceprints and voice clips (their People note is kept)."""
    cfg = _cfg(config)
    if not yes and not typer.confirm(f"Delete all voice data for {name}?"):
        raise typer.Exit(1)
    if Pipeline(cfg).store.forget(name):
        console.print(f"Forgot {name}'s voice.")
    else:
        raise _fail(f"No remembered voice called {name}")


# -- people -----------------------------------------------------------------------------------


@people_app.command("add")
def people_add(
    name: str,
    role: Annotated[str | None, typer.Option()] = None,
    organisation: Annotated[str | None, typer.Option("--org")] = None,
    bio: Annotated[str | None, typer.Option()] = None,
    config: ConfigOpt = None,
) -> None:
    """Create or update a person's profile note (role and bio are used as LLM context)."""
    cfg = _cfg(config)
    path = Vault(cfg.vault).ensure_person(name, role=role, organisation=organisation, bio=bio)
    console.print(f"[green]Saved[/] {path}")


# -- doctor -----------------------------------------------------------------------------------


@app.command()
def doctor(config: ConfigOpt = None) -> None:
    """Check that everything needed is installed and reachable."""
    cfg = _cfg(config)
    ok = True

    def check(label: str, passed: bool, detail: str = "", required: bool = True) -> None:
        nonlocal ok
        mark = "[green]✓[/]" if passed else ("[red]✗[/]" if required else "[yellow]![/]")
        console.print(f"{mark} {label}" + (f" [dim]— {escape(detail)}[/]" if detail else ""))
        ok &= passed or not required

    console.print(f"Config: {default_config_path() if config is None else config}")
    mac = sys.platform == "darwin" and platform.machine() == "arm64"
    check("Apple Silicon Mac", mac, platform.platform(), required=False)
    has_ffmpeg = shutil.which("ffmpeg") is not None
    check("ffmpeg", has_ffmpeg, "" if has_ffmpeg else "brew install ffmpeg")

    asr_pkg = ASR_PACKAGES.get(cfg.asr.backend)
    if asr_pkg:
        check(
            f"ASR backend '{cfg.asr.backend}'",
            is_installed(asr_pkg),
            "pip install -e '.[mac]'"
            if asr_pkg != "faster_whisper"
            else "pip install -e '.[whisper]'",
        )
    check(
        "Diarization (pyannote.audio)",
        is_installed("pyannote.audio"),
        "pip install -e '.[diarize]'",
    )
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    repo_dir = hf_home / "hub" / ("models--" + cfg.diarization.model.replace("/", "--"))
    # a failed download can leave an empty folder behind, so look for the actual config
    if any(repo_dir.glob("snapshots/*/config.yaml")):
        available, detail = True, "downloaded"
    elif is_installed("pyannote.audio"):
        from .diarize.pyannote import access_problem

        token = os.environ.get(cfg.diarization.hf_token_env) or None
        problem = access_problem(cfg.diarization.model, token)
        available, detail = problem is None, problem or "access confirmed; downloads on first use"
    else:
        available, detail = (
            False,
            (
                f"accept the terms at huggingface.co/{cfg.diarization.model}, then run "
                "`hf auth login` once"
            ),
        )
    check("Diarization model available", available, detail)

    reachable, detail = LLMClient(cfg.llm).ping()
    check(f"LLM ({cfg.llm.api} @ {cfg.llm.base_url})", reachable, detail, required=False)
    check("Vault", cfg.vault.exists(), str(cfg.vault))
    raise typer.Exit(0 if ok else 1)


# -- web UI -----------------------------------------------------------------------------------


@app.command()
def ui(
    port: Annotated[int, typer.Option()] = 8765,
    host: Annotated[
        str, typer.Option(help="127.0.0.1 keeps it private to this computer")
    ] = "127.0.0.1",
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
    config: ConfigOpt = None,
) -> None:
    """Start the web interface: record, review speakers and read notes in the browser."""
    import threading
    import webbrowser

    import uvicorn

    from .server.app import create_app, web_dir

    cfg = _cfg(config)
    if web_dir() is None:
        console.print(
            "[yellow]Dashboard not built yet[/] - showing the classic interface. "
            "Build it once with: [bold]cd web && npm install && npm run build[/]"
        )
    if not cfg.vault.exists():
        console.print(f"Creating vault at [bold]{cfg.vault}[/] (run `dzomdu init` to change it)")
    app_ = create_app(cfg)
    # browsers only allow microphone access on https or "localhost"
    url = (
        f"http://localhost:{port}"
        if host in ("127.0.0.1", "localhost")
        else f"http://{host}:{port}"
    )
    console.print(f"Dzomdu is running at [bold]{url}[/]  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app_, host=host, port=port, log_level="warning")


# -- bench ------------------------------------------------------------------------------------


@app.command()
def bench(
    which: Annotated[str, typer.Argument(help="asr | diarization | speaker-id | llm | all")],
    manifest: Annotated[Path, typer.Option("--manifest", "-m")] = Path("bench/manifest.yaml"),
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("bench_out"),
    config: ConfigOpt = None,
) -> None:
    """Phase 0 benchmarks on your own labelled recordings (see bench/README.md)."""
    from .bench.runner import BENCHES, load_manifest

    cfg = _cfg(config)
    if not manifest.exists():
        raise _fail(f"{manifest} not found. Copy bench/manifest.example.yaml to start.")
    selected = list(BENCHES) if which == "all" else [which]
    if any(s not in BENCHES for s in selected):
        raise _fail(f"Unknown benchmark {which!r}. Choose from: {', '.join(BENCHES)}, all")
    spec = load_manifest(manifest)
    out.mkdir(parents=True, exist_ok=True)
    sections = []
    with console.status("Benchmarking…") as status:
        for name in selected:
            section = BENCHES[name](cfg, spec, out, lambda m: status.update(m))
            (out / f"{name}.md").write_text(section, encoding="utf-8")
            sections.append(section)
    report = out / "report.md"
    header = f"# Dzomdu benchmark report\n\nGenerated {datetime.now():%Y-%m-%d %H:%M}\n\n"
    report.write_text(header + "\n".join(sections), encoding="utf-8")
    console.print("\n".join(sections))
    console.print(f"[green]Report:[/] {report}")


if __name__ == "__main__":  # pragma: no cover
    app()
