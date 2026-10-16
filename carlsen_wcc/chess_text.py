"""Deterministic natural-language rendering of chess positions and legal moves.

Everything here is derived from python-chess. Nothing is guessed, and nothing strategic is
claimed: a move description says which piece moves where, what it captures, and whether it
castles, promotes, captures en passant, gives check or gives checkmate. That is all.

`parse_board_description` inverts `describe_board`, so the validator can prove that every
description in the dataset encodes exactly the position in its FEN field.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import chess

COLOR_NAME = {chess.WHITE: "White", chess.BLACK: "Black"}
PIECE_NAME = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}
PIECE_PLURAL = {
    chess.PAWN: "pawns", chess.KNIGHT: "knights", chess.BISHOP: "bishops",
    chess.ROOK: "rooks", chess.QUEEN: "queens", chess.KING: "king",
}
PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
# Listing order in the description: king first, pawns last.
DESCRIBE_ORDER = (chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN)
PROMOTION_PIECES = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)

DEFAULT_QUESTION = "Which move would Magnus Carlsen play?"


def position_key(board: chess.Board) -> str:
    """Placement, side to move, castling rights and legal en-passant square.

    The first four FEN fields, i.e. position identity in the sense of the repetition rule.
    The move counters are left out, so the same position reached at different move numbers
    is recognised as the same position.
    """
    return " ".join(board.fen().split()[:4])


def square_shade(square: int) -> str:
    return "light" if chess.BB_LIGHT_SQUARES & chess.BB_SQUARES[square] else "dark"


def _squares_sorted(squares) -> List[str]:
    # File first, then rank: a2, b2, ..., matches how pawn chains are usually read.
    return [chess.square_name(s) for s in sorted(squares, key=lambda s: (chess.square_file(s), chess.square_rank(s)))]


def material(board: chess.Board, color: bool) -> int:
    return sum(PIECE_VALUE[p] * len(board.pieces(p, color)) for p in PIECE_VALUE)


def non_pawn_material(board: chess.Board) -> int:
    return sum(PIECE_VALUE[p] * len(board.pieces(p, c))
               for p in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for c in chess.COLORS)


def game_phase(board: chess.Board) -> str:
    """A documented heuristic, used only for coverage statistics, never as a model target.

    endgame:    combined non-pawn material of both sides <= 26 (N=B=3, R=5, Q=9; 62 at the start)
    opening:    otherwise, full move number <= 12
    middlegame: everything else
    """
    if non_pawn_material(board) <= 26:
        return "endgame"
    if board.fullmove_number <= 12:
        return "opening"
    return "middlegame"


def _castling_sentence(board: chess.Board) -> str:
    parts = []
    for color in chess.COLORS:
        k = board.has_kingside_castling_rights(color)
        q = board.has_queenside_castling_rights(color)
        name = COLOR_NAME[color]
        if k and q:
            parts.append("%s keeps kingside and queenside castling rights" % name)
        elif k:
            parts.append("%s keeps kingside castling rights only" % name)
        elif q:
            parts.append("%s keeps queenside castling rights only" % name)
        else:
            parts.append("%s has no castling rights" % name)
    return "; ".join(parts) + "."


def _check_sentence(board: chess.Board) -> str:
    side = COLOR_NAME[board.turn]
    checkers = board.checkers()
    if not checkers:
        return "%s is not in check." % side
    names = []
    for sq in sorted(checkers):
        p = board.piece_at(sq)
        names.append("the %s %s on %s" % (COLOR_NAME[p.color], PIECE_NAME[p.piece_type], chess.square_name(sq)))
    return "%s is in check from %s." % (side, " and ".join(names))


def _en_passant_sentence(board: chess.Board) -> str:
    if not board.has_legal_en_passant():
        return "No en-passant capture is available."
    ep = board.ep_square
    victim = ep - 8 if board.turn == chess.WHITE else ep + 8
    return ("%s may capture en passant on %s (the %s pawn on %s has just advanced two squares)."
            % (COLOR_NAME[board.turn], chess.square_name(ep), COLOR_NAME[not board.turn],
               chess.square_name(victim)))


def describe_board(board: chess.Board) -> str:
    """The complete position in plain English. Every piece on the board is listed."""
    lines = ["Current position:",
             "- %s to move." % COLOR_NAME[board.turn],
             "- Full move number: %d." % board.fullmove_number,
             "- Halfmove clock (half-moves since the last capture or pawn move): %d." % board.halfmove_clock]
    for color in (chess.WHITE, chess.BLACK):
        name = COLOR_NAME[color]
        for pt in DESCRIBE_ORDER:
            squares = board.pieces(pt, color)
            if pt == chess.KING:
                lines.append("- %s king on %s." % (name, _squares_sorted(squares)[0]))
                continue
            if pt == chess.BISHOP and squares:
                listed = ", ".join("%s (%s square)" % (s, square_shade(chess.parse_square(s)))
                                   for s in _squares_sorted(squares))
            else:
                listed = ", ".join(_squares_sorted(squares))
            if not squares:
                lines.append("- %s %s: none." % (name, PIECE_PLURAL[pt]))
            else:
                lines.append("- %s %s (%d): %s." % (name, PIECE_PLURAL[pt], len(squares), listed))
    lines.append("- Castling rights: " + _castling_sentence(board))
    lines.append("- Check: " + _check_sentence(board))
    lines.append("- En passant: " + _en_passant_sentence(board))
    lines.append("- Material (pawn 1, knight 3, bishop 3, rook 5, queen 9): White %d, Black %d."
                 % (material(board, chess.WHITE), material(board, chess.BLACK)))
    return "\n".join(lines)


_SQ = r"[a-h][1-8]"


def parse_board_description(text: str) -> str:
    """Rebuild the FEN that `describe_board` rendered. Raises ValueError on anything unexpected."""
    board = chess.Board.empty()
    turn = fullmove = halfmove = None
    castling = ""
    ep = "-"
    seen_kings = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line == "Current position:":
            continue
        m = re.fullmatch(r"- (White|Black) to move\.", line)
        if m:
            turn = m.group(1)
            continue
        m = re.fullmatch(r"- Full move number: (\d+)\.", line)
        if m:
            fullmove = int(m.group(1))
            continue
        m = re.fullmatch(r"- Halfmove clock \(half-moves since the last capture or pawn move\): (\d+)\.", line)
        if m:
            halfmove = int(m.group(1))
            continue
        m = re.fullmatch(r"- (White|Black) king on (%s)\." % _SQ, line)
        if m:
            color = m.group(1) == "White"
            board.set_piece_at(chess.parse_square(m.group(2)), chess.Piece(chess.KING, color))
            seen_kings.add(color)
            continue
        m = re.fullmatch(r"- (White|Black) (queens|rooks|bishops|knights|pawns): none\.", line)
        if m:
            continue
        m = re.fullmatch(r"- (White|Black) (queens|rooks|bishops|knights|pawns) \((\d+)\): (.+)\.", line)
        if m:
            color = m.group(1) == "White"
            pt = {v: k for k, v in PIECE_PLURAL.items() if k != chess.KING}[m.group(2)]
            squares = re.findall(_SQ, m.group(4))
            if len(squares) != int(m.group(3)):
                raise ValueError("count mismatch in line %r" % line)
            for s in squares:
                sq = chess.parse_square(s)
                if board.piece_at(sq) is not None:
                    raise ValueError("square %s listed twice" % s)
                board.set_piece_at(sq, chess.Piece(pt, color))
            if pt == chess.BISHOP:
                for s, shade in re.findall(r"(%s) \((light|dark) square\)" % _SQ, m.group(4)):
                    if square_shade(chess.parse_square(s)) != shade:
                        raise ValueError("wrong square shade for %s" % s)
            continue
        if line.startswith("- Castling rights: "):
            for color, letters in (("White", "KQ"), ("Black", "kq")):
                if "%s keeps kingside and queenside" % color in line:
                    castling += letters
                elif "%s keeps kingside castling rights only" % color in line:
                    castling += letters[0]
                elif "%s keeps queenside castling rights only" % color in line:
                    castling += letters[1]
                elif "%s has no castling rights" % color not in line:
                    raise ValueError("unreadable castling line %r" % line)
            continue
        if line.startswith("- Check: ") or line.startswith("- Material "):
            continue  # derived facts; checked against the rebuilt board below
        if line.startswith("- En passant: "):
            m = re.search(r"en passant on (%s)" % _SQ, line)
            ep = m.group(1) if m else "-"
            continue
        raise ValueError("unrecognised description line %r" % line)
    if turn is None or fullmove is None or halfmove is None or seen_kings != {True, False}:
        raise ValueError("description is missing side to move, counters or a king")
    fen = "%s %s %s %s %d %d" % (board.board_fen(), "w" if turn == "White" else "b",
                                 castling or "-", ep, halfmove, fullmove)
    rebuilt = chess.Board(fen)
    # The derived sentences must agree with the rebuilt position too.
    if describe_board(rebuilt) != text:
        raise ValueError("description does not re-render identically from its own FEN %s" % fen)
    return fen


# ------------------------------------------------------------------------------------- moves

def describe_move(board: chess.Board, move: chess.Move) -> Dict[str, Any]:
    """Factual properties of a legal move, and a one-sentence description of them."""
    if not board.is_legal(move):
        raise ValueError("illegal move %s in %s" % (move.uci(), board.fen()))
    piece = board.piece_at(move.from_square)
    mover = COLOR_NAME[piece.color]
    opp = COLOR_NAME[not piece.color]
    frm, to = chess.square_name(move.from_square), chess.square_name(move.to_square)
    is_castling = board.is_castling(move)
    is_ep = board.is_en_passant(move)
    captured_sq: Optional[int] = None
    captured = None
    if is_ep:
        captured_sq = move.to_square + (-8 if piece.color == chess.WHITE else 8)
        captured = board.piece_at(captured_sq)
    elif not is_castling and board.piece_at(move.to_square) is not None:
        captured_sq = move.to_square
        captured = board.piece_at(move.to_square)
    san = board.san(move)
    gives_check = board.gives_check(move)
    board.push(move)
    try:
        gives_checkmate = board.is_checkmate()
        gives_stalemate = board.is_stalemate()
    finally:
        board.pop()

    if is_castling:
        side = "kingside" if board.is_kingside_castling(move) else "queenside"
        rank = "1" if piece.color == chess.WHITE else "8"
        rook_from, rook_to = ("h" + rank, "f" + rank) if side == "kingside" else ("a" + rank, "d" + rank)
        text = ("%s castles %s: the king moves from %s to %s and the rook moves from %s to %s."
                % (mover, side, frm, to, rook_from, rook_to))
    elif is_ep:
        text = ("%s pawn moves from %s to %s, capturing the %s pawn on %s en passant."
                % (mover, frm, to, opp, chess.square_name(captured_sq)))
    else:
        text = "%s %s moves from %s to %s" % (mover, PIECE_NAME[piece.piece_type], frm, to)
        if captured is not None:
            text += ", capturing the %s %s on %s" % (opp, PIECE_NAME[captured.piece_type], to)
        if move.promotion:
            text += ("," if captured is not None else "") + " and promotes to a %s" % PIECE_NAME[move.promotion]
        elif captured is None:
            text += ", an empty square"
        text += "."
    if gives_checkmate:
        text += " It gives checkmate."
    elif gives_check:
        text += " It gives check."
    elif gives_stalemate:
        text += " It leaves the opponent stalemated."

    return {
        "uci": move.uci(),
        "san": san,
        "piece": PIECE_NAME[piece.piece_type],
        "color": mover.lower(),
        "from_square": frm,
        "to_square": to,
        "is_capture": captured is not None,
        "captured_piece": PIECE_NAME[captured.piece_type] if captured is not None else None,
        "captured_square": chess.square_name(captured_sq) if captured_sq is not None else None,
        "gives_check": gives_check,
        "gives_checkmate": gives_checkmate,
        "gives_stalemate": gives_stalemate,
        "is_castling": is_castling,
        "castling_side": ("kingside" if board.is_kingside_castling(move) else "queenside") if is_castling else None,
        "is_promotion": move.promotion is not None,
        "promotion_piece": PIECE_NAME[move.promotion] if move.promotion else None,
        "is_en_passant": is_ep,
        "description": text,
    }


def legal_options(board: chess.Board) -> List[Dict[str, Any]]:
    """Every legal move, described, in a canonical order (sorted by UCI string)."""
    return [describe_move(board, m) for m in sorted(board.legal_moves, key=lambda m: m.uci())]


# --------------------------------------------------------------------------------- Laya rows

def laya_instructions(side_to_move: str, player: str = "Magnus Carlsen") -> str:
    return ("%s is playing the %s pieces and it is %s's turn. Which one of the legal moves listed "
            "would %s play in this position?" % (player, side_to_move, side_to_move, player))


def laya_criterion(option: Dict[str, Any], include_san: bool = True) -> str:
    text = option["description"]
    if include_san:
        text += " SAN: %s." % option["san"]
    return text


def laya_state(board_description: str, fen: Optional[str] = None, last_move: Optional[str] = None) -> str:
    parts = [board_description]
    if last_move:
        parts.append("Previous move: " + last_move)
    if fen:
        parts.append("FEN: " + fen)
    return "\n".join(parts)


def laya_question(board: chess.Board, options: List[Dict[str, Any]], include_san: bool = True,
                  player: str = "Magnus Carlsen") -> Dict[str, Any]:
    return {
        "type": "choice",
        "instructions": laya_instructions(COLOR_NAME[board.turn], player),
        "criteria": {o["uci"]: laya_criterion(o, include_san) for o in options},
    }


def laya_input_for_fen(fen: str, include_san: bool = True, include_fen: bool = False) -> Dict[str, Any]:
    """`{state, questions}` for any position, e.g. an unseen one at inference time.

    Built by exactly the functions that built the training rows, so training and inference see
    the same rendering.
    """
    board = chess.Board(fen)
    if board.is_game_over():
        raise ValueError("no legal moves in %s" % fen)
    options = legal_options(board)
    return {"state": laya_state(describe_board(board), board.fen() if include_fen else None),
            "questions": {"move": laya_question(board, options, include_san)}}
