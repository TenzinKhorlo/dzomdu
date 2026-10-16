"""End-to-end pipeline tests on SYNTHETIC fixture games between fictional players.

The games are random legal move sequences generated at test time in a temporary directory, under
fictional names ("Alpha, Ann" vs "Beta, Bob"), so no invented game can be mistaken for a real one.
They exercise the mechanics: source registration and hashing, cross-checking, tier classification,
record building, the Laya conversion, and every validator check, including that tampering is caught.
"""
import json
import os
import random
import shutil
import zipfile

import chess
import chess.pgn
import pytest

import build_dataset
import fetch_sources
import prepare_data
import validate_dataset

REGISTRY = {
    "player": {"surname": "alpha", "first_initial": "a", "display": "Ann Alpha"},
    "matches": [{
        "match_id": "2000_test", "year": 2000, "title": "Synthetic test match",
        "opponent": {"surname": "beta", "display": "Bob Beta"},
        "classical_window": ["2000-01-01", "2000-01-10"], "tiebreak_dates": ["2000-01-12"],
        "expected_classical_games": 6, "expected_carlsen_classical_wins": [1, 3, 4, 6],
        "expected_carlsen_classical_losses": [5], "expected_tiebreak_carlsen_wins": 1,
    }],
    "tiers": {},
    "non_classical_event_keywords": ["blitz", "rapid"],
    "non_classical_site_keywords": ["chess.com"],
    "non_classical_site_exact": ["INT"],
}

# (date, round, alpha_is_white, alpha_result, event, site, seed)
GAMES = [
    ("2000.01.01", "1", True, "win", "Test Match", "Testville", 1),
    ("2000.01.02", "2", False, "draw", "Test Match", "Testville", 2),
    ("2000.01.03", "3", True, "win", "Test Match", "Testville", 3),
    ("2000.01.04", "4", False, "win", "Test Match", "Testville", 4),
    ("2000.01.05", "5", True, "loss", "Test Match", "Testville", 5),
    ("2000.01.06", "6", False, "win", "Test Match", "Testville", 6),
    ("2000.01.12", "7.1", True, "win", "Test Match Tiebreak", "Testville", 7),
    ("2000.01.12", "7.2", False, "draw", "Test Match Tiebreak", "Testville", 8),
    ("2001.05.01", "1", True, "win", "Test Open", "Elsewhere", 9),
    ("2001.05.02", "2", False, "draw", "Test Open", "Elsewhere", 10),
    ("2001.06.01", "1", True, "win", "Test Blitz", "Elsewhere", 11),
    ("2001.07.01", "1", False, "win", "Weekly Arena", "INT", 12),
]


def random_game(seed, plies):
    rng = random.Random(seed)
    while True:
        b = chess.Board()
        for _ in range(plies):
            b.push(rng.choice(list(b.legal_moves)))
            if b.is_game_over():
                break
        if not b.is_game_over():
            return b
        seed += 1000
        rng = random.Random(seed)


def pgn_text(spec, name_style, mutate=False):
    date, rnd, alpha_white, res, event, site, seed = spec
    b = random_game(seed, 40 + seed)
    if mutate:  # change the final move to a different legal one
        b.pop()
        alt = sorted(b.legal_moves, key=lambda m: m.uci())
        b.push(alt[0] if alt[0] != b.peek() else alt[1])
    g = chess.pgn.Game.from_board(b)
    alpha, beta = ("Alpha, Ann", "Beta, Bob") if name_style == 1 else ("Alpha,A", "Beta,B")
    g.headers.update({"Event": event, "Site": site, "Date": date, "Round": rnd,
                      "White": alpha if alpha_white else beta, "Black": beta if alpha_white else alpha})
    white_score = {"win": "1-0", "loss": "0-1", "draw": "1/2-1/2"}[res]
    if not alpha_white:
        white_score = {"1-0": "0-1", "0-1": "1-0"}.get(white_score, white_score)
    g.headers["Result"] = white_score
    return str(g) + "\n\n"


def make_sources(root, mutate_round=None):
    raw = os.path.join(root, "sources", "raw")
    one = os.path.join(raw, "one")
    two = os.path.join(raw, "two")
    os.makedirs(one)
    os.makedirs(two)
    with open(os.path.join(one, "games.pgn"), "w") as f:
        for spec in GAMES:
            f.write(pgn_text(spec, 1))
    text = "".join(pgn_text(spec, 2, mutate=(spec[1] == mutate_round)) for spec in GAMES)
    with zipfile.ZipFile(os.path.join(two, "games.zip"), "w") as z:
        z.writestr("inner/games.pgn", text)
    for name, pri in (("one", "1"), ("two", "2")):
        fetch_sources.RAW = raw
        fetch_sources.main(["register", "--name", name, "--publisher", "fixture " + name, "--url",
                            "https://example.invalid/" + name, "--priority", pri, "--retrieved", "2000-02-01"])
    reg = os.path.join(root, "registry.json")
    with open(reg, "w") as f:
        json.dump(REGISTRY, f)
    return raw, reg


def build(root, raw, reg):
    data = os.path.join(root, "data")
    rc = build_dataset.main(["--sources-dir", raw, "--registry", reg, "--overrides", os.path.join(root, "none.json"),
                             "--out-dir", data])
    return rc, data


def test_full_pipeline_passes_and_tiers_are_right(tmp_path):
    raw, reg = make_sources(str(tmp_path))
    rc, data = build(str(tmp_path), raw, reg)
    assert rc == 0
    log = json.load(open(os.path.join(data, "build_log.json")))
    assert log["counts"]["A_games"] == 4 and log["counts"]["B_games"] == 2
    assert log["counts"]["C_games"] == 2 and log["counts"]["D_games"] == 1 and log["counts"]["E_games"] == 1
    reasons = " ".join(e["reason"] for e in log["excluded_copies"])
    assert "blitz" in reasons and "internet" in reasons
    a = build_dataset.read_jsonl(os.path.join(data, build_dataset.TIER_MASTER["A"]))
    assert {r["carlsen_result"] for r in a} == {"win"}
    assert all(r["cross_checked"] and r["independent_sources"] == 2 for r in a)
    sources = json.load(open(os.path.join(data, "carlsen_wcc_sources.json")))
    assert all(len(g["copies"]) == 2 and "original_pgn" in g["copies"][0] for g in sources["games"])

    assert prepare_data.main(["--data-dir", data, "--train-tiers", "AD", "--test-tiers", "A",
                              "--test-frac", "0.3"]) == 0
    manifest = json.load(open(os.path.join(data, "split_manifest.json")))
    assert len(manifest["test_games"]) >= 2
    train = [json.loads(l) for l in open(os.path.join(data, "carlsen_wcc_laya_train.jsonl"))]
    assert {r["meta"]["tier"] for r in train} == {"A", "D"}
    row = train[0]
    assert set(row) >= {"state", "questions", "expected"}
    assert row["expected"]["move"] in row["questions"]["move"]["criteria"]

    assert validate_dataset.main(["--data-dir", data, "--sources-dir", raw]) == 0
    report = json.load(open(os.path.join(data, "dataset_report.json")))
    assert report["validation"]["passed"]
    assert report["totals"]["positions_with_conflicting_historical_choices"] >= 1  # start position, several 1st moves


def test_disagreeing_sources_exclude_the_game_and_fail_the_registry(tmp_path):
    raw, reg = make_sources(str(tmp_path), mutate_round="3")
    rc, data = build(str(tmp_path), raw, reg)
    assert rc == 2
    log = json.load(open(os.path.join(data, "build_log.json")))
    assert any("sources disagree" in e["reason"] for e in log["excluded_games"])
    assert log["registry_check"]["2000_test"]["mismatches"]


def test_single_source_wcc_game_is_refused(tmp_path):
    raw, reg = make_sources(str(tmp_path))
    shutil.rmtree(os.path.join(raw, "two"))
    rc, data = build(str(tmp_path), raw, reg)
    log = json.load(open(os.path.join(data, "build_log.json")))
    assert all("requires a cross-check" in e["reason"] for e in log["excluded_games"] if e["tier"] in "ABC")
    assert log["counts"].get("A_games", 0) == 0 and log["counts"]["D_games"] == 1


@pytest.mark.parametrize("tamper", ["target", "option", "description", "source"])
def test_validator_catches_tampering(tmp_path, tamper):
    raw, reg = make_sources(str(tmp_path))
    rc, data = build(str(tmp_path), raw, reg)
    assert rc == 0
    assert prepare_data.main(["--data-dir", data, "--test-frac", "0.3"]) == 0
    path = os.path.join(data, build_dataset.TIER_MASTER["A"])
    rows = build_dataset.read_jsonl(path)
    r = rows[5]
    if tamper == "target":
        other = next(o for o in r["options"] if o["uci"] != r["target"])
        r["target"] = other["uci"]
    elif tamper == "option":
        r["options"] = r["options"][:-1]
    elif tamper == "description":
        r["board_description"] = r["board_description"].replace("White king on", "White king  on")
    if tamper != "source":
        with open(path, "w") as f:
            for x in rows:
                f.write(json.dumps(x) + "\n")
    else:
        with open(os.path.join(raw, "one", "games.pgn"), "a") as f:
            f.write("\n")
    assert validate_dataset.main(["--data-dir", data, "--sources-dir", raw]) == 1
