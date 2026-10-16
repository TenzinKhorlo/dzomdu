"""Reading source PGN collections: fingerprinting, decoding, and locating each game's original text.

A source is one directory under `sources/raw/` holding a `source.json` and the files exactly as
downloaded (`.pgn`, or `.zip` archives of `.pgn` files). `source.json` records where they came from
and their SHA-256; `load_source` refuses a file whose hash no longer matches, so an edited
download cannot pass as the original.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

import chess
import chess.pgn

PGN_EXTS = (".pgn",)
ARCHIVE_EXTS = (".zip",)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_pgn(data: bytes) -> Tuple[str, str]:
    """Text and the encoding used. PGN is officially Latin-1; most modern files are UTF-8."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


@dataclass
class SourceFile:
    source: str            # source directory name
    path: str              # file path relative to the source directory
    member: Optional[str]  # member name inside an archive, else None
    sha256: str            # hash of the file on disk (the archive, for a member)
    member_sha256: str     # hash of the PGN bytes themselves
    encoding: str
    text: str


@dataclass
class RawGame:
    source: str
    meta: Dict[str, Any]
    file: SourceFile
    index: int             # game index within the file, 0-based
    offset: int            # character offset of the game's text within the decoded file
    raw_pgn: str           # the game's original text, verbatim
    headers: Dict[str, str]
    game: Optional[chess.pgn.Game] = None
    errors: List[str] = field(default_factory=list)

    @property
    def locator(self) -> str:
        where = self.file.path + (("!" + self.file.member) if self.file.member else "")
        return "%s:%s#%d" % (self.source, where, self.index)


def read_source_meta(src_dir: str) -> Dict[str, Any]:
    path = os.path.join(src_dir, "source.json")
    if not os.path.exists(path):
        raise FileNotFoundError("%s has no source.json; register it with fetch_sources.py" % src_dir)
    with open(path, encoding="utf-8") as f:
        meta = json.load(f)
    for key in ("name", "publisher", "files"):
        if key not in meta:
            raise ValueError("%s: source.json lacks %r" % (src_dir, key))
    return meta


def iter_source_files(src_dir: str, meta: Dict[str, Any]) -> Iterator[SourceFile]:
    """Every PGN in a source, after checking each listed file's SHA-256 against source.json."""
    listed = {f["path"]: f for f in meta["files"]}
    on_disk = sorted(
        os.path.relpath(os.path.join(root, n), src_dir)
        for root, _dirs, names in os.walk(src_dir) for n in names
        if n.lower().endswith(PGN_EXTS + ARCHIVE_EXTS))
    unlisted = [p for p in on_disk if p not in listed]
    if unlisted:
        raise ValueError("%s: files not recorded in source.json (re-run fetch_sources.py register): %s"
                         % (src_dir, ", ".join(unlisted)))
    for rel in sorted(listed):
        path = os.path.join(src_dir, rel)
        if not os.path.exists(path):
            raise FileNotFoundError("%s: %s is listed in source.json but missing" % (src_dir, rel))
        digest = sha256_file(path)
        if digest != listed[rel]["sha256"]:
            raise ValueError("%s: %s has SHA-256 %s but source.json records %s; the file changed after "
                             "it was registered" % (src_dir, rel, digest, listed[rel]["sha256"]))
        if rel.lower().endswith(ARCHIVE_EXTS):
            with zipfile.ZipFile(path) as zf:
                for member in sorted(zf.namelist()):
                    if member.lower().endswith(PGN_EXTS):
                        data = zf.read(member)
                        text, enc = decode_pgn(data)
                        yield SourceFile(meta["name"], rel, member, digest, sha256_bytes(data), enc, text)
        else:
            with open(path, "rb") as f:
                data = f.read()
            text, enc = decode_pgn(data)
            yield SourceFile(meta["name"], rel, None, digest, digest, enc, text)


def iter_games(sf: SourceFile, meta: Dict[str, Any], want=None) -> Iterator[RawGame]:
    """Games of one file with their verbatim text. `want(headers)` filters before the full parse."""
    handle = io.StringIO(sf.text)
    index = 0
    while True:
        start = handle.tell()
        headers = chess.pgn.read_headers(handle)
        if headers is None:
            break
        end = handle.tell()
        hdrs = dict(headers)
        if want is None or want(hdrs):
            handle.seek(start)
            game = chess.pgn.read_game(handle)
            end = handle.tell()
            raw = sf.text[start:end].strip("\n\r﻿ ") + "\n"
            rg = RawGame(sf.source, meta, sf, index, start, raw, hdrs, game,
                         [str(e) for e in game.errors] if game is not None else ["unparseable"])
            yield rg
            handle.seek(end)
        index += 1


# --------------------------------------------------------------------------------- headers

def split_name(name: str) -> Tuple[str, str]:
    """(surname, first-name initial) in lower case, for 'Carlsen, Magnus', 'Carlsen,M', 'Magnus Carlsen'."""
    name = (name or "").strip()
    if "," in name:
        surname, first = name.split(",", 1)
    else:
        parts = name.split()
        if not parts:
            return "", ""
        surname, first = parts[-1], " ".join(parts[:-1])
    surname = re.sub(r"[^a-z\- ]", "", surname.strip().lower())
    first = first.strip().lower()
    return surname, (first[:1] if first else "")


def is_player(name: str, surname: str, initial: str = "") -> bool:
    s, i = split_name(name)
    return s == surname and (not initial or not i or i == initial)


def parse_date(value: Optional[str]) -> Optional[str]:
    """'2013.11.15' -> '2013-11-15'. Partial or unknown dates return None."""
    if not value:
        return None
    m = re.fullmatch(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", value.strip())
    if not m or "?" in value:
        return None
    return "%s-%s-%s" % m.groups()


def game_date(headers: Dict[str, str]) -> Optional[str]:
    return parse_date(headers.get("Date"))


def round_number(headers: Dict[str, str]) -> Optional[int]:
    m = re.match(r"\s*(\d+)", headers.get("Round", "") or "")
    return int(m.group(1)) if m else None


def time_control_class(tc: Optional[str]) -> Optional[str]:
    """'classical' / 'rapid' / 'blitz' from a PGN TimeControl tag, or None when it says nothing usable."""
    if not tc or tc.strip() in ("?", "-"):
        return None
    first = tc.split(":")[0].strip()
    m = re.fullmatch(r"(?:(\d+)/)?(\d+)(?:\+(\d+))?", first)
    if not m:
        return None
    base = int(m.group(2))
    inc = int(m.group(3) or 0)
    total = base + 60 * inc        # FIDE's convention: base + 60 x increment
    if total >= 3600:
        return "classical"
    if total >= 600:
        return "rapid"
    return "blitz"
