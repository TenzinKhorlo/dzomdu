#!/usr/bin/env python3
"""Download or register source PGN collections under sources/raw/<name>/.

Download (needs network access to the host):
    python fetch_sources.py download --name pgnmentor --publisher "PGN Mentor" \\
        --url https://www.pgnmentor.com/players/Carlsen.zip

Register files you downloaded yourself and copied, unmodified, into sources/raw/<name>/:
    python fetch_sources.py register --name lichess_wcc2021 --publisher "Lichess broadcast" \\
        --url https://lichess.org/broadcast/... --retrieved 2026-10-16

Either way, sources/raw/<name>/source.json records the URL, the retrieval date and the SHA-256 of
every file. build_dataset.py refuses a file whose hash has changed since.

--lineage: give two sources the same lineage when one was copied from the other (for example
two mirrors of one database). Cross-checking counts lineages, not directories, so a mirror cannot
pass as independent confirmation. --priority: lower wins when choosing which copy's text becomes
the canonical game score (all copies must agree on every move anyway).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from sources_io import ARCHIVE_EXTS, PGN_EXTS, sha256_file

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "sources", "raw")


def write_meta(src_dir: str, args, urls) -> dict:
    files = []
    for root, _dirs, names in os.walk(src_dir):
        for n in sorted(names):
            if n.lower().endswith(PGN_EXTS + ARCHIVE_EXTS):
                path = os.path.join(root, n)
                files.append({"path": os.path.relpath(path, src_dir), "sha256": sha256_file(path),
                              "bytes": os.path.getsize(path)})
    if not files:
        raise SystemExit("no .pgn or .zip files in %s" % src_dir)
    meta = {"name": args.name, "publisher": args.publisher, "url": urls[0] if len(urls) == 1 else urls,
            "retrieved": args.retrieved or dt.date.today().isoformat(),
            "lineage": args.lineage or args.name, "priority": args.priority,
            "notes": args.notes or "", "files": sorted(files, key=lambda f: f["path"])}
    with open(os.path.join(src_dir, "source.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    return meta


def download(url: str, dest_dir: str, attempts: int = 4) -> str:
    name = os.path.basename(urllib.parse.urlparse(url).path) or "download.pgn"
    path = os.path.join(dest_dir, name)
    delay = 2
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "carlsen-wcc-dataset/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(path + ".part", "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(path + ".part", path)
            return path
        except Exception as e:  # report every failure, retry with backoff
            print("download %s failed (attempt %d/%d): %s" % (url, i + 1, attempts, e), file=sys.stderr)
            if i + 1 < attempts:
                time.sleep(delay)
                delay *= 2
    raise SystemExit("could not download %s" % url)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("download", "register"):
        p = sub.add_parser(cmd)
        p.add_argument("--name", required=True, help="directory name under sources/raw/")
        p.add_argument("--publisher", required=True)
        p.add_argument("--url", action="append", default=[], help="source URL (repeatable)")
        p.add_argument("--retrieved", help="retrieval date, YYYY-MM-DD (default today)")
        p.add_argument("--lineage", help="shared by sources copied from one another")
        p.add_argument("--priority", type=int, default=100)
        p.add_argument("--notes")
    sub.add_parser("list")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for name in sorted(os.listdir(RAW)) if os.path.isdir(RAW) else []:
            meta_path = os.path.join(RAW, name, "source.json")
            if os.path.exists(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                print("%-24s %-28s %d file(s)  %s" % (name, meta["publisher"], len(meta["files"]), meta["url"]))
        return 0

    if not args.url:
        raise SystemExit("--url is required: every source must say where it came from")
    src_dir = os.path.join(RAW, args.name)
    os.makedirs(src_dir, exist_ok=True)
    if args.cmd == "download":
        for url in args.url:
            print("saved", download(url, src_dir))
    meta = write_meta(src_dir, args, args.url)
    for f in meta["files"]:
        print("%s  %s" % (f["sha256"], f["path"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
