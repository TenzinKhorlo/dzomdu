#!/usr/bin/env python3
"""Re-derive every record from the source PGNs and check it; write dataset_report.json.

    python validate_dataset.py                 # after build_dataset.py and prepare_data.py

Checks, each reported with its count of failures (the first 50 are listed):

  source_integrity      every source file still has the SHA-256 recorded at registration, and the
                        canonical copy at the recorded index is the game the dataset was built from
  cross_check           tier A-C: every copy's original PGN text replays to the same moves and result
  games_pgn             the games PGN file holds exactly the dataset's games, move for move
  replay                every recorded move is legal, in order, from the standard start
  fen                   each record's FEN is the position before Carlsen's move
  target                each target is the move the source PGN records at that ply (UCI and SAN)
  coverage              every Carlsen move of every game has exactly one record, and no others exist
  legal_options         options == python-chess's legal move set: no extras, none missing, no duplicates
  promotions            every promoting pawn move offers all four pieces (q, r, b, n)
  option_facts          every option's flags and description equal a fresh computation
                        (capture, check, checkmate, castling, en passant, promotion)
  board_description     each description re-renders from, and parses back to, the record's FEN
  results               record, provenance and header results agree; tier matches Carlsen's result
  laya_schema           Laya rows: valid JSON, a well-formed choice question, criteria == legal moves,
                        expected answer among the criteria, state == the record's description
  laya_library          the same rows through laya.train.to_internal/target_from_expected, when laya
                        is importable
  split                 no game in both train and test; test positions seen in training are counted
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

import chess
import chess.pgn
import io

from build_dataset import TIER_MASTER, TIER_PGN, open_text
from chess_text import (COLOR_NAME, PROMOTION_PIECES, describe_board, describe_move, game_phase,
                        laya_criterion, laya_instructions, parse_board_description, position_key)
from sources_io import iter_games, iter_source_files, read_source_meta

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = ("source_integrity", "cross_check", "games_pgn", "replay", "fen", "target", "coverage",
          "legal_options", "promotions", "option_facts", "board_description", "results",
          "laya_schema", "laya_library", "split")


class Report:
    def __init__(self):
        self.checks = {c: {"checked": 0, "failures": 0, "examples": []} for c in CHECKS}
        self.notes: List[str] = []

    def ok(self, check: str, n: int = 1):
        self.checks[check]["checked"] += n

    def fail(self, check: str, msg: str):
        c = self.checks[check]
        c["checked"] += 1
        c["failures"] += 1
        if len(c["examples"]) < 50:
            c["examples"].append(msg)

    def expect(self, check: str, cond: bool, msg: str):
        if cond:
            self.ok(check)
        else:
            self.fail(check, msg)

    @property
    def passed(self) -> bool:
        return all(c["failures"] == 0 for c in self.checks.values())


def load_provenance(data_dir: str) -> Dict[str, Dict[str, Any]]:
    prov = {}
    for name in ("carlsen_wcc_sources.json", "carlsen_classical_sources.json"):
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for g in json.load(f)["games"]:
                    prov[g["game_id"]] = g
    return prov


def mainline(pgn_text: str):
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None or game.errors:
        return None, None
    return game, [m.uci() for m in game.mainline_moves()]


# ---------------------------------------------------------------------------- per game

def check_game(rep: Report, gid: str, recs: List[Dict[str, Any]], prov: Optional[Dict[str, Any]],
               source_games: Dict[str, Any], stats: Dict[str, Any]) -> None:
    if prov is None:
        rep.fail("coverage", "%s: records without a provenance entry" % gid)
        return
    canon = source_games.get(prov["canonical_copy"])
    if canon is None:
        rep.fail("source_integrity", "%s: canonical copy %s not found in the sources" % (gid, prov["canonical_copy"]))
        return
    rep.ok("source_integrity")
    game = canon.game
    ucis = [m.uci() for m in game.mainline_moves()]
    import hashlib
    rep.expect("source_integrity", hashlib.sha256(" ".join(ucis).encode()).hexdigest() == prov["moves_sha256"],
               "%s: canonical copy's moves differ from the recorded moves_sha256" % gid)
    header_result = canon.headers.get("Result")
    rep.expect("results", header_result == prov["result"], "%s: header Result %s vs provenance %s"
               % (gid, header_result, prov["result"]))

    # Cross-check: every listed copy, from its own source file (and its stored original text).
    for copy in prov["copies"]:
        loc = "%s:%s%s#%d" % (copy["source"], copy["file"], ("!" + copy["member"]) if copy["member"] else "",
                              copy["game_index"])
        sg = source_games.get(loc)
        if sg is None:
            rep.fail("cross_check", "%s: copy %s not found" % (gid, loc))
            continue
        other = [m.uci() for m in sg.game.mainline_moves()]
        rep.expect("cross_check", other == ucis and sg.headers.get("Result") == header_result,
                   "%s: copy %s disagrees with the canonical copy" % (gid, loc))
        if "original_pgn" in copy:
            g2, u2 = mainline(copy["original_pgn"])
            rep.expect("cross_check", u2 == ucis and g2.headers.get("Result") == header_result,
                       "%s: stored original_pgn of %s does not replay to the canonical moves" % (gid, loc))

    carlsen = chess.WHITE if prov["carlsen_color"] == "white" else chess.BLACK
    by_ply = {}
    for r in recs:
        if r["ply"] in by_ply:
            rep.fail("coverage", "%s: two records for ply %d" % (gid, r["ply"]))
        by_ply[r["ply"]] = r
    board = chess.Board()
    expected_plies = []
    for ply, uci in enumerate(ucis, 1):
        move = chess.Move.from_uci(uci)
        if not board.is_legal(move):
            rep.fail("replay", "%s: illegal move %s at ply %d" % (gid, uci, ply))
            return
        rep.ok("replay")
        if board.turn == carlsen:
            expected_plies.append(ply)
            r = by_ply.get(ply)
            if r is None:
                rep.fail("coverage", "%s: no record for Carlsen's move at ply %d" % (gid, ply))
            else:
                check_record(rep, r, board, move, prov, stats)
        board.push(move)
    extra = sorted(set(by_ply) - set(expected_plies))
    rep.expect("coverage", not extra, "%s: records for plies that are not Carlsen moves: %s" % (gid, extra))
    rep.expect("coverage", len(expected_plies) == prov["carlsen_decisions"],
               "%s: provenance says %d decisions, replay finds %d" % (gid, prov["carlsen_decisions"], len(expected_plies)))


def check_record(rep: Report, r: Dict[str, Any], board: chess.Board, move: chess.Move,
                 prov: Dict[str, Any], stats: Dict[str, Any]) -> None:
    rid = r["id"]
    rep.expect("fen", r["fen"] == board.fen(), "%s: FEN %s != replayed %s" % (rid, r["fen"], board.fen()))
    rep.expect("fen", r["position_key"] == position_key(board), "%s: position_key mismatch" % rid)
    rep.expect("fen", r["fullmove_number"] == board.fullmove_number and
               r["side_to_move"] == COLOR_NAME[board.turn].lower(), "%s: move number or side to move wrong" % rid)
    rep.expect("target", r["target"] == move.uci() and r["target_san"] == board.san(move),
               "%s: target %s/%s but the source records %s/%s" % (rid, r["target"], r["target_san"],
                                                                    move.uci(), board.san(move)))
    legal = sorted(m.uci() for m in board.legal_moves)
    opts = [o["uci"] for o in r["options"]]
    rep.expect("legal_options", len(opts) == len(set(opts)), "%s: duplicate options" % rid)
    rep.expect("legal_options", sorted(opts) == legal and r["num_legal_moves"] == len(legal),
               "%s: options differ from legal moves (missing %s, extra %s)"
               % (rid, sorted(set(legal) - set(opts)), sorted(set(opts) - set(legal))))
    rep.expect("legal_options", r["target"] in opts, "%s: target not among options" % rid)
    promos = defaultdict(set)
    for m in board.legal_moves:
        if m.promotion:
            promos[(m.from_square, m.to_square)].add(m.promotion)
    for (fs, ts), pieces in promos.items():
        have = {o["promotion_piece"] for o in r["options"]
                if o["from_square"] == chess.square_name(fs) and o["to_square"] == chess.square_name(ts)}
        rep.expect("promotions", pieces == set(PROMOTION_PIECES) and have == {"queen", "rook", "bishop", "knight"},
                   "%s: promotion %s%s offers %s" % (rid, chess.square_name(fs), chess.square_name(ts), sorted(have)))
        stats["promotion_positions"].add(rid)
    fresh = {m.uci(): describe_move(board, m) for m in board.legal_moves}
    for o in r["options"]:
        f = fresh.get(o["uci"])
        rep.expect("option_facts", f == o, "%s: option %s differs from a fresh computation" % (rid, o["uci"]))
        if f and f["is_castling"]:
            stats["castling_options"] += 1
        if f and f["is_en_passant"]:
            stats["en_passant_options"] += 1
    try:
        rebuilt = parse_board_description(r["board_description"])
        rep.expect("board_description", rebuilt == board.fen() and r["board_description"] == describe_board(board),
                   "%s: description encodes %s, FEN is %s" % (rid, rebuilt, board.fen()))
    except ValueError as e:
        rep.fail("board_description", "%s: %s" % (rid, e))
    rep.expect("results", r["result"] == prov["result"] and r["carlsen_result"] == prov["carlsen_result"]
               and r["carlsen_color"] == prov["carlsen_color"], "%s: result/colour disagrees with provenance" % rid)
    tier_ok = {"A": r["carlsen_result"] == "win", "B": r["carlsen_result"] != "win", "C": True,
               "D": r["carlsen_result"] == "win", "E": r["carlsen_result"] != "win"}[r["tier"]]
    rep.expect("results", tier_ok and r["tier"] == prov["tier"], "%s: tier %s inconsistent with result" % (rid, r["tier"]))
    rep.expect("results", r["phase"] == game_phase(board), "%s: phase label differs" % rid)


# ------------------------------------------------------------------------------- laya

def check_laya(rep: Report, path: str, by_id: Dict[str, Dict[str, Any]], laya_mods) -> List[Dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                rep.fail("laya_schema", "%s line %d: invalid JSON (%s)" % (os.path.basename(path), n, e))
                continue
            rows.append(row)
            rid = row.get("id")
            src = by_id.get(rid)
            q = (row.get("questions") or {}).get("move")
            problems = []
            if src is None:
                problems.append("no master record")
            if not isinstance(row.get("state"), str) or not row["state"].strip():
                problems.append("empty state")
            if not isinstance(q, dict) or q.get("type") != "choice":
                problems.append("question 'move' is not a choice question")
            else:
                crit = q.get("criteria")
                if not isinstance(crit, dict) or not crit or not all(isinstance(k, str) for k in crit):
                    problems.append("criteria must be a non-empty dict of str -> str")
                elif not all(isinstance(v, str) and v.strip() for v in crit.values()):
                    problems.append("empty criterion text")
                if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
                    problems.append("empty instructions")
                if src is not None and isinstance(crit, dict):
                    if sorted(crit) != sorted(src["uci"]):
                        problems.append("criteria keys differ from the record's legal moves")
                    if q.get("instructions") != laya_instructions(src["side"].capitalize()):
                        problems.append("instructions differ from the rendering rule")
            exp = (row.get("expected") or {}).get("move")
            if src is not None and exp != src["target"]:
                problems.append("expected %r != master target %r" % (exp, src["target"]))
            if isinstance(q, dict) and isinstance(q.get("criteria"), dict) and exp not in q["criteria"]:
                problems.append("expected answer not among criteria")
            if src is not None and isinstance(row.get("state"), str) and not row["state"].startswith(src["desc"]):
                problems.append("state does not start with the record's board description")
            if row.get("meta", {}).get("game_id") != (src or {}).get("game_id"):
                problems.append("meta.game_id mismatch")
            if problems:
                rep.fail("laya_schema", "%s: %s" % (rid, "; ".join(problems)))
            else:
                rep.ok("laya_schema")
            if laya_mods is not None and isinstance(q, dict):
                to_internal, target_from_expected = laya_mods
                try:
                    iq = to_internal("move", q)
                    t = target_from_expected(iq, exp)
                    rep.expect("laya_library", len(t) == len(q["criteria"]) and abs(sum(t) - 1) < 1e-9,
                               "%s: laya target has wrong shape" % rid)
                except Exception as e:  # noqa: BLE001 - any refusal by laya is a failure to report
                    rep.fail("laya_library", "%s: laya rejected the row: %s" % (rid, e))
    return rows


# -------------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--sources-dir", default=os.path.join(HERE, "sources", "raw"))
    ap.add_argument("--report", default=None, help="default: <data-dir>/dataset_report.json")
    args = ap.parse_args(argv)
    rep = Report()
    prov = load_provenance(args.data_dir)

    # Every source file, re-hashed, and the games the dataset cites.
    wanted = set()
    for g in prov.values():
        wanted.add(g["canonical_copy"])
        for c in g["copies"]:
            wanted.add("%s:%s%s#%d" % (c["source"], c["file"], ("!" + c["member"]) if c["member"] else "",
                                       c["game_index"]))
    by_file = defaultdict(set)
    for loc in wanted:
        where, idx = loc.rsplit("#", 1)
        by_file[where].add(int(idx))
    source_games = {}
    for name in sorted(os.listdir(args.sources_dir)) if os.path.isdir(args.sources_dir) else []:
        src_dir = os.path.join(args.sources_dir, name)
        if not os.path.isdir(src_dir):
            continue
        try:
            meta = read_source_meta(src_dir)
            for sf in iter_source_files(src_dir, meta):   # raises on a changed hash
                rep.ok("source_integrity")
                where = "%s:%s%s" % (meta["name"], sf.path, ("!" + sf.member) if sf.member else "")
                idxs = by_file.get(where)
                if not idxs:
                    continue
                remaining = set(idxs)
                for rg in iter_games(sf, meta):
                    if rg.index in remaining:
                        source_games["%s#%d" % (where, rg.index)] = rg
                        remaining.discard(rg.index)
                    if not remaining:
                        break
        except (ValueError, FileNotFoundError) as e:
            rep.fail("source_integrity", str(e))

    stats: Dict[str, Any] = {"promotion_positions": set(), "castling_options": 0, "en_passant_options": 0}
    tiers: Dict[str, Dict[str, Any]] = {}
    laya_index: Dict[str, Dict[str, Any]] = {}
    pos_targets = defaultdict(lambda: defaultdict(set))   # position -> target -> {record ids}
    seen_games = set()
    for tier, fname in TIER_MASTER.items():
        path = os.path.join(args.data_dir, fname)
        if not os.path.exists(path):
            continue
        t = tiers[tier] = {"file": fname, "games": 0, "decisions": 0, "white_decisions": 0, "black_decisions": 0,
                           "phases": Counter(), "positions": set(), "legal_moves_total": 0}
        current, recs = None, []

        def flush():
            if current is None:
                return
            if current in seen_games:
                rep.fail("coverage", "%s: records are not contiguous or appear in two files" % current)
            seen_games.add(current)
            check_game(rep, current, recs, prov.get(current), source_games, stats)
            t["games"] += 1

        with open_text(path) as f:
            for n, line in enumerate(f, 1):
                try:
                    r = json.loads(line)
                except json.JSONDecodeError as e:
                    rep.fail("coverage", "%s line %d: invalid JSON (%s)" % (fname, n, e))
                    continue
                if r["game_id"] != current:
                    flush()
                    current, recs = r["game_id"], []
                recs.append(r)
                rep.expect("results", r["tier"] == tier, "%s: tier %s in the tier-%s file" % (r["id"], r["tier"], tier))
                t["decisions"] += 1
                t["%s_decisions" % r["carlsen_color"]] += 1
                t["phases"][r["phase"]] += 1
                t["positions"].add(r["position_key"])
                t["legal_moves_total"] += r["num_legal_moves"]
                pos_targets[r["position_key"]][r["target"]].add(r["id"])
                laya_index[r["id"]] = {"uci": [o["uci"] for o in r["options"]], "target": r["target"],
                                       "desc": r["board_description"], "side": r["side_to_move"],
                                       "game_id": r["game_id"]}
            flush()

    missing = sorted(set(prov) - seen_games)
    rep.expect("coverage", not missing, "games in provenance without records: %s" % missing[:20])

    # Games PGN files: the same games, in provenance order, move for move.
    for tier, fname in TIER_PGN.items():
        path = os.path.join(args.data_dir, fname)
        if not os.path.exists(path):
            continue
        expected = [g for g in prov.values() if g["tier"] == tier]
        expected.sort(key=lambda g: (g["date"], g["game_id"]))
        got = []
        with open(path, encoding="utf-8") as f:
            while True:
                g = chess.pgn.read_game(f)
                if g is None:
                    break
                got.append(g)
        rep.expect("games_pgn", len(got) == len(expected), "%s: %d games, provenance lists %d" % (fname, len(got), len(expected)))
        import hashlib
        for g, p in zip(got, expected):
            h = hashlib.sha256(" ".join(m.uci() for m in g.mainline_moves()).encode()).hexdigest()
            rep.expect("games_pgn", h == p["moves_sha256"] and not g.errors, "%s: game for %s differs" % (fname, p["game_id"]))

    # Laya files.
    laya_mods = None
    try:
        from laya.train import target_from_expected, to_internal
        laya_mods = (to_internal, target_from_expected)
        import laya
        rep.notes.append("laya_library checked with laya %s" % getattr(laya, "__version__", "?"))
    except Exception as e:  # noqa: BLE001
        rep.notes.append("laya not importable here (%s): laya_library check skipped; the structural "
                         "laya_schema check still ran" % e.__class__.__name__)
    laya_rows = {}
    for name in ("carlsen_wcc_laya_train.jsonl", "carlsen_wcc_laya_test.jsonl", "carlsen_wcc_laya_test_novel.jsonl"):
        path = os.path.join(args.data_dir, name)
        if os.path.exists(path):
            laya_rows[name] = check_laya(rep, path, laya_index, laya_mods)
    split = {}
    if "carlsen_wcc_laya_train.jsonl" in laya_rows and "carlsen_wcc_laya_test.jsonl" in laya_rows:
        tr, te = laya_rows["carlsen_wcc_laya_train.jsonl"], laya_rows["carlsen_wcc_laya_test.jsonl"]
        tr_games = {r["meta"]["game_id"] for r in tr}
        te_games = {r["meta"]["game_id"] for r in te}
        rep.expect("split", not (tr_games & te_games), "games in both train and test: %s" % sorted(tr_games & te_games))
        tr_ids = {r["id"] for r in tr}
        rep.expect("split", not (tr_ids & {r["id"] for r in te}), "records in both train and test")
        tr_pos = {r["meta"]["position_key"] for r in tr}
        overlap = [r for r in te if r["meta"]["position_key"] in tr_pos]
        tr_targets = defaultdict(set)
        for r in tr:
            tr_targets[r["meta"]["position_key"]].add(r["expected"]["move"])
        same_label = sum(1 for r in overlap if r["expected"]["move"] in tr_targets[r["meta"]["position_key"]])
        for r in te:
            rep.expect("split", r["meta"].get("position_in_train") == (r["meta"]["position_key"] in tr_pos),
                       "%s: position_in_train flag wrong" % r["id"])
        novel = laya_rows.get("carlsen_wcc_laya_test_novel.jsonl", [])
        rep.expect("split", all(r["meta"]["position_key"] not in tr_pos for r in novel),
                   "the novel test file contains positions seen in training")
        split = {"train_rows": len(tr), "test_rows": len(te), "train_games": len(tr_games), "test_games": sorted(te_games),
                 "test_rows_position_seen_in_train": len(overlap),
                 "test_rows_position_seen_in_train_with_same_target": same_label,
                 "test_rows_novel": len(novel),
                 "random_baseline_test_accuracy": round(sum(1 / len(r["questions"]["move"]["criteria"]) for r in te)
                                                        / max(1, len(te)), 4)}

    conflicting = {k: {t: sorted(ids) for t, ids in v.items()} for k, v in pos_targets.items() if len(v) > 1}
    all_positions = set().union(*(t["positions"] for t in tiers.values())) if tiers else set()
    summary = {}
    for tier, t in tiers.items():
        summary[tier] = {"file": t["file"], "games": t["games"], "decisions": t["decisions"],
                         "unique_positions": len(t["positions"]), "white_decisions": t["white_decisions"],
                         "black_decisions": t["black_decisions"], "phases": dict(t["phases"]),
                         "mean_legal_moves": round(t["legal_moves_total"] / max(1, t["decisions"]), 2)}
    report = {
        "validation": {"passed": rep.passed and bool(tiers), "checks": rep.checks, "notes": rep.notes},
        "tiers": summary,
        "totals": {"games": sum(t["games"] for t in tiers.values()),
                   "decisions": sum(t["decisions"] for t in tiers.values()),
                   "unique_positions": len(all_positions),
                   "positions_with_conflicting_historical_choices": len(conflicting),
                   "decisions_in_conflicting_positions": sum(len(ids) for v in conflicting.values() for ids in v.values()),
                   "decisions_with_promotion_options": len(stats["promotion_positions"]),
                   "castling_options_checked": stats["castling_options"],
                   "en_passant_options_checked": stats["en_passant_options"]},
        "conflicting_positions_examples": dict(list(sorted(conflicting.items()))[:25]),
        "split": split,
    }
    for name in ("build_log.json", "split_manifest.json"):
        p = os.path.join(args.data_dir, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            report[name.replace(".json", "")] = (
                {k: d[k] for k in ("counts", "registry_ok", "registry_check", "issues", "excluded_games")}
                | {"excluded_copies": len(d["excluded_copies"]), "unusable_copies": len(d["unusable_copies"])}
                if name == "build_log.json" else d)
    out = args.report or os.path.join(args.data_dir, "dataset_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    for name, c in rep.checks.items():
        print("%-18s %-4s checked %-8d failures %d" % (name, "ok" if not c["failures"] else "FAIL", c["checked"], c["failures"]))
        for ex in c["examples"][:5]:
            print("    " + ex)
    for note in rep.notes:
        print("note:", note)
    print("validation %s; report written to %s" % ("PASSED" if report["validation"]["passed"] else "FAILED", out))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
