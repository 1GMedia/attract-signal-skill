#!/usr/bin/env python3
"""Evaluate Reddit Intelligence v2 against a labeled JSONL corpus.

Each line must contain ``topic``, ``thread`` (a normalized Reddit record),
``relevant`` (boolean), ``lenses`` (list), and ``purchase_intent``.  This tool
does not manufacture a gold corpus; it makes manual labels reproducible and
turns the acceptance gates into a machine-readable CI report.
"""
from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from reddit_intelligence import (
    SignalStore, canonical_reddit_url, run_research,
)


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for item in csv.DictReader(handle):
                if not item.get("gold_relevance"):
                    continue
                raw_lenses = item.get("gold_lenses", "")
                try:
                    lenses = json.loads(raw_lenses) if raw_lenses.strip().startswith("[") else [value.strip() for value in raw_lenses.split(",") if value.strip()]
                except json.JSONDecodeError:
                    lenses = []
                rows.append({
                    "topic": item.get("topic", ""),
                    "thread": {
                        "title": item.get("title", ""), "body": item.get("body", ""),
                        "canonical_url": item.get("canonical_url", ""), "subreddit": item.get("subreddit", ""),
                        "published_at": item.get("published_at"), "upvotes": int(item.get("upvotes") or 0),
                        "comment_count": int(item.get("comment_count") or 0),
                    },
                    "relevant": item["gold_relevance"].strip().lower() in {"1", "true", "relevant", "yes"},
                    "lenses": lenses, "purchase_intent": item.get("gold_intent") or "none",
                })
        return rows
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pipeline_predictions(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Evaluate the selected v2 pipeline, including configured model routing."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["topic"])].append(row)
    predictions: dict[tuple[str, str], dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = SignalStore(root / "evaluation.sqlite3")
        try:
            for index, (topic, topic_rows) in enumerate(grouped.items()):
                items = []
                for item_index, row in enumerate(topic_rows):
                    thread = row["thread"]
                    url = thread.get("canonical_url") or thread.get("url")
                    items.append({
                        "item_id": thread.get("id") or f"eval-{index}-{item_index}", "source": "reddit",
                        "title": thread.get("title", ""), "body": thread.get("body", ""), "url": url,
                        "container": thread.get("subreddit", "unknown"), "published_at": thread.get("published_at"),
                        "engagement": {"score": thread.get("upvotes", 0), "num_comments": thread.get("comment_count", 0)},
                        "top_comments": thread.get("comments", []),
                    })
                artifact = root / f"topic-{index}.json"
                artifact.write_text(json.dumps({"items_by_source": {"reddit": items}}), encoding="utf-8")
                aliases = sorted({alias for row in topic_rows for alias in row.get("aliases", [])})
                dedicated = sorted({name for row in topic_rows for name in row.get("dedicated_subreddits", [])})
                negatives = sorted({anchor for row in topic_rows for anchor in row.get("negative_anchors", [])})
                run = run_research(
                    topic=topic, inputs=[artifact], audience_id=None, brand_path=None, days=30,
                    quality="balanced", output_dir=root / f"report-{index}", store=store,
                    aliases=aliases, dedicated_subreddits=dedicated, negative_anchors=negatives,
                )
                for evidence in run["threads"]:
                    predictions[(topic, evidence["canonical_url"])] = {
                        "relevant": True, "lenses": evidence["lenses"],
                        "purchase_intent": evidence["purchase_intent"],
                    }
                for evidence in run["excluded_threads"]:
                    predictions[(topic, evidence["canonical_url"])] = {
                        "relevant": False, "lenses": [], "purchase_intent": "none",
                    }
        finally:
            store.close()
    return predictions


def evaluate(path: Path) -> dict[str, Any]:
    rows = load_rows(path)
    predictions = pipeline_predictions(rows)
    tp = fp = tn = fn = 0
    lens_tp = lens_fp = lens_fn = 0
    purchase_fp = purchase_negatives = 0
    high_engagement_negatives = high_engagement_promoted = 0
    lens_counts: dict[str, dict[str, int]] = {
        lens: {"tp": 0, "fp": 0, "fn": 0}
        for lens in ("pain_points", "solution_requests", "money_talk", "hot_discussions", "seeking_alternatives")
    }
    for row in rows:
        thread = row["thread"]
        url = canonical_reddit_url(thread.get("canonical_url") or thread.get("url") or "")
        prediction = predictions.get((str(row["topic"]), url), {"relevant": False, "lenses": [], "purchase_intent": "none"})
        predicted_relevant = bool(prediction["relevant"])
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
            predicted = set(prediction["lenses"])
            expected = set(row.get("lenses", []))
            lens_tp += len(predicted & expected)
            lens_fp += len(predicted - expected)
            lens_fn += len(expected - predicted)
            for lens, counts in lens_counts.items():
                counts["tp"] += int(lens in predicted and lens in expected)
                counts["fp"] += int(lens in predicted and lens not in expected)
                counts["fn"] += int(lens not in predicted and lens in expected)
            predicted_purchase = str(prediction["purchase_intent"])
            expected_purchase = row.get("purchase_intent", "none")
            if expected_purchase in {"none", "curiosity"}:
                purchase_negatives += 1
                purchase_fp += int(predicted_purchase in {"evaluating", "willing_to_pay", "active_switching"})
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    lens_precision = safe_div(lens_tp, lens_tp + lens_fp)
    lens_recall = safe_div(lens_tp, lens_tp + lens_fn)
    lens_f1 = safe_div(2 * lens_precision * lens_recall, lens_precision + lens_recall)
    per_lens_f1 = {}
    for lens, counts in lens_counts.items():
        item_precision = safe_div(counts["tp"], counts["tp"] + counts["fp"])
        item_recall = safe_div(counts["tp"], counts["tp"] + counts["fn"])
        per_lens_f1[lens] = safe_div(2 * item_precision * item_recall, item_precision + item_recall)
    lens_macro_f1 = safe_div(sum(per_lens_f1.values()), len(per_lens_f1))
    metrics = {
        "examples": len(rows), "relevance_precision": round(precision, 4),
        "relevance_recall": round(recall, 4), "lens_micro_f1": round(lens_f1, 4),
        "lens_macro_f1": round(lens_macro_f1, 4),
        "per_lens_f1": {key: round(value, 4) for key, value in per_lens_f1.items()},
        "false_purchase_intent_rate": round(safe_div(purchase_fp, purchase_negatives), 4),
        "high_engagement_off_topic_promotion_rate": round(safe_div(high_engagement_promoted, high_engagement_negatives), 4),
    }
    gates = {
        "corpus_has_300_examples": len(rows) >= 300,
        "relevance_precision": precision >= 0.92,
        "relevance_recall": recall >= 0.85,
        "lens_macro_f1": lens_macro_f1 >= 0.85,
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
