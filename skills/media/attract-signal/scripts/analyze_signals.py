#!/usr/bin/env python3
"""Combine one or more Attract Signal scan JSON files into a ranked signals payload."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def numeric(values: List[Any]) -> List[int]:
    return [v for v in values if isinstance(v, int)]


def safe_ratio(numerator: Any, denominator: Any) -> Optional[float]:
    if isinstance(numerator, int) and isinstance(denominator, int) and denominator > 0:
        return numerator / denominator
    return None


def percentile_rank(value: Optional[float], values: List[float]) -> Optional[float]:
    if value is None or not values:
        return None
    below_or_equal = sum(1 for item in values if item <= value)
    return below_or_equal / len(values)


def recompute_cross_scan_scores(videos: List[Dict[str, Any]]) -> None:
    scores = [float(v.get("signal_score")) for v in videos if isinstance(v.get("signal_score"), (int, float))]
    view_ratios = [float(v.get("relative_views")) for v in videos if isinstance(v.get("relative_views"), (int, float))]
    engagement = [
        safe_ratio(v.get("like_count"), v.get("view_count")) or 0
        for v in videos
        if isinstance(v.get("view_count"), int)
    ]
    for video in videos:
        base_score = float(video.get("signal_score") or 0)
        score_rank = percentile_rank(base_score, scores) or 0
        view_rank = percentile_rank(video.get("relative_views"), view_ratios) or 0
        like_view = safe_ratio(video.get("like_count"), video.get("view_count")) or 0
        engagement_rank = percentile_rank(like_view, engagement) or 0
        blended = round((base_score * 0.65) + (score_rank * 15) + (view_rank * 12) + (engagement_rank * 8))
        video["cross_channel_signal_score"] = max(0, min(100, blended))
        video["cross_channel_signal_reason"] = "; ".join(
            item
            for item in [
                video.get("signal_reason"),
                f"{round(score_rank * 100)}th percentile by scan score" if scores else None,
                f"{round(view_rank * 100)}th percentile by relative views" if view_ratios else None,
            ]
            if item
        )


def channel_summary(scan: Dict[str, Any]) -> Dict[str, Any]:
    videos = scan.get("videos") or []
    scores = numeric([v.get("signal_score") for v in videos])
    views = numeric([v.get("view_count") for v in videos])
    return {
        "channel_url": scan.get("channel_url"),
        "videos_scanned": scan.get("videos_scanned", len(videos)),
        "partial_scan": bool(scan.get("partial_scan")),
        "winner_count": len(scan.get("winners") or []),
        "median_signal_score": int(median(scores)) if scores else None,
        "max_signal_score": max(scores) if scores else None,
        "median_views": int(median(views)) if views else None,
        "baseline": scan.get("channel_baseline") or {},
        "errors": scan.get("errors") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank content signals across one or more Attract Signal scan JSON files.")
    parser.add_argument("scans", nargs="+", type=Path, help="One or more scan JSON files produced by scan_shorts.py")
    parser.add_argument("--out", type=Path, default=None, help="Write combined signals JSON to this path")
    parser.add_argument("--top", type=int, default=25, help="Number of top signals to include")
    args = parser.parse_args()

    scans = [load_json(path) for path in args.scans]
    videos: List[Dict[str, Any]] = []
    for scan_path, scan in zip(args.scans, scans):
        for video in scan.get("videos") or []:
            row = dict(video)
            row["scan_file"] = str(scan_path)
            row["scan_channel_url"] = scan.get("channel_url")
            videos.append(row)

    recompute_cross_scan_scores(videos)
    videos.sort(
        key=lambda item: (
            item.get("cross_channel_signal_score") or item.get("signal_score") or -1,
            item.get("view_count") or -1,
        ),
        reverse=True,
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scan_count": len(scans),
        "video_count": len(videos),
        "top_count": min(args.top, len(videos)),
        "channels": [channel_summary(scan) for scan in scans],
        "top_signals": videos[: args.top],
        "videos": videos,
        "notes": [
            "cross_channel_signal_score blends per-channel score, cross-scan percentile, relative views, and engagement",
            "all strategy outputs should cite source_url and avoid copying creator-specific expression",
        ],
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

