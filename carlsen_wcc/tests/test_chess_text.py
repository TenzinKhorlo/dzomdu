"""Unit tests for the board/move renderers. Positions here are test fixtures, not dataset content."""
import random

import chess
import pytest

from chess_text import (describe_board, describe_move, game_phase, laya_input_for_fen, legal_options,
                        parse_board_description, position_key)
from sources_io import split_name, time_control_class


def random_positions(n, seed=7):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        b = chess.Board()
        for _ in range(rng.randint(0, 120)):
            moves = list(b.legal_moves)
            if not moves:
                break
            b.push(rng.choice(moves))
            out.append(b.copy(stack=False))
    return out[:n]


def test_description_round_trips_on_many_positions():
    for b in random_positions(1500):
        text = describe_board(b)
        assert parse_board_description(text) == b.fen()


def test_description_lists_every_piece():
    for b in random_positions(300, seed=11):
        text = describe_board(b)
        for sq, piece in b.piece_map().items():
            assert chess.square_name(sq) in text
        assert sum(1 for line in text.splitlines() if "king on" in line) == 2
        listed = sum(len(b.pieces(pt, c)) for pt in chess.PIECE_TYPES for c in chess.COLORS)
        assert listed == len(b.piece_map())


def test_tampered_description_is_rejected():
    b = chess.Board()
    # A moved pawn still describes a legal position, just not this one: the validator compares FENs.
    assert parse_board_description(describe_board(b).replace("a2, b2, c2", "a3, b2, c2")) != b.fen()
    with pytest.raises(ValueError):  # a non-canonical rendering does not re-render identically
        parse_board_description(describe_board(b).replace("a2, b2, c2", "b2, a2, c2"))
    with pytest.raises(ValueError):
        parse_board_description(describe_board(b).replace("White king on e1.\n", ""))


def test_options_equal_legal_moves_without_duplicates():
    for b in random_positions(400, seed=3):
        if b.is_game_over():
            continue
        opts = [o["uci"] for o in legal_options(b)]
        assert len(opts) == len(set(opts))
        assert sorted(opts) == sorted(m.uci() for m in b.legal_moves)


def test_all_four_promotions_including_capture_promotions():
    b = chess.Board("1r2k3/2P5/8/8/8/8/8/4K3 w - - 0 1")
    opts = {o["uci"]: o for o in legal_options(b)}
    for to in ("c8", "b8"):
        pieces = {opts["c7" + to + p]["promotion_piece"] for p in "qrbn"}
        assert pieces == {"queen", "rook", "bishop", "knight"}
    o = opts["c7b8q"]
    assert o["is_capture"] and o["captured_piece"] == "rook" and o["is_promotion"]
    assert o["description"].startswith("White pawn moves from c7 to b8, capturing the Black rook on b8, and promotes to a queen.")
    assert opts["c7c8q"]["gives_check"] and not opts["c7c8n"]["gives_check"]


def test_black_promotion_wording():
    b = chess.Board("4k3/8/8/8/8/8/1p6/4K3 b - - 0 1")
    o = {x["uci"]: x for x in legal_options(b)}["b2b1q"]
    assert o["description"] == "Black pawn moves from b2 to b1 and promotes to a queen. It gives check."


def test_castling_both_sides_and_colors():
    b = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    opts = {o["uci"]: o for o in legal_options(b)}
    assert opts["e1g1"]["is_castling"] and opts["e1g1"]["castling_side"] == "kingside"
    assert opts["e1g1"]["description"] == ("White castles kingside: the king moves from e1 to g1 and the rook "
                                           "moves from h1 to f1.")
    assert opts["e1c1"]["castling_side"] == "queenside" and opts["e1c1"]["san"] == "O-O-O"
    b.turn = chess.BLACK
    opts = {o["uci"]: o for o in legal_options(b)}
    assert opts["e8c8"]["description"].endswith("rook moves from a8 to d8.")
    assert not opts["e8c8"]["is_capture"]


def test_castling_through_check_is_not_offered():
    b = chess.Board("4k3/8/8/8/8/8/6r1/4K2R w K - 0 1")
    assert "e1g1" not in {o["uci"] for o in legal_options(b)}


def test_en_passant():
    b = chess.Board()
    for san in ("e4", "a6", "e5", "d5"):
        b.push_san(san)
    opts = {o["uci"]: o for o in legal_options(b)}
    o = opts["e5d6"]
    assert o["is_en_passant"] and o["is_capture"] and o["captured_square"] == "d5"
    assert o["description"] == "White pawn moves from e5 to d6, capturing the Black pawn on d5 en passant."
    assert "may capture en passant on d6" in describe_board(b)
    assert position_key(b).endswith(" d6")


def test_unavailable_en_passant_is_not_described():
    b = chess.Board()
    b.push_san("e4")  # no black pawn can capture
    assert "No en-passant capture is available." in describe_board(b)
    assert position_key(b).split()[3] == "-"


def test_check_and_checkmate_flags():
    b = chess.Board()
    for san in ("f3", "e5", "g4"):
        b.push_san(san)
    o = {x["uci"]: x for x in legal_options(b)}["d8h4"]
    assert o["gives_check"] and o["gives_checkmate"]
    assert o["description"].endswith("It gives checkmate.")
    b.push_san("Qh4#")
    assert "White is in check from the Black queen on h4." in describe_board(b)


def test_neutral_move_wording():
    o = {x["uci"]: x for x in legal_options(chess.Board())}["g1f3"]
    assert o["description"] == "White knight moves from g1 to f3, an empty square."
    assert not any(o[k] for k in ("is_capture", "gives_check", "is_castling", "is_promotion", "is_en_passant"))


def test_illegal_move_rejected():
    with pytest.raises(ValueError):
        describe_move(chess.Board(), chess.Move.from_uci("e2e5"))


def test_phase_heuristic():
    assert game_phase(chess.Board()) == "opening"
    assert game_phase(chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 40")) == "endgame"


def test_inference_input_matches_training_rendering():
    row = laya_input_for_fen(chess.STARTING_FEN)
    crit = row["questions"]["move"]["criteria"]
    assert len(crit) == 20 and crit["e2e4"].endswith("SAN: e4.")
    assert row["state"] == describe_board(chess.Board())


@pytest.mark.parametrize("tc,cls", [("40/7200:3600", "classical"), ("5400+30", "classical"), ("900+10", "rapid"),
                                    ("180+2", "blitz"), ("?", None), ("-", None), ("weird", None)])
def test_time_control(tc, cls):
    assert time_control_class(tc) == cls


@pytest.mark.parametrize("name,surname,initial", [("Carlsen, Magnus", "carlsen", "m"), ("Carlsen,M", "carlsen", "m"),
                                                  ("Magnus Carlsen", "carlsen", "m"), ("Carlsen", "carlsen", "")])
def test_split_name(name, surname, initial):
    assert split_name(name) == (surname, initial)
