"""Laya token-budget mechanics, through laya 0.4.8's own item builder.

The real Laya tokenizer (ModernBERT's) needs a Hugging Face download, so these tests train a small
stand-in BPE tokenizer on the generated rows. Token counts therefore differ from the real ones;
what is tested is the mechanism: with Laya's default head budget the option texts are cut and items
are dropped, and with the widened budgets prepare_data.py certifies, nothing is cut or dropped.
Run `prepare_data.py --laya-check <checkpoint>` for the real numbers.
"""
import json
import os

import pytest

pytest.importorskip("torch")
pytest.importorskip("laya")
tokenizers = pytest.importorskip("tokenizers")
transformers = pytest.importorskip("transformers")

import build_dataset  # noqa: E402
import prepare_data  # noqa: E402
from laya.common import build_head  # noqa: E402
from laya.train import items_from_rows, to_internal  # noqa: E402

from test_pipeline import build, make_sources  # noqa: E402

SPECIALS = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]


def standin_checkpoint(root, texts):
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers
    tok = Tokenizer(models.BPE(unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.train_from_iterator(texts, trainers.BpeTrainer(vocab_size=1200, special_tokens=SPECIALS))
    fast = transformers.PreTrainedTokenizerFast(tokenizer_object=tok, pad_token="[PAD]", unk_token="[UNK]",
                                                cls_token="[CLS]", sep_token="[SEP]", mask_token="[MASK]")
    model_dir = os.path.join(root, "standin_ckpt")
    fast.save_pretrained(os.path.join(model_dir, "tokenizer"))
    with open(os.path.join(model_dir, "rl_agent_config.json"), "w") as f:
        json.dump({"max_len": 512, "head_max_len": 192}, f)
    return model_dir, fast


@pytest.fixture()
def prepared(tmp_path):
    raw, reg = make_sources(str(tmp_path))
    rc, data = build(str(tmp_path), raw, reg)
    assert rc == 0
    assert prepare_data.main(["--data-dir", data, "--test-frac", "0.3"]) == 0
    rows = [json.loads(l) for n in ("carlsen_wcc_laya_train.jsonl", "carlsen_wcc_laya_test.jsonl")
            for l in open(os.path.join(data, n))]
    texts = [r["state"] for r in rows] + [v for r in rows for v in r["questions"]["move"]["criteria"].values()]
    model_dir, tok = standin_checkpoint(str(tmp_path), texts)
    return data, rows, model_dir, tok


def test_default_budget_cuts_options(prepared):
    _data, rows, _model_dir, tok = prepared
    cut, kept = 0, []
    for r in rows:
        _ids, _markers, stats = build_head(tok, to_internal("move", r["questions"]["move"]), 192)
        cut += stats["tokens_per_option"] is not None
        kept.append(stats["tokens_per_option"])
    # Every position's move descriptions are cut to a few tokens each ([MASK] + the label, roughly):
    assert cut == len(rows) and max(kept) <= 16
    # Laya still builds the items -- the cut is silent, which is the problem.
    items, _skipped = items_from_rows(tok, rows, 512, 192)
    assert items


def test_widened_budget_keeps_everything(prepared):
    data, rows, model_dir, _tok = prepared
    rc = prepare_data.main(["--data-dir", data, "--test-frac", "0.3", "--laya-check", model_dir,
                            "--max-len", "2048", "--head-max-len", "1536"])
    assert rc == 0
    tb = json.load(open(os.path.join(data, "split_manifest.json")))["token_budget"]
    assert tb["violations"] == 0 and tb["laya_skipped"] == {} and tb["laya_items"] == tb["laya_rows"]


def test_budget_check_flags_a_too_small_budget(prepared):
    data, _rows, model_dir, _tok = prepared
    rc = prepare_data.main(["--data-dir", data, "--test-frac", "0.3", "--laya-check", model_dir,
                            "--max-len", "512", "--head-max-len", "192"])
    assert rc == 3
