#!/usr/bin/env python3
"""Normalize exported short-form metrics from YouTube, TikTok, Instagram, or X.

This is not a scraper. It turns user-provided CSV/JSON exports into the same
scan-like JSON shape used by Attract Signal so multi-platform analysis can rank
signals consistently when platform APIs/scrapers are unavailable.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional


FIELD_ALIASES = {
    "title": ("title", "caption", "text", "description", "post_text"),
    "source_url": ("source_url", "url", "link", "permalink", "post_url", "video_url"),
    "channel": ("channel", "creator", "account", "username", "handle", "profile"),
    "upload_date": ("upload_date", "published_at", "created_at", "date", "posted_at"),
    "view_count": ("view_count", "views", "plays", "play_count", "impressions"),
    "like_count": ("like_count", "likes", "like_count", "favorites"),
    "comment_count": ("comment_count", "comments", "reply_count", "replies"),
    "share_count": ("share_count", "shares", "reposts", "retweets"),
    "save_count": ("save_count", "saves", "bookmarks"),
    "thumbnail": ("thumbnail", "thumbnail_url", "image", "cover_url"),
}


def parse_number(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().lower().replace(",", "")
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def read_rows(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            for key in ("videos", "posts", "items", "data", "rows"):
                if isinstance(payload.get(key), list):
                    return [row for row in payload[key] if isinstance(row, dict)]
            return [payload]
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def first_value(row: Dict[str, Any], aliases: Iterable[str]) -> Any:
    lower_map = {str(key).lower(): value for key, value in row.items()}
    for alias in aliases:
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    return None


def safe_ratio(numerator: Any, denominator: Any) -> Optional[float]:
    if isinstance(numerator, int) and isinstance(denominator, int) and denominator > 0:
        return numerator / denominator
    return None


def values(rows: List[Dict[str, Any]], key: str) -> List[int]:
    return [row[key] for row in rows if isinstance(row.get(key), int)]


def normalize_row(row: Dict[str, Any], platform: str, index: int) -> Dict[str, Any]:
    row_platform = first_value(row, ("platform", "network", "source"))
    resolved_platform = str(row_platform or platform).strip().lower() if platform == "mixed" else platform
    video: Dict[str, Any] = {
        "id": str(first_value(row, ("id", "video_id", "post_id")) or f"{resolved_platform}-{index:04d}"),
        "platform": resolved_platform,
        "title": first_value(row, FIELD_ALIASES["title"]) or f"{resolved_platform.title()} post {index}",
        "source_url": first_value(row, FIELD_ALIASES["source_url"]),
        "watch_url": first_value(row, FIELD_ALIASES["source_url"]),
        "channel": first_value(row, FIELD_ALIASES["channel"]),
        "channel_url": first_value(row, ("channel_url", "profile_url", "account_url")),
        "upload_date": first_value(row, FIELD_ALIASES["upload_date"]),
        "view_count": parse_number(first_value(row, FIELD_ALIASES["view_count"])),
        "like_count": parse_number(first_value(row, FIELD_ALIASES["like_count"])),
        "comment_count": parse_number(first_value(row, FIELD_ALIASES["comment_count"])),
        "share_count": parse_number(first_value(row, FIELD_ALIASES["share_count"])),
        "save_count": parse_number(first_value(row, FIELD_ALIASES["save_count"])),
        "description": first_value(row, FIELD_ALIASES["title"]),
        "thumbnail": first_value(row, FIELD_ALIASES["thumbnail"]),
        "raw": row,
    }
    if not video["source_url"]:
        video["source_url"] = f"unavailable:{resolved_platform}:{video['id']}"
    return video


def baseline(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "video_count": len(videos),
        "median_views": int(median(values(videos, "view_count"))) if values(videos, "view_count") else None,
        "median_likes": int(median(values(videos, "like_count"))) if values(videos, "like_count") else None,
        "median_comments": int(median(values(videos, "comment_count"))) if values(videos, "comment_count") else None,
        "median_shares": int(median(values(videos, "share_count"))) if values(videos, "share_count") else None,
        "median_saves": int(median(values(videos, "save_count"))) if values(videos, "save_count") else None,
    }


def enrich(videos: List[Dict[str, Any]], base: Dict[str, Any]) -> None:
    for video in videos:
        views = video.get("view_count")
        likes = video.get("like_count")
        comments = video.get("comment_count")
        shares = video.get("share_count")
        saves = video.get("save_count")
        like_view = safe_ratio(likes, views)
        comment_view = safe_ratio(comments, views)
        share_view = safe_ratio(shares, views)
        save_view = safe_ratio(saves, views)
        relative_views = safe_ratio(views, base.get("median_views"))
        score = 0.0
        if isinstance(views, int):
            score += min(24, math.log10(max(views, 1)) * 4)
        for metric, cap, scale in ((likes, 18, 3.0), (comments, 12, 4.0), (shares, 12, 4.0), (saves, 12, 4.0)):
            if isinstance(metric, int):
                score += min(cap, math.log10(max(metric, 1) + 1) * scale)
        if like_view is not None:
            score += min(12, like_view * 500)
        if relative_views is not None:
            score += min(10, relative_views * 4)
        video.update({
            "like_view_ratio": like_view,
            "comment_view_ratio": comment_view,
            "share_view_ratio": share_view,
            "save_view_ratio": save_view,
            "relative_views": relative_views,
            "signal_score": max(0, min(100, round(score))),
            "signal_reason": "; ".join(
                item
                for item in [
                    f"{like_view * 100:.2f}% like/view ratio" if like_view is not None else None,
                    f"{comment_view * 100:.3f}% comment/view ratio" if comment_view is not None else None,
                    f"{share_view * 100:.3f}% share/view ratio" if share_view is not None else None,
                    f"{save_view * 100:.3f}% save/view ratio" if save_view is not None else None,
                    f"{relative_views:.1f}x platform median views" if relative_views is not None else None,
                ]
                if item
            ) or "normalized platform metrics captured",
        })


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize short-form platform exports into Attract Signal scan JSON.")
    parser.add_argument("--platform", required=True, choices=["youtube", "tiktok", "instagram", "x", "other", "mixed"])
    parser.add_argument("--input", required=True, type=Path, help="CSV or JSON export containing post/video metrics")
    parser.add_argument("--out", required=True, type=Path, help="Write normalized scan JSON")
    parser.add_argument("--source-name", default=None, help="Human label for this account/channel/export")
    parser.add_argument("--min-likes", type=int, default=10_000)
    args = parser.parse_args()

    rows = read_rows(args.input)
    videos = [normalize_row(row, args.platform, index) for index, row in enumerate(rows, 1)]
    base = baseline(videos)
    enrich(videos, base)
    winners = [video for video in videos if isinstance(video.get("like_count"), int) and video["like_count"] >= args.min_likes]
    winners.sort(key=lambda video: (video.get("signal_score") or 0, video.get("view_count") or 0), reverse=True)
    payload = {
        "platform": args.platform,
        "channel_url": args.source_name or f"{args.platform} export: {args.input}",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "min_likes": args.min_likes,
        "max_videos": len(videos),
        "videos_scanned": len(videos),
        "partial_scan": False,
        "channel_baseline": base,
        "winners": winners,
        "videos": videos,
        "errors": [],
        "notes": [
            "normalized from a user-provided export, not scraped directly",
            "source_url may be unavailable if the export did not include links",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
