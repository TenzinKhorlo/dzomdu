#!/usr/bin/env python3
"""Turn the master dataset into Laya 0.4.8 training and test files.

    python prepare_data.py                                   # tiers A+D train, held-out A games test
    python prepare_data.py --tokenizer /path/to/laya/checkpoint/tokenizer --max-len 2048 --head-max-len 1536
    python prepare_data.py --laya-check /path/to/laya/checkpoint --max-len 2048 --head-max-len 1536

Each output row is one Carlsen decision in the `{state, questions, expected}` form that
`laya.train.items_from_rows` reads:

    {"state": "<board description>",
     "questions": {"move": {"type": "choice", "instructions": "...",
                            "criteria": {"<uci>": "<factual description> SAN: <san>.", ...}}},
     "expected": {"move": "<uci Carlsen played>"},
     "id": ..., "meta": {...provenance, ignored by Laya...}}

Every row carries its own legal-move set under the same question id `move`. Laya trains each row
on its own question definition, so a shared id is correct; the "Conflicting schema" warning that
`laya.train.finetune` prints for it only concerns the questions.json it saves for convenience.

The split is by game. Test games come from the tiers named by --test-tiers (A by default) and
are never used for training, whichever tiers training draws on.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set

from build_dataset import TIER_MASTER, open_text, read_jsonl
from chess_text import laya_criterion, laya_instructions, laya_state

HERE = os.path.dirname(os.path.abspath(__file__))
QID = "move"


def load_master(data_dir: str, tiers: str) -> List[Dict[str, Any]]:
    rows = []
    for t in tiers:
        path = os.path.join(data_dir, TIER_MASTER[t])
        if not os.path.exists(path):
            raise SystemExit("missing %s (tier %s); run build_dataset.py first" % (path, t))
        rows.extend(read_jsonl(path))
    return rows


def to_laya(rec: Dict[str, Any], include_san: bool, include_fen: bool, include_last_move: bool) -> Dict[str, Any]:
    last = None
    if include_last_move and rec.get("previous_move"):
        pm = rec["previous_move"]
        last = "%s played %s (%s)." % (pm["by"].capitalize(), pm["san"], pm["uci"])
    criteria = {o["uci"]: laya_criterion(o, include_san) for o in rec["options"]}
    return {
        "id": rec["id"],
        "state": laya_state(rec["board_description"], rec["fen"] if include_fen else None, last),
        "questions": {QID: {"type": "choice",
                            "instructions": laya_instructions(rec["side_to_move"].capitalize()),
                            "criteria": criteria}},
        "expected": {QID: rec["target"]},
        "meta": {k: rec[k] for k in ("game_id", "tier", "ply", "fullmove_number", "fen", "position_key", "phase",
                                     "carlsen_color", "carlsen_result", "num_legal_moves", "date", "target_san")},
    }


# --------------------------------------------------------------------------------- split

def game_table(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    games: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        g = games.setdefault(r["game_id"], {"game_id": r["game_id"], "tier": r["tier"], "date": r["date"],
                                             "match_id": r["match_id"], "carlsen_color": r["carlsen_color"],
                                             "decisions": 0, "positions": set()})
        g["decisions"] += 1
        g["positions"].add(r["position_key"])
    return games


def choose_balanced(cands: List[Dict[str, Any]], static_train_pos: Set[str], frac: float, seed: str):
    """Exhaustive search over subsets of candidate games (deterministic).

    Constraints: at least one test game with Carlsen as White and one as Black, and at least one
    candidate game left for training. Objective, in order: test share of the candidates' decisions
    closest to `frac`; fewest test positions also seen in training; a seeded hash as tiebreak.
    """
    n = len(cands)
    if n < 3:
        raise SystemExit("need at least 3 candidate test games for a balanced split, have %d" % n)
    if n > 20:
        raise SystemExit("%d candidate games is too many for the exhaustive search; use --split temporal" % n)
    total = sum(g["decisions"] for g in cands)
    best = None
    for k in range(1, n):
        for combo in itertools.combinations(range(n), k):
            test = [cands[i] for i in combo]
            if {g["carlsen_color"] for g in test} != {"white", "black"}:
                continue
            share = sum(g["decisions"] for g in test) / total
            train_pos = set(static_train_pos)
            for i in range(n):
                if i not in combo:
                    train_pos |= cands[i]["positions"]
            test_pos = set().union(*(g["positions"] for g in test))
            overlap = len(test_pos & train_pos) / max(1, len(test_pos))
            h = hashlib.sha256((seed + "|" + ",".join(sorted(g["game_id"] for g in test))).encode()).hexdigest()
            score = (round(abs(share - frac), 3), round(overlap, 4), h)
            if best is None or score < best[0]:
                best = (score, [g["game_id"] for g in test], share, overlap)
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--out-dir", default=None, help="default: --data-dir")
    ap.add_argument("--train-tiers", default="AD", help="tiers used for training (default AD = all wins)")
    ap.add_argument("--test-tiers", default="A", help="tiers test games are drawn from (default A)")
    ap.add_argument("--split", choices=("balanced", "temporal"), default="balanced")
    ap.add_argument("--test-frac", type=float, default=0.2,
                    help="balanced split: target share of the test tiers' decisions held out (default 0.2)")
    ap.add_argument("--temporal-test-match", default="2021_wcc", help="temporal split: the match held out")
    ap.add_argument("--allow-future-train", action="store_true",
                    help="temporal split: keep training games dated on/after the first test game")
    ap.add_argument("--test-games", help="comma-separated game ids: use exactly these as the test set")
    ap.add_argument("--seed", default="carlsen-wcc-v1")
    ap.add_argument("--no-san", action="store_true", help="leave SAN out of the option texts")
    ap.add_argument("--include-fen", action="store_true", help="append the FEN to the state text")
    ap.add_argument("--include-last-move", action="store_true", help="state the opponent's previous move")
    ap.add_argument("--tokenizer", help="tokenizer directory (e.g. <laya checkpoint>/tokenizer) for exact budgets")
    ap.add_argument("--laya-check", metavar="MODEL_DIR",
                    help="run laya.train.items_from_rows on the output with this checkpoint's tokenizer")
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--head-max-len", type=int, default=1536)
    args = ap.parse_args(argv)
    out_dir = args.out_dir or args.data_dir
    os.makedirs(out_dir, exist_ok=True)

    tiers = "".join(sorted(set(args.train_tiers) | set(args.test_tiers)))
    rows = load_master(args.data_dir, tiers)
    games = game_table(rows)

    cands = sorted((g for g in games.values() if g["tier"] in args.test_tiers), key=lambda g: g["game_id"])
    future_cut = None
    if args.test_games:
        test_ids = [x.strip() for x in args.test_games.split(",") if x.strip()]
        unknown = [x for x in test_ids if x not in games]
        if unknown:
            raise SystemExit("unknown --test-games: %s" % unknown)
        split_info = {"method": "explicit list"}
    elif args.split == "temporal":
        test_ids = [g["game_id"] for g in cands if g["match_id"] == args.temporal_test_match]
        if not test_ids:
            raise SystemExit("no %s games in tiers %s" % (args.temporal_test_match, args.test_tiers))
        future_cut = None if args.allow_future_train else min(games[i]["date"] for i in test_ids)
        split_info = {"method": "temporal", "test_match": args.temporal_test_match,
                      "train_excludes_games_dated_on_or_after": future_cut}
    else:
        static = set()
        for g in games.values():
            if g["tier"] in args.train_tiers and g["tier"] not in args.test_tiers:
                static |= g["positions"]
        score, test_ids, share, overlap = choose_balanced(cands, static, args.test_frac, args.seed)
        split_info = {"method": "balanced exhaustive search", "target_test_frac": args.test_frac,
                      "achieved_test_frac": round(share, 4), "test_position_overlap": round(overlap, 4),
                      "seed": args.seed}
    test_set = set(test_ids)

    include_san = not args.no_san
    train, test, dropped_future = [], [], Counter()
    for r in rows:
        if r["game_id"] in test_set:
            test.append(r)
        elif r["tier"] in args.train_tiers:
            if future_cut and r["date"] >= future_cut:
                dropped_future[r["game_id"]] += 1
                continue
            train.append(r)
    train_pos = {r["position_key"] for r in train}
    train_games = {r["game_id"] for r in train}
    assert not (train_games & test_set), "a test game leaked into training"

    def write(path, recs, extra=None):
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                row = to_laya(r, include_san, args.include_fen, args.include_last_move)
                if extra:
                    row["meta"].update(extra(r))
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(recs)

    train.sort(key=lambda r: r["id"])
    test.sort(key=lambda r: r["id"])
    novel = [r for r in test if r["position_key"] not in train_pos]
    seen = lambda r: {"position_in_train": r["position_key"] in train_pos}
    n_train = write(os.path.join(out_dir, "carlsen_wcc_laya_train.jsonl"), train)
    n_test = write(os.path.join(out_dir, "carlsen_wcc_laya_test.jsonl"), test, seen)
    n_novel = write(os.path.join(out_dir, "carlsen_wcc_laya_test_novel.jsonl"), novel, seen)

    # Training-set conflicts: the same position with different Carlsen moves (kept, by design).
    targets = defaultdict(set)
    for r in train:
        targets[r["position_key"]].add(r["target"])
    conflicting = {k: sorted(v) for k, v in targets.items() if len(v) > 1}

    report = {
        "train_tiers": args.train_tiers, "test_tiers": args.test_tiers, "split": split_info,
        "test_games": sorted(test_set),
        "train_games": len(train_games), "train_decisions": n_train,
        "test_decisions": n_test, "test_decisions_unseen_positions": n_novel,
        "test_decisions_position_also_in_train": n_test - n_novel,
        "train_decisions_dropped_as_future": sum(dropped_future.values()),
        "train_positions_with_conflicting_targets": len(conflicting),
        "random_baseline_test_accuracy": round(sum(1 / r["num_legal_moves"] for r in test) / max(1, n_test), 4),
        "options": {"include_san": include_san, "include_fen": args.include_fen,
                    "include_last_move": args.include_last_move},
        "max_legal_moves": max((r["num_legal_moves"] for r in train + test), default=0),
    }
    report["token_budget"] = budget_check(out_dir, args)
    with open(os.path.join(out_dir, "split_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "test_games"}, indent=2))
    tb = report["token_budget"]
    if tb.get("violations"):
        print("token budget violated by %d row(s); see split_manifest.json" % tb["violations"], file=sys.stderr)
        return 3
    if tb.get("laya_skipped"):
        print("laya.train skipped items: %r" % tb["laya_skipped"], file=sys.stderr)
        return 3
    return 0


# --------------------------------------------------------------------------------- budgets

def budget_check(out_dir: str, args) -> Dict[str, Any]:
    """Exact token accounting with Laya's own sequence builder, when a tokenizer is available.

    Without one, only a character-based estimate is reported and nothing is certified.
    """
    paths = [os.path.join(out_dir, n) for n in ("carlsen_wcc_laya_train.jsonl", "carlsen_wcc_laya_test.jsonl")]
    rows = [json.loads(l) for p in paths for l in open(p, encoding="utf-8") if l.strip()]
    tok_dir = args.tokenizer or (os.path.join(args.laya_check, "tokenizer") if args.laya_check else None)
    if not tok_dir:
        longest = max(rows, key=lambda r: sum(len(k) + len(v) + 3 for k, v in r["questions"][QID]["criteria"].items()),
                      default=None)
        if longest is None:
            return {"mode": "none"}
        head_chars = sum(len(k) + len(v) + 3 for k, v in longest["questions"][QID]["criteria"].items())
        state_chars = max(len(r["state"]) for r in rows)
        return {"mode": "estimate only (pass --tokenizer for exact numbers)",
                "max_head_chars": head_chars, "max_state_chars": state_chars,
                "note": "English BPE averages about 3-4 characters per token; square names like 'e4' "
                        "often cost 2 tokens, so treat chars/3 as the planning figure, not a guarantee"}
    from transformers import AutoTokenizer
    from laya.common import build_head, encode_text
    from laya.train import to_internal

    tok = AutoTokenizer.from_pretrained(tok_dir)
    worst_head = worst_total = worst_opt = 0
    violations = []
    for r in rows:
        q = to_internal(QID, r["questions"][QID])
        opts = ["%s: %s" % (k, v) for k, v in q["crit"].items()]
        opt_lens = [len(encode_text(tok, " " + o, add_special_tokens=False)["input_ids"]) for o in opts]
        ins_len = len(encode_text(tok, "%s question: %s" % (q["t"], q["ins"]), add_special_tokens=False)["input_ids"])
        need_head = 2 + ins_len + sum(n + 1 for n in opt_lens) + 1   # CLS, SEP, [MASK]+option each, SEP
        state_len = len(encode_text(tok, r["state"], add_special_tokens=False)["input_ids"])
        need_total = need_head + state_len + 1
        _ids, markers, stats = build_head(tok, q, args.head_max_len)
        worst_head, worst_total = max(worst_head, need_head), max(worst_total, need_total)
        worst_opt = max(worst_opt, max(opt_lens))
        problems = []
        if max(opt_lens) > 48:
            problems.append("an option is %d tokens; Laya caps each option at 48" % max(opt_lens))
        if stats["tokens_per_option"] is not None or stats["options_distinct"] < stats["options"]:
            problems.append("head_max_len %d cuts option texts" % args.head_max_len)
        if sum(n + 1 for n in opt_lens) + ins_len > args.head_max_len:
            problems.append("instructions would be cut")
        if need_total > args.max_len:
            problems.append("needs %d tokens > max_len %d (state would be truncated)" % (need_total, args.max_len))
        if problems:
            violations.append({"id": r["id"], "problems": problems})
    out = {"mode": "exact (laya.common + %s)" % tok_dir, "max_len": args.max_len, "head_max_len": args.head_max_len,
           "max_head_tokens_needed": worst_head, "max_sequence_tokens_needed": worst_total,
           "max_option_tokens": worst_opt, "violations": len(violations), "violation_examples": violations[:20],
           "recommended": {"head_max_len": 64 * math.ceil((worst_head + 8) / 64),
                           "max_len": 64 * math.ceil((worst_total + 8) / 64)}}
    if args.laya_check:
        import laya.train as lt
        with open(os.path.join(args.laya_check, "rl_agent_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        items, skipped = lt.items_from_rows(tok, rows, args.max_len, args.head_max_len)
        out.update({"laya_items": len(items), "laya_rows": len(rows), "laya_skipped": skipped,
                    "checkpoint_defaults": {"max_len": cfg.get("max_len"), "head_max_len": cfg.get("head_max_len")}})
    return out


if __name__ == "__main__":
    sys.exit(main())
