#!/usr/bin/env python3
"""Scan a YouTube channel Shorts tab for high-performing Shorts.

Requires yt-dlp on PATH. Outputs JSON and optional Markdown.
This script intentionally collects metadata only; transcript analysis is done by
the bundled transcript helper or a host-agent transcript tool so unavailable
transcripts are not invented.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from statistics import median
from pathlib import Path
from typing import Any, Dict, List, Optional


def run(cmd: List[str]) -> str:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout


def normalize_shorts_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("channel URL is empty")
    if "/shorts" not in url and "/watch" not in url and "youtu.be/" not in url:
        url = url.rstrip("/") + "/shorts"
    return url


def video_url_from_entry(entry: Dict[str, Any]) -> Optional[str]:
    if entry.get("webpage_url"):
        return entry["webpage_url"]
    if entry.get("url") and str(entry["url"]).startswith("http"):
        return entry["url"]
    vid = entry.get("id")
    if vid:
        return f"https://www.youtube.com/shorts/{vid}"
    return None


def parse_json_lines(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def add_cookie_args(cmd: List[str], cookies: Optional[Path], cookies_from_browser: Optional[str]) -> List[str]:
    if cookies:
        cmd.extend(["--cookies", str(cookies)])
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    return cmd


def fetch_flat_entries(
    channel_shorts_url: str,
    max_videos: int,
    cookies: Optional[Path],
    cookies_from_browser: Optional[str],
) -> List[Dict[str, Any]]:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--playlist-end",
        str(max_videos),
        channel_shorts_url,
    ]
    add_cookie_args(cmd, cookies, cookies_from_browser)
    return parse_json_lines(run(cmd))


def fetch_video_metadata(url: str, cookies: Optional[Path], cookies_from_browser: Optional[str]) -> Dict[str, Any]:
    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--skip-download",
        "--ignore-no-formats-error",
        "--no-warnings",
        url,
    ]
    add_cookie_args(cmd, cookies, cookies_from_browser)
    return json.loads(run(cmd))


def compact_video(meta: Dict[str, Any], source_url: str) -> Dict[str, Any]:
    video_id = meta.get("id")
    shorts_url = f"https://www.youtube.com/shorts/{video_id}" if video_id else source_url
    watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else source_url
    like_count = meta.get("like_count")
    view_count = meta.get("view_count")
    ratio = None
    if isinstance(like_count, int) and isinstance(view_count, int) and view_count > 0:
        ratio = like_count / view_count
    return {
        "id": video_id,
        "title": meta.get("title"),
        "source_url": shorts_url,
        "watch_url": watch_url,
        "original_url": source_url,
        "channel": meta.get("channel") or meta.get("uploader"),
        "channel_url": meta.get("channel_url") or meta.get("uploader_url"),
        "upload_date": meta.get("upload_date"),
        "duration": meta.get("duration"),
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": meta.get("comment_count"),
        "like_view_ratio": ratio,
        "description": meta.get("description"),
        "tags": meta.get("tags") or [],
        "categories": meta.get("categories") or [],
        "thumbnail": meta.get("thumbnail"),
    }


def safe_ratio(numerator: Any, denominator: Any) -> Optional[float]:
    if isinstance(numerator, int) and isinstance(denominator, int) and denominator > 0:
        return numerator / denominator
    return None


def numeric_values(videos: List[Dict[str, Any]], key: str) -> List[int]:
    return [v[key] for v in videos if isinstance(v.get(key), int)]


def channel_baseline(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    views = numeric_values(videos, "view_count")
    likes = numeric_values(videos, "like_count")
    comments = numeric_values(videos, "comment_count")
    return {
        "video_count": len(videos),
        "median_views": int(median(views)) if views else None,
        "median_likes": int(median(likes)) if likes else None,
        "median_comments": int(median(comments)) if comments else None,
        "max_views": max(views) if views else None,
        "max_likes": max(likes) if likes else None,
        "max_comments": max(comments) if comments else None,
        "likes_available_count": len(likes),
        "comments_available_count": len(comments),
    }


def recency_modifier(upload_date: Any, now: datetime) -> float:
    if not upload_date:
        return 0.9
    try:
        uploaded = datetime.strptime(str(upload_date), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.9
    days_old = max((now - uploaded).days, 0)
    if days_old <= 30:
        return 1.1
    if days_old <= 90:
        return 1.0
    if days_old <= 365:
        return 0.9
    return 0.75


def metric_relative(value: Any, baseline: Any) -> Optional[float]:
    if isinstance(value, int) and isinstance(baseline, int) and baseline > 0:
        return value / baseline
    return None


def score_video(video: Dict[str, Any], baseline: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    views = video.get("view_count")
    likes = video.get("like_count")
    comments = video.get("comment_count")
    like_view = safe_ratio(likes, views)
    comment_view = safe_ratio(comments, views)
    relative_views = metric_relative(views, baseline.get("median_views"))
    relative_likes = metric_relative(likes, baseline.get("median_likes"))
    relative_comments = metric_relative(comments, baseline.get("median_comments"))

    absolute_score = 0.0
    if isinstance(views, int):
        absolute_score += min(18.0, math.log10(max(views, 1)) * 3.0)
    if isinstance(likes, int):
        absolute_score += min(12.0, math.log10(max(likes, 1)) * 2.5)
    if isinstance(comments, int):
        absolute_score += min(8.0, math.log10(max(comments, 1) + 1) * 2.5)

    engagement_score = 0.0
    if like_view is not None:
        engagement_score += min(18.0, like_view * 650)
    if comment_view is not None:
        engagement_score += min(10.0, comment_view * 2500)

    outlier_score = 0.0
    if relative_views is not None:
        outlier_score += min(14.0, relative_views * 4.0)
    if relative_likes is not None:
        outlier_score += min(10.0, relative_likes * 3.0)
    if relative_comments is not None:
        outlier_score += min(6.0, relative_comments * 2.0)

    completeness_score = 0.0
    for key in ("title", "source_url", "view_count", "like_count", "comment_count", "description", "thumbnail"):
        if video.get(key) not in (None, "", []):
            completeness_score += 1.0

    raw = absolute_score + engagement_score + outlier_score + completeness_score
    score = max(0, min(100, round(raw * recency_modifier(video.get("upload_date"), now))))
    reasons = []
    if relative_views is not None and relative_views >= 2:
        reasons.append(f"{relative_views:.1f}x channel median views")
    if relative_likes is not None and relative_likes >= 2:
        reasons.append(f"{relative_likes:.1f}x channel median likes")
    if like_view is not None:
        reasons.append(f"{like_view * 100:.2f}% like/view ratio")
    if comment_view is not None and comment_view > 0:
        reasons.append(f"{comment_view * 100:.3f}% comment/view ratio")
    if not reasons:
        reasons.append("baseline metadata captured; signal depends on available metrics")

    return {
        "like_view_ratio": like_view,
        "comment_view_ratio": comment_view,
        "relative_views": relative_views,
        "relative_likes": relative_likes,
        "relative_comments": relative_comments,
        "signal_score": score,
        "signal_reason": "; ".join(reasons),
    }


def enrich_videos(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    baseline = channel_baseline(videos)
    now = datetime.now(timezone.utc)
    for video in videos:
        video.update(score_video(video, baseline, now))
    return baseline


def fmt_num(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def write_markdown(path: Path, payload: Dict[str, Any]) -> None:
    lines = []
    lines.append(f"# YouTube Shorts Scan: {payload['channel_url']}\n")
    lines.append(f"- Scanned at: {payload['scanned_at']}")
    lines.append(f"- Min likes: {payload['min_likes']:,}")
    lines.append(f"- Videos scanned: {payload['videos_scanned']}")
    lines.append(f"- Winners: {len(payload['winners'])}\n")
    lines.append("## Winners\n")
    if not payload["winners"]:
        lines.append("No videos met the like threshold, or like counts were unavailable.\n")
    else:
        lines.append("| Rank | Title | Views | Likes | Comments | Like/View | Source |")
        lines.append("|---:|---|---:|---:|---:|---:|---|")
        for i, v in enumerate(payload["winners"], 1):
            title = (v.get("title") or "Untitled").replace("|", "\\|")
            lines.append(
                f"| {i} | {title} | {fmt_num(v.get('view_count'))} | {fmt_num(v.get('like_count'))} | "
                f"{fmt_num(v.get('comment_count'))} | {fmt_num(v.get('like_view_ratio'))} | [link]({v.get('source_url')}) |"
            )
    lines.append("\n## All scanned videos\n")
    for v in payload["videos"]:
        lines.append(f"- [{v.get('title') or v.get('id')}]({v.get('source_url')}) — views={fmt_num(v.get('view_count'))}, likes={fmt_num(v.get('like_count'))}, comments={fmt_num(v.get('comment_count'))}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan YouTube channel Shorts metadata and filter by likes.")
    parser.add_argument("channel_url", help="Channel URL or Shorts tab URL, e.g. https://www.youtube.com/@handle/shorts")
    parser.add_argument("--min-likes", type=int, default=10_000)
    parser.add_argument("--max-videos", type=int, default=50)
    parser.add_argument("--out", type=Path, default=None, help="Write JSON payload to this path")
    parser.add_argument("--markdown", type=Path, default=None, help="Write Markdown table to this path")
    parser.add_argument("--include-unknown-likes", action="store_true", help="Include unknown-like videos in winners for manual review")
    parser.add_argument("--cookies", type=Path, default=None, help="Netscape cookies file for yt-dlp, useful when YouTube requires sign-in")
    parser.add_argument("--cookies-from-browser", default=None, help="Browser cookies source for yt-dlp, e.g. chrome, safari, firefox, or chrome:Profile 1")
    args = parser.parse_args()

    if shutil.which("yt-dlp") is None:
        print("ERROR: yt-dlp is required. Install with: python3 -m pip install -U yt-dlp", file=sys.stderr)
        return 2

    channel_url = normalize_shorts_url(args.channel_url)
    flat_entries = fetch_flat_entries(channel_url, args.max_videos, args.cookies, args.cookies_from_browser)
    videos: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for entry in flat_entries[: args.max_videos]:
        url = video_url_from_entry(entry)
        if not url:
            continue
        try:
            meta = fetch_video_metadata(url, args.cookies, args.cookies_from_browser)
            videos.append(compact_video(meta, url))
        except Exception as exc:  # keep scanning even if one video fails
            errors.append({"url": url, "error": str(exc)})

    baseline = enrich_videos(videos)
    winners = []
    for v in videos:
        likes = v.get("like_count")
        if isinstance(likes, int) and likes >= args.min_likes:
            winners.append(v)
        elif likes is None and args.include_unknown_likes:
            winners.append(v)
    winners.sort(key=lambda x: ((x.get("signal_score") or -1), (x.get("like_count") or -1), (x.get("view_count") or -1)), reverse=True)

    payload = {
        "channel_url": channel_url,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "min_likes": args.min_likes,
        "max_videos": args.max_videos,
        "videos_scanned": len(videos),
        "partial_scan": len(errors) > 0 or len(videos) < len(flat_entries[: args.max_videos]),
        "channel_baseline": baseline,
        "winners": winners,
        "videos": videos,
        "errors": errors,
        "notes": [
            "like_count may be null if YouTube hides likes or yt-dlp cannot extract them",
            "if YouTube asks to confirm you are not a bot, rerun with --cookies-from-browser or --cookies",
            "use source_url as the required citation for each analysis row",
        ],
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.markdown:
        write_markdown(args.markdown, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
