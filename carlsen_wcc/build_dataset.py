#!/usr/bin/env python3
"""Build the source-grounded master dataset of Magnus Carlsen's move decisions.

    python build_dataset.py                      # reads sources/raw/*, writes data/

Every game is read from the registered source PGNs (see fetch_sources.py), replayed with
python-chess, classified into a tier, and cross-checked against every other source that holds
the same game. One record is written per Carlsen move: the position before it, every legal move
described factually, and the move Carlsen actually played as the target.

Tiers (see match_registry.json):
    A  World Championship classical wins         -> data/carlsen_wcc_master.jsonl
    B  World Championship classical draws/losses -> data/carlsen_wcc_draws_losses_master.jsonl
    C  World Championship rapid/blitz tiebreaks  -> data/carlsen_wcc_tiebreaks_master.jsonl
    D  Other classical over-the-board wins       -> data/carlsen_classical_wins_master.jsonl.gz
    E  Other classical draws/losses              -> data/carlsen_classical_draws_losses_master.jsonl.gz

Nothing is repaired. A game that fails to parse, replay, or agree across sources is excluded and
listed in data/build_log.json with the reason. The exit status is 2 when any match's games
disagree with the expectations in match_registry.json, so a wrong assumption cannot pass quietly.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import chess

from chess_text import (COLOR_NAME, DEFAULT_QUESTION, describe_board, game_phase, legal_options,
                        position_key)
from sources_io import (RawGame, game_date, is_player, iter_games, iter_source_files, read_source_meta,
                        round_number, split_name, time_control_class)

HERE = os.path.dirname(os.path.abspath(__file__))

TIER_MASTER = {
    "A": "carlsen_wcc_master.jsonl",
    "B": "carlsen_wcc_draws_losses_master.jsonl",
    "C": "carlsen_wcc_tiebreaks_master.jsonl",
    "D": "carlsen_classical_wins_master.jsonl.gz",
    "E": "carlsen_classical_draws_losses_master.jsonl.gz",
}
TIER_PGN = {
    "A": "carlsen_wcc_games.pgn",
    "B": "carlsen_wcc_draws_losses_games.pgn",
    "C": "carlsen_wcc_tiebreaks_games.pgn",
    "D": "carlsen_classical_wins_games.pgn",
    "E": "carlsen_classical_draws_losses_games.pgn",
}
WCC_TIERS = ("A", "B", "C")
RESULTS = ("1-0", "0-1", "1/2-1/2")


def open_text(path: str, mode: str = "rt"):
    if path.endswith(".gz"):
        if "w" in mode:
            # mtime=0 keeps the archive byte-identical across rebuilds
            return io.TextIOWrapper(gzip.GzipFile(path, "wb", mtime=0), encoding="utf-8")
        return gzip.open(path, mode, encoding="utf-8")
    return open(path, mode, encoding="utf-8")


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    with open_text(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def short_hash(*parts: str, n: int = 8) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:n]


def norm_event(event: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (event or "").lower()).strip()


# ------------------------------------------------------------------------------- loading

class Candidate:
    """One copy of one game in one source, replayed and classified."""

    def __init__(self, rg: RawGame, player: Dict[str, str]):
        self.rg = rg
        h = rg.headers
        self.white, self.black = h.get("White", ""), h.get("Black", "")
        self.carlsen_color = ("white" if is_player(self.white, player["surname"], player["first_initial"])
                              else "black")
        self.opponent = self.black if self.carlsen_color == "white" else self.white
        self.opp_surname = split_name(self.opponent)[0]
        self.date = game_date(h)
        self.result = (h.get("Result") or "").strip()
        self.problem: Optional[str] = None
        self.ucis: List[str] = []
        self.sans: List[str] = []
        self._replay()
        self.moves_hash = short_hash(*self.ucis, n=16)
        self.kind: Optional[str] = None      # wcc_classical | wcc_tiebreak | other
        self.match: Optional[Dict[str, Any]] = None
        self.tc_basis: Optional[str] = None

    def _replay(self):
        h, g = self.rg.headers, self.rg.game
        if g is None:
            self.problem = "unparseable game"
            return
        if self.rg.errors:
            self.problem = "PGN parse errors: " + "; ".join(self.rg.errors)
            return
        variant = (h.get("Variant") or "standard").lower()
        if variant not in ("standard", "chess", "normal") or h.get("FEN") or h.get("SetUp") == "1":
            self.problem = "non-standard start (Variant/FEN/SetUp header)"
            return
        if self.result not in RESULTS:
            self.problem = "result %r is not a finished game" % self.result
            return
        board = chess.Board()
        for move in g.mainline_moves():
            if not board.is_legal(move):  # GameBuilder already rejects these; re-checked on purpose
                self.problem = "illegal move %s at ply %d" % (move.uci(), board.ply() + 1)
                return
            self.sans.append(board.san(move))
            self.ucis.append(move.uci())
            board.push(move)
        if not self.ucis:
            self.problem = "no moves"
            return
        # A finished board must not contradict the recorded result.
        outcome = board.outcome(claim_draw=False)
        if outcome is not None and outcome.termination == chess.Termination.CHECKMATE:
            mated_result = "1-0" if outcome.winner == chess.WHITE else "0-1"
            if self.result != mated_result:
                self.problem = "checkmate on the board contradicts Result %s" % self.result
        elif outcome is not None and outcome.termination in (chess.Termination.STALEMATE,
                                                             chess.Termination.INSUFFICIENT_MATERIAL):
            if self.result != "1/2-1/2":
                self.problem = "%s on the board contradicts Result %s" % (outcome.termination.name, self.result)
        self.final_fen = board.fen()

    @property
    def carlsen_result(self) -> str:
        if self.result == "1/2-1/2":
            return "draw"
        won = (self.result == "1-0") == (self.carlsen_color == "white")
        return "win" if won else "loss"


def load_candidates(sources_dir: str, registry: Dict[str, Any], log: Dict[str, Any]) -> List[Candidate]:
    player = registry["player"]

    def wants(h):
        return (is_player(h.get("White", ""), player["surname"], player["first_initial"])
                or is_player(h.get("Black", ""), player["surname"], player["first_initial"]))

    cands = []
    names = sorted(d for d in os.listdir(sources_dir) if os.path.isdir(os.path.join(sources_dir, d))) \
        if os.path.isdir(sources_dir) else []
    if not names:
        raise SystemExit("no sources under %s; download PGNs and register them with fetch_sources.py" % sources_dir)
    for name in names:
        src_dir = os.path.join(sources_dir, name)
        meta = read_source_meta(src_dir)
        stats = Counter()
        for sf in iter_source_files(src_dir, meta):
            stats["files"] += 1
            for rg in iter_games(sf, meta, want=wants):
                stats["carlsen_games_read"] += 1
                c = Candidate(rg, player)
                if is_player(c.white, player["surname"], player["first_initial"]) and \
                        is_player(c.black, player["surname"], player["first_initial"]):
                    c.problem = "both players match the Carlsen pattern"
                if c.problem:
                    stats["unusable"] += 1
                    log["unusable_copies"].append({"copy": rg.locator, "white": c.white, "black": c.black,
                                                   "date": rg.headers.get("Date"), "reason": c.problem})
                    continue
                cands.append(c)
        log["sources"].append({"name": meta["name"], "publisher": meta.get("publisher"),
                               "lineage": meta.get("lineage", meta["name"]), "priority": meta.get("priority", 100),
                               "files": meta["files"], **stats})
    return cands


# ------------------------------------------------------------------------------ classifying

def classify(c: Candidate, registry: Dict[str, Any], overrides: Dict[str, Dict[str, str]]) -> Optional[str]:
    """Sets c.kind / c.match / c.tc_basis. Returns an exclusion reason, or None."""
    for m in registry["matches"]:
        if c.opp_surname != m["opponent"]["surname"]:
            continue
        if c.date is None:
            year = (c.rg.headers.get("Date") or "")[:4]
            if year == str(m["year"]):
                return "game against %s dated %r in a match year: cannot place it" % (
                    m["opponent"]["display"], c.rg.headers.get("Date"))
            continue
        if c.date in m["tiebreak_dates"]:
            c.kind, c.match, c.tc_basis = "wcc_tiebreak", m, "match tiebreak date"
            return None
        lo, hi = m["classical_window"]
        if lo <= c.date <= hi:
            c.kind, c.match, c.tc_basis = "wcc_classical", m, "match classical window"
            return None
    c.kind = "other"
    if c.date is None:
        return "no complete date; cannot identify or de-duplicate the game"
    h = c.rg.headers
    event, site = h.get("Event", ""), h.get("Site", "")
    ov = overrides.get(event)
    if ov:
        c.tc_basis = "override: " + ov.get("reason", "")
        return None if ov["decision"] == "classical" else "excluded by event override: %s" % ov.get("reason", "")
    tc = time_control_class(h.get("TimeControl"))
    if tc is not None:
        c.tc_basis = "TimeControl %s" % h.get("TimeControl")
        return None if tc == "classical" else "TimeControl %s is %s" % (h.get("TimeControl"), tc)
    ev = event.lower()
    for kw in registry["non_classical_event_keywords"]:
        if kw in ev:
            return "event %r matches non-classical keyword %r" % (event, kw)
    st = site.lower()
    for kw in registry["non_classical_site_keywords"]:
        if kw in st:
            return "site %r matches non-classical keyword %r" % (site, kw)
    if site.strip() in registry["non_classical_site_exact"]:
        return "site %r marks an internet game" % site
    c.tc_basis = "event-name filter (no TimeControl header)"
    return None


# ------------------------------------------------------------------------------- grouping

class GameGroup:
    """All copies of one game, across sources."""

    def __init__(self, key: Tuple, copies: List[Candidate]):
        self.key = key
        self.copies = copies
        self.problem: Optional[str] = None
        self.tier: Optional[str] = None
        self.game_id: Optional[str] = None
        self.game_number: Optional[int] = None
        lineages = {c.rg.meta.get("lineage", c.rg.meta["name"]) for c in copies}
        self.independent_sources = len(lineages)
        self.canonical = sorted(copies, key=lambda c: (c.rg.meta.get("priority", 100), c.rg.source,
                                                       c.rg.file.path, c.rg.index))[0]

    def check_agreement(self) -> None:
        base = self.canonical
        diffs = []
        for c in self.copies:
            if c.ucis != base.ucis:
                diffs.append("%s differs from %s at ply %d" % (c.rg.locator, base.rg.locator,
                                                              first_difference(c.ucis, base.ucis)))
            if c.result != base.result:
                diffs.append("%s has Result %s, %s has %s" % (c.rg.locator, c.result, base.rg.locator, base.result))
            if c.carlsen_color != base.carlsen_color:
                diffs.append("%s has Carlsen as %s" % (c.rg.locator, c.carlsen_color))
        if diffs:
            self.problem = "sources disagree: " + "; ".join(diffs)


def first_difference(a: List[str], b: List[str]) -> int:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i + 1
    return min(len(a), len(b)) + 1


def group_wcc(cands: List[Candidate], log: Dict[str, Any]) -> List[GameGroup]:
    groups: List[GameGroup] = []
    classical = defaultdict(list)
    tiebreak = defaultdict(list)
    for c in cands:
        if c.kind == "wcc_classical":
            classical[(c.match["match_id"], c.date)].append(c)
        elif c.kind == "wcc_tiebreak":
            tiebreak[(c.match["match_id"], c.date)].append(c)
    # Classical: one game per playing day, so (match, date) identifies the game.
    by_match = defaultdict(list)
    for key, copies in sorted(classical.items()):
        g = GameGroup(key, copies)
        g.check_agreement()
        rounds = {round_number(c.rg.headers) for c in copies}
        by_match[key[0]].append(g)
        if len(rounds) != 1 or None in rounds:
            g.problem = (g.problem + "; " if g.problem else "") + \
                "Round headers disagree or are missing: %s" % sorted(str(r) for r in rounds)
        else:
            g.game_number = rounds.pop()
        groups.append(g)
    for match_id, gs in by_match.items():
        ordered = sorted(gs, key=lambda g: g.key[1])
        for pos, g in enumerate(ordered, 1):
            if g.game_number is not None and g.game_number != pos:
                log["issues"].append("%s: the game dated %s has Round %s but is game %d by date order"
                                     % (match_id, g.key[1], g.game_number, pos))
    # Tiebreaks: several games a day, so copies are matched by their move sequence.
    for (match_id, date), copies in sorted(tiebreak.items()):
        seqs = defaultdict(list)
        for c in copies:
            seqs[c.moves_hash].append(c)
        day = [GameGroup((match_id, date, h), cs) for h, cs in seqs.items()]
        n_sources = len({c.rg.meta.get("lineage", c.rg.meta["name"]) for c in copies})
        for g in day:
            g.check_agreement()
            if g.independent_sources < n_sources:
                log["issues"].append(
                    "%s tiebreak on %s: a game held by %d of the %d sources for that day; the others "
                    "either lack it or record different moves (%s)"
                    % (match_id, date, g.independent_sources, n_sources, g.canonical.rg.locator))
        day.sort(key=lambda g: (natural_key(g.canonical.rg.headers.get("Round", "")), g.canonical.rg.index))
        for k, g in enumerate(day, 1):
            g.game_number = k
            groups.append(g)
    return groups


def natural_key(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s or "")]


def group_other(cands: List[Candidate], log: Dict[str, Any]) -> List[GameGroup]:
    by_seq = defaultdict(list)
    for c in cands:
        if c.kind == "other":
            pair = (split_name(c.white)[0], split_name(c.black)[0])
            by_seq[(c.date,) + pair + (c.moves_hash,)].append(c)
    groups = [GameGroup(k, v) for k, v in sorted(by_seq.items())]
    for g in groups:
        g.check_agreement()
    # Distinct move sequences for the same players on the same day.
    by_day = defaultdict(list)
    for g in groups:
        by_day[g.key[:3]].append(g)
    for day_key, gs in by_day.items():
        if len(gs) < 2:
            continue
        for i, a in enumerate(gs):
            for b in gs[i + 1:]:
                ra = {(norm_event(c.rg.headers.get("Event")), c.rg.headers.get("Round", "")) for c in a.copies}
                rb = {(norm_event(c.rg.headers.get("Event")), c.rg.headers.get("Round", "")) for c in b.copies}
                sa, sb = a.canonical.ucis, b.canonical.ucis
                prefix = sa[:len(sb)] == sb or sb[:len(sa)] == sa
                if prefix or (ra & rb):
                    why = "one is a truncated copy of the other" if prefix else "same event and round"
                    for g in (a, b):
                        g.problem = "conflicting copies of one game (%s): %s vs %s" % (
                            why, a.canonical.rg.locator, b.canonical.rg.locator)
                elif {e for e, _ in ra} & {e for e, _ in rb}:
                    for g in (a, b):
                        if g.problem is None:
                            g.problem = ("two different games between the same players on %s in the same event "
                                         "(probable armageddon/tiebreak); excluded unless overridden" % day_key[0])
    return groups


# ---------------------------------------------------------------------------- registry check

def check_registry(groups: List[GameGroup], registry: Dict[str, Any], log: Dict[str, Any]) -> bool:
    ok = True
    for m in registry["matches"]:
        mid = m["match_id"]
        cl = [g for g in groups if g.key[0] == mid and g.canonical.kind == "wcc_classical" and g.problem is None]
        tb = [g for g in groups if g.key[0] == mid and g.canonical.kind == "wcc_tiebreak" and g.problem is None]
        found = {
            "classical_games": len(cl),
            "carlsen_classical_wins": sorted(g.game_number for g in cl if g.canonical.carlsen_result == "win"),
            "carlsen_classical_losses": sorted(g.game_number for g in cl if g.canonical.carlsen_result == "loss"),
            "tiebreak_carlsen_wins": sum(1 for g in tb if g.canonical.carlsen_result == "win"),
        }
        expected = {
            "classical_games": m["expected_classical_games"],
            "carlsen_classical_wins": m["expected_carlsen_classical_wins"],
            "carlsen_classical_losses": m["expected_carlsen_classical_losses"],
            "tiebreak_carlsen_wins": m["expected_tiebreak_carlsen_wins"],
        }
        mismatches = {k: {"expected": expected[k], "found": found[k]} for k in expected if expected[k] != found[k]}
        log["registry_check"][mid] = {"found": found, "expected": expected, "mismatches": mismatches}
        if mismatches:
            ok = False
            log["issues"].append("%s: sources disagree with match_registry.json: %s" % (mid, json.dumps(mismatches)))
    return ok


# ------------------------------------------------------------------------------ records

def assign_tiers(groups: List[GameGroup]) -> None:
    for g in groups:
        c = g.canonical
        if c.kind == "wcc_classical":
            g.tier = "A" if c.carlsen_result == "win" else "B"
            g.game_id = "%s_game%s" % (c.match["match_id"], g.game_number if g.game_number is not None
                                       else "_" + c.date.replace("-", ""))
        elif c.kind == "wcc_tiebreak":
            g.tier = "C"
            g.game_id = "%s_tiebreak%d" % (c.match["match_id"], g.game_number)
        else:
            g.tier = "D" if c.carlsen_result == "win" else "E"
            ws, bs = split_name(c.white)[0], split_name(c.black)[0]
            g.game_id = "otb_%s_%s_%s_%s" % (c.date.replace("-", ""), re.sub(r"\W+", "", ws),
                                             re.sub(r"\W+", "", bs), c.moves_hash[:6])


def game_records(g: GameGroup) -> List[Dict[str, Any]]:
    c = g.canonical
    h = c.rg.headers
    carlsen_turn = chess.WHITE if c.carlsen_color == "white" else chess.BLACK
    board = chess.Board()
    records = []
    prev = None
    for ply, (uci, san) in enumerate(zip(c.ucis, c.sans), 1):
        move = chess.Move.from_uci(uci)
        if board.turn == carlsen_turn:
            options = legal_options(board)
            target = next(o for o in options if o["uci"] == uci)
            records.append({
                "id": "%s_ply%03d" % (g.game_id, ply),
                "game_id": g.game_id,
                "tier": g.tier,
                "dataset": c.kind,
                "match_id": c.match["match_id"] if c.match else None,
                "championship_year": c.match["year"] if c.match else None,
                "game_number": g.game_number,
                "event": h.get("Event"),
                "site": h.get("Site"),
                "date": c.date,
                "round": h.get("Round"),
                "white": c.white,
                "black": c.black,
                "result": c.result,
                "carlsen_result": c.carlsen_result,
                "carlsen_color": c.carlsen_color,
                "opponent": c.opponent,
                "time_control_basis": c.tc_basis,
                "ply": ply,
                "fullmove_number": board.fullmove_number,
                "side_to_move": COLOR_NAME[board.turn].lower(),
                "phase": game_phase(board),
                "fen": board.fen(),
                "position_key": position_key(board),
                "board_description": describe_board(board),
                "previous_move": prev,
                "question": DEFAULT_QUESTION,
                "num_legal_moves": len(options),
                "options": options,
                "target": uci,
                "target_san": san,
                "target_description": target["description"],
                "source": {"copy": c.rg.locator, "name": c.rg.source, "url": c.rg.meta.get("url"),
                           "file_sha256": c.rg.file.sha256, "pgn_sha256": c.rg.file.member_sha256,
                           "game_index": c.rg.index},
                "sources": sorted({x.rg.source for x in g.copies}),
                "independent_sources": g.independent_sources,
                "cross_checked": g.independent_sources >= 2,
            })
        prev = {"uci": uci, "san": san, "by": COLOR_NAME[board.turn].lower()}
        board.push(move)
    return records


def provenance_entry(g: GameGroup, n_decisions: int, include_text: bool) -> Dict[str, Any]:
    c = g.canonical
    entry = {
        "game_id": g.game_id, "tier": g.tier, "dataset": c.kind,
        "match_id": c.match["match_id"] if c.match else None,
        "championship_year": c.match["year"] if c.match else None,
        "game_number": g.game_number, "event": c.rg.headers.get("Event"), "site": c.rg.headers.get("Site"),
        "date": c.date, "round": c.rg.headers.get("Round"),
        "white": c.white, "black": c.black, "result": c.result,
        "carlsen_color": c.carlsen_color, "carlsen_result": c.carlsen_result,
        "plies": len(c.ucis), "carlsen_decisions": n_decisions,
        "time_control_basis": c.tc_basis,
        "independent_sources": g.independent_sources,
        "cross_checked": g.independent_sources >= 2,
        "cross_check": "all %d copies agree on every move, the result and the colours" % len(g.copies)
        if len(g.copies) > 1 else "single copy; no second source to compare",
        "canonical_copy": c.rg.locator,
        "moves_sha256": hashlib.sha256(" ".join(c.ucis).encode()).hexdigest(),
        "copies": [],
    }
    for x in sorted(g.copies, key=lambda x: x.rg.locator):
        copy = {"source": x.rg.source, "publisher": x.rg.meta.get("publisher"), "url": x.rg.meta.get("url"),
                "retrieved": x.rg.meta.get("retrieved"), "file": x.rg.file.path, "member": x.rg.file.member,
                "file_sha256": x.rg.file.sha256, "pgn_sha256": x.rg.file.member_sha256,
                "game_index": x.rg.index, "headers": x.rg.headers}
        if include_text:
            copy["original_pgn"] = x.rg.raw_pgn
        entry["copies"].append(copy)
    return entry


# ----------------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources-dir", default=os.path.join(HERE, "sources", "raw"))
    ap.add_argument("--registry", default=os.path.join(HERE, "match_registry.json"))
    ap.add_argument("--overrides", default=os.path.join(HERE, "event_overrides.json"))
    ap.add_argument("--out-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--tiers", default="ABCDE", help="tiers to write (default ABCDE)")
    ap.add_argument("--require-cross-check", default="ABC",
                    help="tiers whose games need >= 2 independent agreeing sources (default ABC)")
    args = ap.parse_args(argv)

    with open(args.registry, encoding="utf-8") as f:
        registry = json.load(f)
    overrides = {}
    if os.path.exists(args.overrides):
        with open(args.overrides, encoding="utf-8") as f:
            overrides = {o["event"]: o for o in json.load(f).get("overrides", [])}
    os.makedirs(args.out_dir, exist_ok=True)
    log: Dict[str, Any] = {"sources": [], "unusable_copies": [], "excluded_copies": [], "excluded_games": [],
                           "issues": [], "registry_check": {}, "overrides": list(overrides.values())}

    cands = load_candidates(args.sources_dir, registry, log)
    kept = []
    for c in cands:
        reason = classify(c, registry, overrides)
        if reason:
            log["excluded_copies"].append({"copy": c.rg.locator, "event": c.rg.headers.get("Event"),
                                           "date": c.rg.headers.get("Date"), "white": c.white, "black": c.black,
                                           "reason": reason})
        else:
            kept.append(c)

    groups = group_wcc(kept, log) + group_other(kept, log)
    registry_ok = check_registry(groups, registry, log)
    assign_tiers(groups)
    for g in groups:
        if g.problem is None and g.tier in args.require_cross_check and g.independent_sources < 2:
            g.problem = "only %d independent source; tier %s requires a cross-check" % (g.independent_sources, g.tier)
        if g.problem:
            log["excluded_games"].append({"game_id": g.game_id, "tier": g.tier, "copies": [c.rg.locator for c in g.copies],
                                          "reason": g.problem})

    accepted = sorted((g for g in groups if g.problem is None and g.tier in args.tiers),
                      key=lambda g: (g.tier, g.canonical.date, g.game_id))
    ids = Counter(g.game_id for g in accepted)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit("duplicate game ids: %s" % dup)

    counts = Counter()
    wcc_prov, other_prov = [], []
    writers = {t: open_text(os.path.join(args.out_dir, TIER_MASTER[t]), "wt") for t in args.tiers}
    pgns = {t: open(os.path.join(args.out_dir, TIER_PGN[t]), "w", encoding="utf-8") for t in args.tiers}
    try:
        for g in accepted:
            recs = game_records(g)
            for r in recs:
                writers[g.tier].write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            pgns[g.tier].write(g.canonical.rg.raw_pgn.rstrip("\n") + "\n\n")
            counts[g.tier + "_games"] += 1
            counts[g.tier + "_decisions"] += len(recs)
            prov = provenance_entry(g, len(recs), include_text=g.tier in WCC_TIERS)
            (wcc_prov if g.tier in WCC_TIERS else other_prov).append(prov)
    finally:
        for w in list(writers.values()) + list(pgns.values()):
            w.close()

    with open(os.path.join(args.out_dir, "carlsen_wcc_sources.json"), "w", encoding="utf-8") as f:
        json.dump({"about": "Every World Championship game in tiers A-C: its sources, their SHA-256, the original "
                            "PGN text of each copy, and the cross-check result.",
                   "sources": log["sources"], "games": wcc_prov}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.out_dir, "carlsen_classical_sources.json"), "w", encoding="utf-8") as f:
        json.dump({"about": "Every tier D/E game: its sources, their SHA-256 and the game's index in each file "
                            "(the original text is the game at that index of that file).",
                   "sources": log["sources"], "games": other_prov}, f, indent=2, ensure_ascii=False)
    log["counts"] = dict(sorted(counts.items()))
    log["registry_ok"] = registry_ok
    with open(os.path.join(args.out_dir, "build_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    print("games and decisions by tier:", dict(sorted(counts.items())))
    print("unusable copies %d, excluded copies %d, excluded games %d, issues %d"
          % (len(log["unusable_copies"]), len(log["excluded_copies"]), len(log["excluded_games"]), len(log["issues"])))
    for issue in log["issues"]:
        print("ISSUE:", issue)
    if not registry_ok:
        print("match_registry.json expectations do not match the sources; see build_log.json registry_check",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
