#!/usr/bin/env python3
"""Score a fine-tuned Laya checkpoint on the held-out Carlsen decisions.

    python evaluate_laya.py --model ./laya-carlsen --test data/carlsen_wcc_laya_test.jsonl

Each row is answered with its own legal-move question, exactly as at training time, through
`laya.load(...).predict`. Reported: top-1 / top-3 accuracy, mean probability given to Carlsen's
move, the uniform-random baseline (mean 1/K) on the same rows, and breakdowns by whether the
position also occurs in training, by phase, by Carlsen's colour and by tier.

The budgets the checkpoint was trained with are stored in its config and used by default; a
row that would not fit is reported as an error rather than silently truncated.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="fine-tuned checkpoint directory")
    ap.add_argument("--test", required=True, help="Laya-format JSONL (e.g. carlsen_wcc_laya_test.jsonl)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--out", help="write per-row predictions here (JSONL)")
    args = ap.parse_args(argv)

    import laya
    agent = laya.load(args.model, device=args.device)
    rows = [json.loads(l) for l in open(args.test, encoding="utf-8") if l.strip()]
    groups = defaultdict(lambda: {"n": 0, "top1": 0, "top3": 0, "p_target": 0.0, "random": 0.0})
    truncated = 0
    out = open(args.out, "w", encoding="utf-8") if args.out else None
    for r in rows:
        res = agent.predict(r["state"], r["questions"])
        ans = res["answers"]["move"]
        truncated += bool(res.get("usage", {}).get("truncated"))
        probs = ans["probabilities"]
        target = r["expected"]["move"]
        ranked = sorted(probs, key=probs.get, reverse=True)
        meta = r.get("meta", {})
        keys = ["all", "tier=%s" % meta.get("tier"), "phase=%s" % meta.get("phase"),
                "carlsen=%s" % meta.get("carlsen_color"),
                "position_in_train=%s" % meta.get("position_in_train")]
        for k in keys:
            g = groups[k]
            g["n"] += 1
            g["top1"] += ranked[0] == target
            g["top3"] += target in ranked[:3]
            g["p_target"] += probs.get(target, 0.0)
            g["random"] += 1.0 / len(probs)
        if out:
            out.write(json.dumps({"id": r["id"], "target": target, "predicted": ranked[0], "top3": ranked[:3],
                                  "p_target": probs.get(target), "k": len(probs)}) + "\n")
    if out:
        out.close()
    summary = {k: {"n": g["n"], "top1": round(g["top1"] / g["n"], 4), "top3": round(g["top3"] / g["n"], 4),
                   "mean_p_target": round(g["p_target"] / g["n"], 4), "random_top1": round(g["random"] / g["n"], 4)}
               for k, g in sorted(groups.items())}
    summary["rows_with_truncated_state"] = truncated
    print(json.dumps(summary, indent=2))
    if truncated:
        print("WARNING: %d rows were truncated; retrain with larger --max-len/--head-max-len" % truncated,
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
