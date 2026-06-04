#!/usr/bin/env python3
"""Generate an industry-agnostic Attract Signal strategy report from signals JSON."""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_BRAND = {
    "brand_name": "Your Brand",
    "industry": "your industry",
    "audience": "your target audience",
    "offer": "your offer, product, or service",
    "tone": "clear, useful, and brand-safe",
    "proof_points": [],
    "constraints": [],
    "filming_resources": [],
    "forbidden_claims": [],
}

TREND_KEYWORDS = [
    ("transformation / before-after", ("before", "after", "clean", "reset", "makeover", "restore", "fixed")),
    ("challenge / countdown", ("challenge", "try", "can i", "we only", "day", "count", "again")),
    ("problem-solution", ("how to", "fix", "mistake", "problem", "stop", "avoid")),
    ("routine / ritual", ("routine", "morning", "night", "daily", "week", "reset")),
    ("product demo / tool reveal", ("tool", "product", "using", "review", "test", "demo")),
    ("social proof / results", ("result", "client", "customer", "reaction", "proof")),
    ("storytime / confession", ("story", "i was", "they said", "confession", "pov")),
]


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",")]
    return value.strip("\"'")


def load_brand(path: Optional[Path]) -> Dict[str, Any]:
    brand = dict(DEFAULT_BRAND)
    if not path:
        brand["assumption_note"] = "No brand.yaml supplied; recommendations use industry-agnostic placeholders."
        return brand
    current_key: Optional[str] = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            brand.setdefault(current_key, [])
            if not isinstance(brand[current_key], list):
                brand[current_key] = [brand[current_key]]
            brand[current_key].append(parse_scalar(stripped[2:]))
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            current_key = key
            parsed = parse_scalar(value)
            brand[key] = [] if parsed == "" else parsed
    brand.setdefault("assumption_note", f"Brand context loaded from {path}.")
    return brand


def fmt_num(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "unknown"
    return f"{value * 100:.2f}%"


def md_escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def words(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9'-]+", text.lower())


def infer_trend(video: Dict[str, Any]) -> str:
    text = " ".join(str(video.get(key) or "") for key in ("title", "description", "tags")).lower()
    for label, keys in TREND_KEYWORDS:
        if any(key in text for key in keys):
            return label
    return "curiosity / visual premise"


def infer_hook(video: Dict[str, Any]) -> str:
    title = str(video.get("title") or "Untitled source")
    lower = title.lower()
    if "?" in title or lower.startswith(("how", "why", "what", "can")):
        return "question or curiosity hook"
    if any(token in lower for token in ("before", "after", "clean", "reset", "makeover")):
        return "transformation hook"
    if any(token in lower for token in ("free", "called", "secret", "mistake", "wrong", "no")):
        return "tension or contradiction hook"
    if re.search(r"\d", title):
        return "specificity or countdown hook"
    return "plain-language premise hook"


def top_keywords(videos: Iterable[Dict[str, Any]], limit: int = 10) -> List[str]:
    stop = {
        "the", "and", "for", "you", "with", "this", "that", "from", "are", "was", "were",
        "shorts", "youtube", "video", "part", "more", "your", "our", "their", "have",
    }
    counts: Dict[str, int] = {}
    for video in videos:
        for word in words(" ".join(str(video.get(key) or "") for key in ("title", "description"))):
            if len(word) < 4 or word in stop:
                continue
            counts[word] = counts.get(word, 0) + 1
    return [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def strategy_angle(video: Dict[str, Any], brand: Dict[str, Any]) -> str:
    trend = infer_trend(video)
    industry = brand.get("industry") or "your industry"
    offer = brand.get("offer") or "your offer"
    if "transformation" in trend:
        return f"Show a visible before/after transformation around {offer} in {industry}."
    if "challenge" in trend:
        return f"Create a simple progress challenge where {brand.get('audience')} can understand the goal in one second."
    if "problem-solution" in trend:
        return f"Name a common pain point, solve it quickly, and tie the proof back to {offer}."
    if "product demo" in trend:
        return f"Demonstrate {offer} with one clear visual proof point and no overexplaining."
    return f"Translate the source's hook mechanics into a brand-safe premise for {industry}."


def concept_title(video: Dict[str, Any], brand: Dict[str, Any], index: int) -> str:
    industry = brand.get("industry") or "your industry"
    trend = infer_trend(video).split("/")[0].strip()
    return f"Concept {index}: {trend.title()} Signal for {industry.title()}"


def build_calendar_rows(top: List[Dict[str, Any]], brand: Dict[str, Any], days: int = 30) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not top:
        return rows
    pillars = [
        "Proof / transformation",
        "Problem-solution",
        "Behind the scenes",
        "Audience question",
        "Challenge / countdown",
        "Myth or mistake",
    ]
    for day in range(1, days + 1):
        source = top[(day - 1) % len(top)]
        pillar = pillars[(day - 1) % len(pillars)]
        rows.append({
            "day": str(day),
            "pillar": pillar,
            "working_title": f"{pillar}: {brand.get('offer', 'your offer')}",
            "hook": f"Open with a {infer_hook(source)} inspired by source day {((day - 1) % len(top)) + 1}.",
            "format": infer_trend(source),
            "source_url": source.get("source_url") or "",
            "cta": "Ask viewers to comment a question or follow for the next example.",
        })
    return rows


def write_calendar(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["day", "pillar", "working_title", "hook", "format", "source_url", "cta"])
        writer.writeheader()
        writer.writerows(rows)


def load_transcripts(transcripts_dir: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if not transcripts_dir:
        return {}
    transcripts: Dict[str, Dict[str, Any]] = {}
    if not transcripts_dir.exists():
        return transcripts
    for path in transcripts_dir.glob("*.json"):
        try:
            payload = load_json(path)
        except Exception:
            continue
        video_id = payload.get("video_id") or path.stem
        transcripts[str(video_id)] = payload
    return transcripts


def transcript_beats(transcript: Dict[str, Any]) -> List[str]:
    timestamped = transcript.get("timestamped_text")
    full_text = transcript.get("full_text")
    if not timestamped and not full_text:
        return ["Transcript unavailable or empty."]
    lines = [line.strip() for line in str(timestamped or "").splitlines() if line.strip()]
    if lines:
        first = lines[0]
        early = lines[min(2, len(lines) - 1)]
        middle = lines[len(lines) // 2]
        end = lines[-1]
        return [
            f"Opening beat: {first}",
            f"Early escalation: {early}",
            f"Midpoint/payoff setup: {middle}",
            f"Ending/CTA beat: {end}",
        ]
    text = str(full_text)
    return [
        f"Opening language: {text[:160].strip()}",
        "Timestamped structure unavailable; use visual review for beat timing.",
    ]


def generate_report(signals: Dict[str, Any], brand: Dict[str, Any], top_n: int, transcripts: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    top = (signals.get("top_signals") or signals.get("videos") or [])[:top_n]
    transcripts = transcripts or {}
    keywords = top_keywords(top)
    lines: List[str] = []
    lines.append(f"# Attract Signal Strategy Report: {brand.get('brand_name', 'Your Brand')}")
    lines.append("")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Industry: {brand.get('industry', 'your industry')}")
    lines.append(f"- Audience: {brand.get('audience', 'your target audience')}")
    lines.append(f"- Offer: {brand.get('offer', 'your offer, product, or service')}")
    lines.append(f"- Brand context: {brand.get('assumption_note')}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- Analyzed {signals.get('video_count', len(top))} videos across {signals.get('scan_count', 1)} scan(s).")
    lines.append("- The strongest signals are ranked by source performance, channel-relative outlier strength, engagement, and metadata completeness.")
    lines.append("- Recommendations are industry-agnostic by default and should be adapted to the user's actual proof points before production.")
    if keywords:
        lines.append(f"- Repeated language signals: {', '.join(keywords)}.")
    lines.append("")
    lines.append("## Top Signals")
    lines.append("")
    lines.append("| Rank | Source | Score | Views | Likes | Comments | Signal reason | Strategy angle |")
    lines.append("|---:|---|---:|---:|---:|---:|---|---|")
    for index, video in enumerate(top, 1):
        score = video.get("cross_channel_signal_score") or video.get("signal_score")
        lines.append(
            f"| {index} | [{md_escape(video.get('title') or video.get('id'))}]({video.get('source_url')}) | "
            f"{fmt_num(score)} | {fmt_num(video.get('view_count'))} | {fmt_num(video.get('like_count'))} | "
            f"{fmt_num(video.get('comment_count'))} | {md_escape(video.get('cross_channel_signal_reason') or video.get('signal_reason'))} | "
            f"{md_escape(strategy_angle(video, brand))} |"
        )
    lines.append("")
    lines.append("## Source Evidence")
    lines.append("")
    for index, video in enumerate(top, 1):
        lines.append(f"### {index}. {video.get('title') or video.get('id')}")
        lines.append("")
        lines.append(f"- Source: {video.get('source_url')}")
        lines.append(f"- Channel: {video.get('channel') or video.get('scan_channel_url') or 'unknown'}")
        lines.append(f"- Views: {fmt_num(video.get('view_count'))}")
        lines.append(f"- Likes: {fmt_num(video.get('like_count'))}")
        lines.append(f"- Comments: {fmt_num(video.get('comment_count'))}")
        lines.append(f"- Like/view: {pct(video.get('like_view_ratio'))}")
        lines.append(f"- Comment/view: {pct(video.get('comment_view_ratio'))}")
        lines.append(f"- Relative views: {fmt_num(video.get('relative_views'))}x channel median")
        lines.append("")
    lines.append("## Hook Taxonomy")
    lines.append("")
    for label in sorted({infer_hook(video) for video in top}):
        examples = [video for video in top if infer_hook(video) == label][:3]
        source_links = ", ".join(f"[source]({video.get('source_url')})" for video in examples)
        lines.append(f"- {label}: {source_links}")
    lines.append("")
    lines.append("## Visual Pattern Taxonomy")
    lines.append("")
    lines.append("- Immediate action: start after the action has already begun; avoid throat-clearing intros.")
    lines.append("- Visible progress: use counters, before/after frames, checklists, or completion states.")
    lines.append("- Human reaction: show surprise, relief, tension, or satisfaction when possible.")
    lines.append("- Repeatable proof: make the viewer understand the result without needing context.")
    lines.append("")
    lines.append("## Transcript Insights")
    lines.append("")
    if transcripts:
        for index, video in enumerate(top, 1):
            transcript = transcripts.get(str(video.get("id")))
            if not transcript:
                lines.append(f"- {index}. {video.get('title') or video.get('id')}: transcript not provided; use visual review and mark transcript unavailable.")
                continue
            lines.append(f"- {index}. {video.get('title') or video.get('id')}:")
            for beat in transcript_beats(transcript):
                lines.append(f"  - {beat}")
    else:
        lines.append("- Use the bundled transcript helper for shortlisted videos, then pass the JSON files with `--transcripts-dir`.")
        lines.append("- For videos without captions, mark transcript status as unavailable and analyze visible structure only.")
        lines.append("- Strong Shorts usually make the premise legible in the first 0-2 seconds, escalate by 5-12 seconds, and end with a payoff or loop.")
    lines.append("")
    lines.append("## Brand Strategy Opportunities")
    lines.append("")
    for index, video in enumerate(top[:5], 1):
        lines.append(f"### {concept_title(video, brand, index)}")
        lines.append("")
        lines.append(f"- Source inspiration: {video.get('source_url')}")
        lines.append(f"- Signal to adapt: {strategy_angle(video, brand)}")
        lines.append(f"- 0-2s hook: Open with a {infer_hook(video)} tied to {brand.get('audience')}.")
        lines.append(f"- Script beat: name the tension, show the proof, compress the payoff, then invite a comment or follow.")
        lines.append(f"- Avoid copying: do not reuse the source creator's exact premise, wording, setting, or edit sequence.")
        lines.append("")
    lines.append("## Script Drafts")
    lines.append("")
    for index, video in enumerate(top[:3], 1):
        lines.append(f"### Script {index}: {concept_title(video, brand, index)}")
        lines.append("")
        lines.append(f"- 0-2s: \"Wait, this is the part of {brand.get('industry')} nobody shows you.\"")
        lines.append(f"- 2-6s: Show the problem or desired outcome for {brand.get('audience')}.")
        lines.append(f"- 6-15s: Demonstrate {brand.get('offer')} with one visual proof point.")
        lines.append("- 15-25s: Reveal the result, contrast, or lesson.")
        lines.append("- CTA: \"Comment what you want us to test next.\"")
        lines.append(f"- Source reference: {video.get('source_url')}")
        lines.append("")
    lines.append("## Shot Lists")
    lines.append("")
    lines.append("| Shot | Duration | Framing | Action | Overlay | Notes |")
    lines.append("|---:|---:|---|---|---|---|")
    lines.append("| 1 | 0-2s | tight vertical close-up | start mid-action | short tension phrase | no intro |")
    lines.append("| 2 | 2-6s | hand/product/process shot | show the problem | name the stakes | make it legible |")
    lines.append("| 3 | 6-15s | sequence cuts | show proof or process | progress cue | keep motion high |")
    lines.append("| 4 | 15-22s | reveal frame | show result | outcome phrase | source-inspired, not copied |")
    lines.append("| 5 | 22-30s | face/result frame | CTA | comment prompt | loop to next video |")
    lines.append("")
    lines.append("## Storyboard Prompts")
    lines.append("")
    lines.append(f"- Frame 1: vertical phone-video frame, immediate action in {brand.get('industry')}, clear tension, natural light, authentic brand setting.")
    lines.append(f"- Frame 2: close-up proof shot of {brand.get('offer')}, visible progress indicator, clean readable overlay.")
    lines.append(f"- Frame 3: human reaction or result reveal for {brand.get('audience')}, brand-safe and realistic.")
    lines.append("- Frame 4: final payoff frame with simple CTA, designed for Shorts/Reels/TikTok pacing.")
    lines.append("")
    lines.append("## 30-Day Content Calendar")
    lines.append("")
    lines.append("| Day | Pillar | Working title | Hook | Source |")
    lines.append("|---:|---|---|---|---|")
    for row in build_calendar_rows(top, brand, 30):
        lines.append(f"| {row['day']} | {md_escape(row['pillar'])} | {md_escape(row['working_title'])} | {md_escape(row['hook'])} | [source]({row['source_url']}) |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an industry-agnostic Attract Signal Markdown report.")
    parser.add_argument("--signals", type=Path, required=True, help="signals.json produced by analyze_signals.py")
    parser.add_argument("--brand", type=Path, default=None, help="Optional brand.yaml context file")
    parser.add_argument("--out", type=Path, required=True, help="Write Markdown report to this path")
    parser.add_argument("--calendar", type=Path, default=None, help="Optional CSV 30-day calendar output")
    parser.add_argument("--transcripts-dir", type=Path, default=None, help="Optional directory containing transcript JSON files named <video_id>.json")
    parser.add_argument("--top", type=int, default=10, help="Number of top signals to include")
    args = parser.parse_args()

    signals = load_json(args.signals)
    brand = load_brand(args.brand)
    transcripts = load_transcripts(args.transcripts_dir)
    report = generate_report(signals, brand, args.top, transcripts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    if args.calendar:
        top = (signals.get("top_signals") or signals.get("videos") or [])[: args.top]
        write_calendar(args.calendar, build_calendar_rows(top, brand, 30))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
