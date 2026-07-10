#!/usr/bin/env python3
"""Evaluate Reddit Intelligence v2 against a labeled JSONL corpus.

Each line must contain ``topic``, ``thread`` (a normalized Reddit record),
``relevant`` (boolean), ``lenses`` (list), and ``purchase_intent``.  This tool
does not manufacture a gold corpus; it makes manual labels reproducible and
turns the acceptance gates into a machine-readable CI report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from reddit_intelligence import (
    RELEVANT_THRESHOLD, deterministic_relevance,
    infer_purchase_intent, lens_hints,
)


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    tp = fp = tn = fn = 0
    lens_tp = lens_fp = lens_fn = 0
    purchase_fp = purchase_negatives = 0
    high_engagement_negatives = high_engagement_promoted = 0
    for row in rows:
        thread = row["thread"]
        score, _ = deterministic_relevance(
            thread, row["topic"], row.get("aliases", []), set(row.get("dedicated_subreddits", [])),
            row.get("negative_anchors", []),
        )
        predicted_relevant = score >= RELEVANT_THRESHOLD
        expected_relevant = bool(row["relevant"])
        if predicted_relevant and expected_relevant:
            tp += 1
        elif predicted_relevant and not expected_relevant:
            fp += 1
        elif not predicted_relevant and expected_relevant:
            fn += 1
        else:
            tn += 1
        if not expected_relevant and thread.get("upvotes", 0) + thread.get("comment_count", 0) >= 500:
            high_engagement_negatives += 1
            high_engagement_promoted += int(predicted_relevant)
        if expected_relevant:
            lenses, _ = lens_hints(thread, float("inf"))
            predicted = set(lenses)
            expected = set(row.get("lenses", []))
            lens_tp += len(predicted & expected)
            lens_fp += len(predicted - expected)
            lens_fn += len(expected - predicted)
            predicted_purchase = infer_purchase_intent(f"{thread.get('title','')} {thread.get('body','')}", lenses)
            expected_purchase = row.get("purchase_intent", "none")
            if expected_purchase in {"none", "curiosity"}:
                purchase_negatives += 1
                purchase_fp += int(predicted_purchase in {"evaluating", "willing_to_pay", "active_switching"})
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    lens_precision = safe_div(lens_tp, lens_tp + lens_fp)
    lens_recall = safe_div(lens_tp, lens_tp + lens_fn)
    lens_f1 = safe_div(2 * lens_precision * lens_recall, lens_precision + lens_recall)
    metrics = {
        "examples": len(rows), "relevance_precision": round(precision, 4),
        "relevance_recall": round(recall, 4), "lens_micro_f1": round(lens_f1, 4),
        "false_purchase_intent_rate": round(safe_div(purchase_fp, purchase_negatives), 4),
        "high_engagement_off_topic_promotion_rate": round(safe_div(high_engagement_promoted, high_engagement_negatives), 4),
    }
    gates = {
        "corpus_has_300_examples": len(rows) >= 300,
        "relevance_precision": precision >= 0.92,
        "relevance_recall": recall >= 0.85,
        "lens_f1": lens_f1 >= 0.85,
        "false_purchase_intent": safe_div(purchase_fp, purchase_negatives) < 0.05,
        "high_engagement_off_topic": safe_div(high_engagement_promoted, high_engagement_negatives) < 0.02,
    }
    return {"metrics": metrics, "gates": gates, "passed": all(gates.values())}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Reddit Intelligence v2 against labeled JSONL")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = evaluate(args.corpus)
    output = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
