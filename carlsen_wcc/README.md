# Magnus Carlsen decision dataset for Laya

A reproducible pipeline that turns authentic PGN game scores into one training example per
Magnus Carlsen move. Each example holds the board in plain English, every legal move with a
factual description, and the move Carlsen actually played as the target. The pipeline also
produces the `{state, questions, expected}` files that `laya-train` (Laya 0.4.8) reads.

Nothing in the dataset is written by hand or by a language model. Positions, legal moves and
descriptions come from python-chess, and targets come from the source PGNs. Every record traces
back to a game, a ply and a SHA-256-pinned source file.

> **Status.** The pipeline and its tests are complete. **No dataset has been generated yet**,
> because the container this was built in could not reach any chess database. Download the
> sources listed below, then run the four commands in [Reproduce](#reproduce).
> `validate_dataset.py` has to pass before the data counts as verified.

## Scope: tiers

| Tier | Games | Master file |
|---|---|---|
| **A** | World Championship classical games Carlsen **won** (the original research scope) | `carlsen_wcc_master.jsonl` |
| B | World Championship classical games Carlsen drew or lost | `carlsen_wcc_draws_losses_master.jsonl` |
| C | World Championship rapid/blitz tiebreak games (separate, never mixed in unlabelled) | `carlsen_wcc_tiebreaks_master.jsonl` |
| **D** | Carlsen's **won** games in other over-the-board classical events (the main expansion) | `carlsen_classical_wins_master.jsonl.gz` |
| E | Carlsen's drawn or lost games in other classical events | `carlsen_classical_draws_losses_master.jsonl.gz` |

The default training set is **A + D**, all wins. The default test set is held-out tier-A games.

### Expected tier-A games

These come from `match_registry.json`, which was compiled before any source was read. The build
checks every claim against the PGNs and exits with status 2 on any disagreement.

| Match | Carlsen classical wins (game no.) | Notes |
|---|---|---|
| 2013 Chennai vs Anand | 5 (W), 6 (B), 9 (B) | 10 games played |
| 2014 Sochi vs Anand | 2 (W), 6 (W), 11 (B) | Carlsen lost game 3 |
| 2016 New York vs Karjakin | 10 (W) | lost game 8; rapid tiebreak 3–1 (tier C) |
| 2018 London vs Caruana | none | all 12 classical games drawn; rapid tiebreak 3–0 (tier C) |
| 2021 Dubai vs Nepomniachtchi | 6 (W), 8 (W), 9 (B), 11 (B) | game 6 lasted 136 moves |

That is **11 classical wins**, roughly 600 Carlsen decisions; the build reports the exact count.
Tier D adds his other classical wins, likely tens of thousands of decisions depending on the
source database.

## Sources

The container this was written in could not reach these hosts, so download them yourself. Use
at least **two independent** sources: tiers A–C need two agreeing copies of every game.

| Source | What to get |
|---|---|
| PGN Mentor | `https://www.pgnmentor.com/players/Carlsen.zip` (all tiers), or the event files on `https://www.pgnmentor.com/files.html` |
| The Week in Chess | weekly `https://theweekinchess.com/zips/twicNNNNg.zip` issues that cover each match's dates, and any other events you want cross-checked |
| Lichess broadcasts | the official broadcasts of each match → "Download all games" |
| chessgames.com | per-game PGN downloads |

Register each one without modifying the files:

```bash
# downloads directly (needs network access to the host)
python fetch_sources.py download --name pgnmentor --publisher "PGN Mentor" \
    --url https://www.pgnmentor.com/players/Carlsen.zip --priority 1

# or: copy files you downloaded into sources/raw/<name>/ and register them
python fetch_sources.py register --name twic --publisher "The Week in Chess" \
    --url https://theweekinchess.com/zips/ --retrieved 2026-10-16 --priority 2
python fetch_sources.py list
```

`source.json` records the URL, the retrieval date and each file's SHA-256. Any later edit to a
file makes the build and the validator refuse it. If two sources are copies of one database
(mirrors), give them the same `--lineage`, so they cannot count as independent confirmation.

## Reproduce

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt            # python-chess; laya + transformers for the token checks

python build_dataset.py                    # sources/raw/* -> data/*master*, games PGNs, provenance, build_log.json
python prepare_data.py \
    --laya-check /path/to/laya/checkpoint \
    --max-len 2048 --head-max-len 1536     # -> data/carlsen_wcc_laya_{train,test,test_novel}.jsonl
python validate_dataset.py                 # -> data/dataset_report.json; exit 0 only if every check passed
python -m pytest -q tests                  # 36 tests; fixtures are synthetic games between fictional players
```

To get the Laya checkpoint directory, run
`huggingface-cli download convaiinnovations/laya --local-dir ./laya-base`, or point at the
snapshot that `laya.load` already cached.

## Output files (`data/`)

| File | Contents |
|---|---|
| `carlsen_wcc_master.jsonl` | Tier A: one record per Carlsen move, with full provenance (other tiers alongside) |
| `carlsen_wcc_laya_train.jsonl` | Laya rows for training (tiers from `--train-tiers`, default `AD`) |
| `carlsen_wcc_laya_test.jsonl` | Laya rows for held-out tier-A games; `meta.position_in_train` marks shared positions |
| `carlsen_wcc_laya_test_novel.jsonl` | The test rows whose position never occurs in training |
| `carlsen_wcc_games.pgn` | Verbatim source text of every tier-A game (`*_games.pgn` for other tiers) |
| `carlsen_wcc_sources.json` | Every tier A–C game: each source copy, its SHA-256, original PGN, headers, cross-check result |
| `carlsen_classical_sources.json` | Tier D/E provenance: source, file hash and game index for each copy |
| `build_log.json` | Every excluded copy and game, with its reason; registry check; issues |
| `split_manifest.json` | The split, its method, overlap counts, random baseline and the token-budget certificate |
| `dataset_report.json` | Counts and distributions, conflicting-label positions, and every validation check's result |

### Master record (abridged)

```json
{
  "id": "2013_wcc_game5_ply001", "game_id": "2013_wcc_game5", "tier": "A",
  "dataset": "wcc_classical", "match_id": "2013_wcc", "championship_year": 2013, "game_number": 5,
  "event": "...", "site": "...", "date": "2013-11-15", "round": "5",
  "white": "Carlsen, Magnus", "black": "Anand, Viswanathan", "result": "1-0",
  "carlsen_result": "win", "carlsen_color": "white",
  "ply": 1, "fullmove_number": 1, "side_to_move": "white", "phase": "opening",
  "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
  "position_key": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",
  "board_description": "Current position:\n- White to move.\n...",
  "previous_move": null,
  "question": "Which move would Magnus Carlsen play?",
  "num_legal_moves": 20,
  "options": [{"uci": "c2c4", "san": "c4", "piece": "pawn", "color": "white",
               "from_square": "c2", "to_square": "c4", "is_capture": false,
               "captured_piece": null, "captured_square": null, "gives_check": false,
               "gives_checkmate": false, "gives_stalemate": false, "is_castling": false,
               "castling_side": null, "is_promotion": false, "promotion_piece": null,
               "is_en_passant": false,
               "description": "White pawn moves from c2 to c4, an empty square."}],
  "target": "<the move in the source PGN>", "target_san": "...", "target_description": "...",
  "source": {"copy": "pgnmentor:Carlsen.zip!Carlsen.pgn#1234", "url": "...", "file_sha256": "..."},
  "sources": ["pgnmentor", "twic"], "independent_sources": 2, "cross_checked": true
}
```

(The values above show the format only; they do not come from a source.)

### Board description

The description is generated from python-chess and lists every piece. `validate_dataset.py`
parses it back into a FEN and requires an exact match:

```
Current position:
- White to move.
- Full move number: 1.
- Halfmove clock (half-moves since the last capture or pawn move): 0.
- White king on e1.
- White queens (1): d1.
- White rooks (2): a1, h1.
- White bishops (2): c1 (dark square), f1 (light square).
- White knights (2): b1, g1.
- White pawns (8): a2, b2, c2, d2, e2, f2, g2, h2.
- Black king on e8.
  ... (every Black piece likewise)
- Castling rights: White keeps kingside and queenside castling rights; Black keeps ...
- Check: White is not in check.
- En passant: No en-passant capture is available.
- Material (pawn 1, knight 3, bishop 3, rook 5, queen 9): White 39, Black 39.
```

### Move descriptions

Descriptions state facts only, never strategy:

- `g1f3`: White knight moves from g1 to f3, an empty square.
- `f3e5`: White knight moves from f3 to e5, capturing the Black pawn on e5.
- `e1g1`: White castles kingside: the king moves from e1 to g1 and the rook moves from h1 to f1.
- `e5d6`: White pawn moves from e5 to d6, capturing the Black pawn on d5 en passant.
- `b2b1q`: Black pawn moves from b2 to b1 and promotes to a queen. It gives check.

Each of the four promotion pieces is its own option. Engine commentary is deliberately absent. If
you add it, keep it in a separate file keyed by record `id`, so that historical facts, legal-move
facts and engine opinion stay apart.

## What Laya 0.4.8 does with these rows (from its source)

Read from `laya/train.py`, `laya/common.py` and `laya/agent.py` of the installed wheel.

1. **One sequence per question.** `build_sequence` produces
   `[CLS] "choice question: <instructions>" [SEP] [MASK] opt0 [MASK] opt1 … [SEP] <state> [SEP]`,
   cut to `max_len`. Each option is scored from its own `[MASK]` embedding, so the number of
   options can differ from row to row. Dynamic legal-move sets are therefore native to the
   architecture.
2. **Each row trains on its own question.** `items_from_rows` converts every row's own
   `questions` dict, so one shared id (`"move"`) with a different move list per row is correct.
   The `Conflicting schema detected for question 'move'` warning comes from code that runs
   *after* training and only writes a convenience `questions.json`. It has no effect on training,
   which is why unique, FEN-derived question ids changed nothing. At inference, always pass the
   row's own question (`chess_text.laya_input_for_fen` builds it for any FEN) and ignore the
   saved `questions.json`.
3. **The default budgets silently destroy this input.** `head_max_len` (192 on the English
   checkpoint) is the token budget for instructions plus all options.
   - When the options don't fit, `build_head` cuts every option to `(head_max_len − 16) / K`
     tokens. With 35 legal moves that is 5 tokens, `[MASK]` included, so the model sees little
     more than the UCI label and none of the description.
   - The instructions are cut as well.
   - Options whose cut text becomes identical are dropped as `options_collapsed`, which can
     remove whole positions.
   - The state is then cut to whatever is left of `max_len` (512).

   `tests/test_laya_budget.py` reproduces the cutting through Laya's own `build_head` and
   `items_from_rows`. **This is the most likely reason the earlier v1–v3 runs scored near the
   random baseline.** The longer English state in v3 left even less room.
4. **The fix is to raise the budgets and certify them.** Train with `--max-len 2048
   --head-max-len 1536`. ModernBERT-large uses rotary position embeddings and was pretrained to
   8192 tokens, so this stays inside its range. `finetune` writes both values into the saved
   config, so inference uses the same budgets. `prepare_data.py --laya-check <checkpoint>` runs
   Laya's own `items_from_rows` with the real tokenizer and fails unless every row fits uncut
   (no per-option cut, no instruction cut, no state truncation, no skipped item). Laya also caps
   each option at 48 tokens; the check enforces that too. It prints the minimum budgets that fit.
5. **Option order.** Options are written sorted by UCI. Train with `--shuffle-options` so the
   model cannot learn a slot prior; Laya re-permutes each epoch through the same path inference
   uses. `option_layout="parallel"` (transformers ≥ 5) would make the encoder fully order-blind,
   but it is a property of the weights, and the published checkpoints are sequential.
6. **Limits to know.**
   - The act head encodes `K/255`, so up to 255 options are fine. Chess never exceeds 218.
   - `laya-train` uses one device (`cuda:0`); with two GPUs, run two configurations in parallel
     with `CUDA_VISIBLE_DEVICES`.
   - 10% of the training items (at most 400) are held back for temperature calibration.
   - `--eval` labels the run `overlapping_eval` whenever any test position also occurs in
     training. Opening positions always do, so for a strictly held-out label use
     `carlsen_wcc_laya_test_novel.jsonl`.

### Train and evaluate

```bash
laya-train --data data/carlsen_wcc_laya_train.jsonl \
           --eval data/carlsen_wcc_laya_test.jsonl \
           --base /path/to/laya/checkpoint --out ./laya-carlsen \
           --max-len 2048 --head-max-len 1536 --shuffle-options \
           --epochs 6 --micro-batch 8 --grad-accum 8 --loss soft-ce

python evaluate_laya.py --model ./laya-carlsen --test data/carlsen_wcc_laya_test.jsonl --out preds.jsonl
python evaluate_laya.py --model ./laya-carlsen --test data/carlsen_wcc_laya_test_novel.jsonl
```

`evaluate_laya.py` reports top-1 and top-3 accuracy and the mean probability given to Carlsen's
move. Each is broken down by tier, phase, colour and whether the position was seen in training,
next to the uniform-random baseline (mean 1/K) for the same rows. Compare against that baseline:
4–8% top-1 is roughly what random choice among 20–40 legal moves scores.

Both `laya-train` and `evaluate_laya.py` were run end to end on synthetic fixture files with a
tiny randomly initialised checkpoint (`skipped {}`, no truncation), so the file format and
budgets are known to work. They have not yet been run on the real checkpoint or the real data.

## Split methodology

- **By game.** No game contributes to both train and test. `prepare_data.py` asserts this, and
  the validator re-checks it from the written files.
- **Balanced (default).** An exhaustive, deterministic search over subsets of tier-A games picks
  the test set. It needs at least one Carlsen-White and one Carlsen-Black win. It prefers a test
  share closest to `--test-frac` (default 20%), then the fewest test positions also seen in
  training, then a seeded hash. The choice and its numbers go in `split_manifest.json`, and
  `--test-games` fixes it explicitly.
- **Temporal** (`--split temporal`). This holds out the 2021 match (4 wins). It also drops tier
  D/E training games dated on or after the first test game, unless `--allow-future-train`.
  - What it measures: generalisation to Carlsen's later play against an opponent unseen in WCC
    play, a stricter and more realistic test.
  - What it costs: about 45% of tier-A decisions, and the result conflates time drift with
    opponent and opening drift.
- **Shared positions.** Opening positions recur across games; for example, the starting position
  appears whenever Carlsen has White. These are flagged rather than deleted:
  `meta.position_in_train` on every test row, plus the separate `_test_novel` file.
- **Conflicting labels.** The same position with different Carlsen moves (`1.c4`, `1.e4`, `1.d4`
  from the starting position) is kept as separate records with their own provenance. The counts
  are in `dataset_report.json`.
- **No future information in inputs.** The model sees the position and its legal moves.
  Optionally (`--include-last-move`) it also sees the opponent's previous move, which is past
  information. Results, later moves and game outcome stay in `meta`, which Laya ignores.

## Validation (`validate_dataset.py`)

The validator re-derives everything from the source files and fails on any mismatch. Its checks:

- **Source integrity:** file hashes match, and each game sits at its recorded index.
- **Cross-check:** every copy, including the stored original PGN text, replays to the same moves
  and result.
- **Games PGN:** the games PGN files hold exactly the dataset's games.
- **Replay:** every move is legal in sequence.
- **FEN:** each record's FEN matches the replayed position.
- **Target:** each target matches the source move in UCI and SAN.
- **Coverage:** every Carlsen move has exactly one record.
- **Legal options:** options exactly equal the legal-move set, with no duplicates.
- **Promotions:** all four promotion pieces are offered.
- **Option facts:** every option's flags and wording match a fresh computation.
- **Board description:** each description parses back to its FEN.
- **Results:** results, colours and tiers are consistent.
- **Laya schema:** the rows are structurally valid Laya rows.
- **Laya library:** laya's own `to_internal` and `target_from_expected` accept every row.
- **Split:** the split is clean.

The first 50 failures of each check are written to `dataset_report.json`.

## Known limitations

- **Tier D/E time controls.** These tiers rely on a `TimeControl` header when present. Otherwise
  an event-name/site filter excludes rapid, blitz, online and odd formats, and same-day rematches
  are treated as probable armageddon games. Every exclusion and its reason is in
  `build_log.json`; `event_overrides.json` corrects individual events.
- **Single-source games.** Tier D/E games with only one source are kept, marked
  `cross_checked: false`. Tiers A–C require two independent sources.
- **Result evidence.** Results come from PGN headers, checked across sources and against the
  final board when it is mate or stalemate. Resignations cannot be verified from the moves alone.
- **Phase labels.** The labels (opening / middlegame / endgame) use a documented material and
  move-number heuristic. They are for coverage statistics only.
- **Dataset size.** Even tens of thousands of decisions are small for move prediction. Models
  built specifically to imitate a player train on millions of positions. Report accuracy against
  the random baseline and on the novel-position test file.
