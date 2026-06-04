#!/usr/bin/env python3
"""Generate an industry-agnostic Attract Signal strategy report from signals JSON."""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_BRAND = {
    "brand_name": "Your Brand",
    "industry": "your industry",
    "audience": "your target audience",
    "offer": "your offer, product, or service",
    "tone": "clear, useful, and brand-safe",
    "promise": "",
    "primary_path": "",
    "channel_style": "",
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


def has_performance_metrics(video: Dict[str, Any]) -> bool:
    return any(isinstance(video.get(key), int) for key in ("view_count", "like_count", "comment_count", "share_count", "save_count"))


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


def video_text(video: Dict[str, Any]) -> str:
    return " ".join(str(video.get(key) or "") for key in ("title", "description", "channel", "categories", "tags")).lower()


def has_phrase(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def has_word(text: str, terms: Iterable[str]) -> bool:
    tokens = set(words(text))
    return any(term in tokens for term in terms)


def transcript_opening(video: Dict[str, Any], transcripts: Dict[str, Dict[str, Any]]) -> Optional[str]:
    transcript = transcripts.get(str(video.get("id")))
    if not transcript:
        return None
    timestamped = transcript.get("timestamped_text")
    if timestamped:
        for line in str(timestamped).splitlines():
            line = line.strip()
            if line:
                return re.sub(r"^\d{1,2}:\d{2}\s+", "", line).strip()
    full_text = transcript.get("full_text")
    if full_text:
        words_ = str(full_text).split()
        return " ".join(words_[:14]).strip()
    return None


def infer_avatar(top: List[Dict[str, Any]], brand: Dict[str, Any]) -> str:
    audience = str(brand.get("audience") or "").strip()
    if audience and audience != DEFAULT_BRAND["audience"]:
        return audience
    blob = " ".join(video_text(video) for video in top)
    if has_phrase(blob, ("ball pit",)) or has_word(blob, ("clean", "cleaned", "dirty", "drain", "sink", "target", "mess")):
        return "viewers who enjoy satisfying reveals, cleanup tension, and surprising everyday messes"
    if has_word(blob, ("startup", "founder", "founders", "saas", "ai", "company", "yc", "apply")):
        return "founders, operators, and startup-curious builders"
    if has_word(blob, ("game", "gaming", "player", "level")):
        return "viewers who enjoy game-like challenges, reactions, and payoff loops"
    if has_word(blob, ("product", "tool", "review", "using")):
        return "buyers and enthusiasts comparing tools, products, or practical outcomes"
    return "viewers who already respond to this channel's repeated topics, stakes, and payoff style"


def infer_promise(top: List[Dict[str, Any]], brand: Dict[str, Any], keywords: List[str]) -> str:
    promise = str(brand.get("promise") or "").strip()
    if promise:
        return promise
    offer = str(brand.get("offer") or "").strip()
    industry = str(brand.get("industry") or "").strip()
    if offer and offer != DEFAULT_BRAND["offer"]:
        if any(term in industry.lower() for term in ("startup", "founder", "business", "education", "community")):
            return f"Make {offer} clear, timely, and actionable."
        return f"Help the avatar get a clearer, faster result from {offer}."
    blob = " ".join(video_text(video) for video in top)
    if has_word(blob, ("dirty", "clean", "cleaned", "drain", "sink", "mess")):
        return "Turn ordinary messes into curiosity-driven cleanup payoffs."
    if has_word(blob, ("startup", "ai", "saas", "company", "apply")):
        return "Make big startup shifts feel legible, urgent, and actionable."
    if keywords:
        return f"Make {', '.join(keywords[:3])} feel worth watching through a clear hook and payoff."
    return "Give the avatar a fast reason to watch, a visible payoff, and a clear next step."


def infer_meat_type(video: Dict[str, Any]) -> str:
    text = video_text(video)
    if has_word(text, ("startup", "founder", "founders", "saas", "ai", "school", "lesson")):
        return "Education"
    if has_phrase(text, ("ball pit",)) or has_word(text, ("clean", "cleaned", "dirty", "drain", "sink", "demo", "test", "using", "tool")):
        return "Demonstration"
    if has_word(text, ("client", "customer", "testimonial", "reaction", "proof")):
        return "Testimonial"
    if has_word(text, ("story", "i", "we", "my", "called", "security", "pov")):
        return "Story"
    if has_word(text, ("how", "why", "what", "mistake", "lesson", "school", "ai", "saas", "startup")):
        return "Education"
    return "Demonstration"


def dominant_meats(top: List[Dict[str, Any]]) -> List[str]:
    counts: Dict[str, int] = {}
    for video in top:
        meat = infer_meat_type(video)
        counts[meat] = counts.get(meat, 0) + 1
    ordered = [meat for meat, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    for fallback in ("Demonstration", "Story", "Education", "Testimonial"):
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered[:2]


def infer_channel_style(top: List[Dict[str, Any]], brand: Dict[str, Any]) -> str:
    explicit = str(brand.get("channel_style") or "").strip()
    if explicit:
        return explicit
    blob = " ".join(video_text(video) for video in top)
    if has_word(blob, ("startup", "founder", "founders", "saas", "yc", "school", "apply")):
        return "face_led"
    if has_word(blob, ("product", "tool", "gadget", "using", "review")):
        return "product_led"
    if has_phrase(blob, ("b-roll",)) or has_word(blob, ("compilation", "satisfying", "tutorial", "gameplay")):
        return "faceless"
    if has_word(blob, ("i", "my", "we", "called", "subscribe", "reaction")):
        return "face_led"
    return "face_led"


def infer_primary_path(top: List[Dict[str, Any]], brand: Dict[str, Any]) -> str:
    explicit = str(brand.get("primary_path") or brand.get("path") or "").strip().lower()
    if explicit:
        return explicit
    blob = " ".join(video_text(video) for video in top)
    if "apply" in blob:
        return "apply"
    if has_word(blob, ("checkout", "buy", "code", "shop")):
        return "buy"
    if has_phrase(blob, ("link in", "watch full")) or has_word(blob, ("description", "download")):
        return "click"
    if has_phrase(blob, ("dm me", "message me")) or has_word(blob, ("comment",)):
        return "opt_in"
    return "sub"


def infer_spine(top: List[Dict[str, Any]], brand: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    meats = dominant_meats(top)
    return {
        "avatar": infer_avatar(top, brand),
        "promise": infer_promise(top, brand, keywords),
        "proof": ", ".join(meats),
        "meats": meats,
        "primary_path": infer_primary_path(top, brand),
        "channel_style": infer_channel_style(top, brand),
    }


def hook_pattern_tag(video: Dict[str, Any]) -> str:
    title = str(video.get("title") or "")
    lower = title.lower()
    if any(token in lower for token in ("million", "$", "world", "biggest", "stuck", "security", "called")):
        return "Spectacle"
    if "?" in title or lower.startswith(("how", "why", "what", "can")):
        return "Curiosity"
    if any(token in lower for token in ("before", "after", "cleaned", "clean", "dirty", "new")):
        return "Transformation"
    if any(token in lower for token in ("try", "challenge", "only", "day", "almost")):
        return "Challenge"
    if any(token in lower for token in ("client", "customer", "react", "proof")):
        return "Social Proof"
    return "Narrative"


def hook_template(video: Dict[str, Any]) -> str:
    title = str(video.get("title") or "")
    tag = hook_pattern_tag(video)
    if tag == "Curiosity":
        return "How [surprising condition] is [familiar object/problem]?"
    if tag == "Spectacle":
        return "When [specific high-friction problem] happens, watch [unexpected attempt/payoff]."
    if tag == "Transformation":
        return "I turned [mess/before state] into [clean/after state] under [constraint]."
    if tag == "Challenge":
        return "We're trying to reach [clear finish line] before [constraint/time pressure]."
    if tag == "Social Proof":
        return "Watch [specific person/audience] react to [proof/result]."
    if re.search(r"\d", title):
        return "[Number/timeframe] ways [avatar] can get [specific result]."
    return "[Plain-language premise] with a visible payoff by the end."


def adjacent_hooks(entry: Dict[str, Any], spine: Dict[str, Any]) -> List[str]:
    template = entry["template"]
    avatar = spine["avatar"]
    promise = spine["promise"]
    return [
        template.replace("[familiar object/problem]", "[adjacent object/problem]").replace("[specific high-friction problem]", "[adjacent high-friction problem]"),
        f"What happens when {avatar} tries [specific constraint] for [short timeframe]?",
        f"I tested [one surprising version of the promise] so you can see {promise.lower()}",
    ]


def build_hook_library(top: List[Dict[str, Any]], transcripts: Dict[str, Dict[str, Any]], spine: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    winners: List[Dict[str, Any]] = []
    for video in top[:5]:
        raw = transcript_opening(video, transcripts) or str(video.get("title") or "Untitled hook")
        entry = {
            "source_title": video.get("title") or video.get("id"),
            "source_url": video.get("source_url") or "",
            "raw_hook": raw,
            "template": hook_template(video),
            "pattern_tag": hook_pattern_tag(video),
            "meat_type": infer_meat_type(video),
        }
        winners.append(entry)
    adjacent: List[Dict[str, Any]] = []
    for entry in winners[:5]:
        for hook in adjacent_hooks(entry, spine)[:1]:
            adjacent.append({
                "source_url": entry["source_url"],
                "hook": hook,
                "template_source": entry["template"],
                "pattern_tag": entry["pattern_tag"],
            })
    return {"winners": winners, "adjacent": adjacent[:5]}


def cta_for_path(path: str, promise: str) -> str:
    normalized = path.lower().strip()
    clean_promise = promise.rstrip(".")
    promise_fragment = clean_promise[:1].lower() + clean_promise[1:] if clean_promise else "the promised outcome"
    library = {
        "sub": f"Subscribe so you do not miss the next test: {clean_promise}.",
        "click": f"Tap the link in the description for the next step: {clean_promise}.",
        "opt_in": f"Comment 'SIGNAL' and the next step is a DM with the checklist for {promise_fragment}.",
        "buy": f"Use code SIGNAL at checkout today to try the product behind {promise_fragment}.",
        "apply": f"Apply when you are ready; use the link in the description to take the next step toward {promise_fragment}.",
    }
    return library.get(normalized, library["sub"])


def style_adjustment(channel_style: str) -> str:
    return {
        "face_led": "Put the creator or subject on camera early; use reaction and voiceover to carry stakes.",
        "product_led": "Open on the product/result; keep hands, demo, and proof visible before the CTA.",
        "faceless": "Use captions, tight b-roll, screen/game footage, and fast proof cuts instead of personality beats.",
    }.get(channel_style, "Match the channel's native framing while preserving hook, proof, payoff, CTA.")


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


def build_sprint_rows(hook_library: Dict[str, List[Dict[str, Any]]], spine: Dict[str, Any], days: int = 14) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    winners = hook_library.get("winners") or []
    adjacent = hook_library.get("adjacent") or []
    if not winners:
        return rows
    for day in range(1, days + 1):
        if day <= 10:
            hook = winners[(day - 1) % len(winners)]
            test_type = "70% proven winner"
            hook_template_value = hook["template"]
            source_url = hook["source_url"]
            pattern_tag = hook["pattern_tag"]
            meat_type = hook["meat_type"]
        elif day <= 13 and adjacent:
            hook = adjacent[(day - 11) % len(adjacent)]
            test_type = "20% winner-adjacent"
            hook_template_value = hook["hook"]
            source_url = hook["source_url"]
            pattern_tag = hook["pattern_tag"]
            meat_type = spine["meats"][(day - 1) % len(spine["meats"])]
        else:
            test_type = "10% new experiment"
            hook_template_value = "What if [avatar] could get [promise/payoff] under [new constraint]?"
            source_url = winners[(day - 1) % len(winners)]["source_url"]
            pattern_tag = "Challenge"
            meat_type = spine["meats"][(day - 1) % len(spine["meats"])]
        rows.append({
            "day": str(day),
            "test_type": test_type,
            "hook_template": hook_template_value,
            "pattern_tag": pattern_tag,
            "meat_type": meat_type,
            "channel_style_adjustment": style_adjustment(spine["channel_style"]),
            "primary_path": spine["primary_path"],
            "cta": cta_for_path(spine["primary_path"], spine["promise"]),
            "source_url": source_url,
        })
    return rows


def platform_rows(videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for video in videos:
        platform = str(video.get("platform") or "youtube")
        grouped.setdefault(platform, []).append(video)
    rows = []
    for platform, items in sorted(grouped.items()):
        measured = [item for item in items if has_performance_metrics(item)]
        discovery = [item for item in items if not has_performance_metrics(item)]
        score_items = measured or items
        avg_score = sum(float(item.get("cross_channel_signal_score") or item.get("signal_score") or 0) for item in score_items) / max(len(score_items), 1)
        best = max(score_items, key=lambda item: item.get("cross_channel_signal_score") or item.get("signal_score") or 0)
        rows.append({
            "platform": platform,
            "count": len(items),
            "measured_count": len(measured),
            "discovery_count": len(discovery),
            "avg_score": round(avg_score),
            "best_title": best.get("title") or best.get("id"),
            "best_url": best.get("source_url"),
        })
    return rows


def discovery_note(video: Dict[str, Any]) -> str:
    raw = video.get("raw") if isinstance(video.get("raw"), dict) else {}
    return raw.get("notes") or video.get("notes") or video.get("signal_reason") or "Discovery/profile row; performance metrics were not supplied."


def thumbnail_concept(video: Dict[str, Any], brand: Dict[str, Any]) -> str:
    hook = infer_hook(video)
    industry = brand.get("industry") or "your industry"
    if "transformation" in hook:
        return f"Split-frame before/after result in {industry}; big contrast, 3-5 word overlay, proof visible."
    if "countdown" in hook or "specificity" in hook:
        return "Large number/progress cue, expressive reaction, simple high-contrast background."
    if "tension" in hook:
        return "Freeze the highest-tension moment with a short contradiction overlay and clear subject focus."
    return "Clean close-up of the action/result with one curiosity phrase and no clutter."


def write_calendar(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "day",
            "test_type",
            "hook_template",
            "pattern_tag",
            "meat_type",
            "channel_style_adjustment",
            "primary_path",
            "cta",
            "source_url",
        ])
        writer.writeheader()
        writer.writerows(rows)


def run_json(cmd: List[str]) -> Dict[str, Any]:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Expected JSON from {' '.join(cmd)}, got:\n{proc.stdout}") from exc


def default_doc_title(brand: Dict[str, Any], report_path: Path) -> str:
    brand_name = brand.get("brand_name")
    if brand_name and brand_name != DEFAULT_BRAND["brand_name"]:
        return f"Attract Signal Brief - {brand_name}"
    return f"Attract Signal Brief - {report_path.stem.replace('-', ' ').replace('_', ' ').title()}"


def publish_google_doc(report_path: Path, title: str, parent: Optional[str] = None, pageless: bool = True) -> Dict[str, Any]:
    if shutil.which("gog") is None:
        raise RuntimeError("gogcli is required. Install with: brew install openclaw/tap/gogcli")
    cmd = ["gog", "docs", "create", title, "--file", str(report_path), "--json"]
    if pageless:
        cmd.append("--pageless")
    if parent:
        cmd.extend(["--parent", parent])
    created = run_json(cmd)
    doc_id = (created.get("file") or {}).get("id") or created.get("id")
    if not doc_id:
        raise RuntimeError("Google Doc was created but no document ID was returned")
    verified = run_json(["gog", "drive", "get", doc_id, "--json"])
    result = {"created": created, "verified": verified}
    metadata_path = report_path.with_suffix(".google-doc.json")
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def open_google_doc(publish_result: Dict[str, Any]) -> None:
    created_file = (publish_result.get("created") or {}).get("file") or {}
    verified_file = publish_result.get("verified") or {}
    url = created_file.get("webViewLink") or verified_file.get("webViewLink")
    if url and shutil.which("open"):
        subprocess.run(["open", url], check=False)


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
    all_items = signals.get("videos") or signals.get("top_signals") or []
    ranked = signals.get("top_signals") or all_items
    measured_ranked = [item for item in ranked if has_performance_metrics(item)]
    top = (measured_ranked or ranked)[:top_n]
    discovery_items = signals.get("discovery_items")
    if discovery_items is None:
        discovery_items = [item for item in all_items if not has_performance_metrics(item)]
    transcripts = transcripts or {}
    keywords = top_keywords(top)
    spine = infer_spine(top, brand, keywords)
    hook_library = build_hook_library(top, transcripts, spine)
    lines: List[str] = []
    lines.append(f"# Attract Signal Strategy Report: {brand.get('brand_name', 'Your Brand')}")
    lines.append("")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Avatar: {spine['avatar']}")
    lines.append(f"- Promise: {spine['promise']}")
    lines.append(f"- Proof: {spine['proof']}")
    lines.append(f"- Path: {spine['primary_path']}")
    lines.append(f"- Brand context: {brand.get('assumption_note')}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    item_count = signals.get("item_count", signals.get("video_count", len(all_items or top)))
    video_count = signals.get("video_count", len([item for item in all_items if has_performance_metrics(item)]))
    discovery_count = signals.get("discovery_count", len(discovery_items))
    lines.append(f"- Analyzed {video_count} measured content item(s) and {discovery_count} discovery/profile row(s) across {signals.get('scan_count', 1)} scan(s).")
    lines.append("- The strongest signals are ranked by source performance, channel-relative outlier strength, engagement, and metadata completeness.")
    if item_count != video_count:
        lines.append("- Metric-less social profile discoveries are listed separately and not treated as performance winners.")
    lines.append("- Recommendations are normalized around Avatar, Promise, Proof, and Path so the same engine works across face-led, product-led, and faceless channels.")
    lines.append("- The 14-day sprint uses a 70/20/10 testing mix: proven hooks, winner-adjacent variations, then one new experiment.")
    if keywords:
        lines.append(f"- Repeated language signals: {', '.join(keywords)}.")
    lines.append("")
    lines.append("## Strategy Spine")
    lines.append("")
    lines.append("| Primitive | Inference | How to use it |")
    lines.append("|---|---|---|")
    lines.append(f"| Avatar | {md_escape(spine['avatar'])} | Write every hook as if this viewer has one obvious reason to stop. |")
    lines.append(f"| Promise | {md_escape(spine['promise'])} | Keep each short attached to the channel's reason to exist. |")
    lines.append(f"| Proof | {md_escape(spine['proof'])} | Use these as the two main meats after the hook. |")
    lines.append(f"| Path | {md_escape(spine['primary_path'])} | Pick CTAs from this path family instead of generic engagement asks. |")
    lines.append(f"| Channel style | {md_escape(spine['channel_style'])} | {md_escape(style_adjustment(spine['channel_style']))} |")
    lines.append("")
    lines.append("## Hook Library")
    lines.append("")
    lines.append("### Top 5 Winning Hooks")
    lines.append("")
    lines.append("| Rank | Raw hook | Template | Pattern tag | Meat | Source |")
    lines.append("|---:|---|---|---|---|---|")
    for index, hook in enumerate(hook_library["winners"], 1):
        lines.append(
            f"| {index} | {md_escape(hook['raw_hook'])} | {md_escape(hook['template'])} | "
            f"{md_escape(hook['pattern_tag'])} | {md_escape(hook['meat_type'])} | [source]({hook['source_url']}) |"
        )
    lines.append("")
    lines.append("### Winner-Adjacent Hooks")
    lines.append("")
    lines.append("| Variant | Hook to test | Pattern tag | Source pattern |")
    lines.append("|---:|---|---|---|")
    for index, hook in enumerate(hook_library["adjacent"], 1):
        lines.append(
            f"| {index} | {md_escape(hook['hook'])} | {md_escape(hook['pattern_tag'])} | [source]({hook['source_url']}) |"
        )
    lines.append("")
    lines.append("## Meats, Style, And CTA System")
    lines.append("")
    lines.append(f"- Primary meats: {', '.join(spine['meats'])}.")
    lines.append(f"- Channel style: `{spine['channel_style']}`. {style_adjustment(spine['channel_style'])}")
    lines.append(f"- Primary path: `{spine['primary_path']}`.")
    lines.append(f"- Modular CTA: {cta_for_path(spine['primary_path'], spine['promise'])}")
    lines.append("- Script structure: Hook from library -> Meat -> Payoff -> CTA.")
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
            f"{md_escape(hook_template(video))} -> {md_escape(infer_meat_type(video))} -> {md_escape(cta_for_path(spine['primary_path'], spine['promise']))} |"
        )
    lines.append("")
    if discovery_items:
        lines.append("## Discovered Social Profiles")
        lines.append("")
        lines.append("| Platform | Source | Status / note |")
        lines.append("|---|---|---|")
        for item in discovery_items:
            platform = item.get("platform") or "unknown"
            title = item.get("title") or item.get("id") or platform
            url = item.get("source_url") or item.get("watch_url") or ""
            lines.append(f"| {md_escape(platform)} | [{md_escape(title)}]({url}) | {md_escape(discovery_note(item))} |")
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
    lines.append("## Platform Comparison")
    lines.append("")
    lines.append("| Platform | Measured content | Discovery rows | Avg measured score | Best measured/source item | Platform-specific strategy |")
    lines.append("|---|---:|---:|---:|---|---|")
    platform_basis = all_items or top
    for row in platform_rows(platform_basis):
        strategy = {
            "youtube": "Package as Shorts with strong first-frame clarity and source-cited follow-up ideas.",
            "tiktok": "Lean into fast native trend language, comments-as-briefs, and looser creator delivery.",
            "instagram": "Prioritize visual polish, saveable tips, carousels/Reels pairing, and profile trust.",
            "x": "Pair short video with a text hook/thread that frames the insight before playback.",
        }.get(row["platform"], "Adapt the winning premise to the platform's native pacing and audience expectations.")
        lines.append(f"| {md_escape(row['platform'])} | {row['measured_count']} | {row['discovery_count']} | {row['avg_score']} | [{md_escape(row['best_title'])}]({row['best_url']}) | {md_escape(strategy)} |")
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
        lines.append(f"- Hook template: {hook_template(video)}")
        lines.append(f"- Pattern tag: {hook_pattern_tag(video)}")
        lines.append(f"- Meat: {infer_meat_type(video)}")
        lines.append(f"- 0-2s hook: Adapt the template for {spine['avatar']}.")
        lines.append(f"- Script beat: hook, {infer_meat_type(video).lower()} meat, payoff, then `{spine['primary_path']}` CTA.")
        lines.append(f"- Avoid copying: do not reuse the source creator's exact premise, wording, setting, or edit sequence.")
        lines.append("")
    lines.append("## Script Drafts")
    lines.append("")
    for index, video in enumerate(top[:3], 1):
        lines.append(f"### Script {index}: {concept_title(video, brand, index)}")
        lines.append("")
        lines.append(f"- Hook: Use template `{hook_template(video)}` for {spine['avatar']}.")
        lines.append(f"- Meat: {infer_meat_type(video)} proof that supports `{spine['promise']}`.")
        lines.append("- Payoff: Show the result, lesson, or reversal clearly before the final beat.")
        lines.append(f"- CTA: {cta_for_path(spine['primary_path'], spine['promise'])}")
        lines.append(f"- Style adjustment: {style_adjustment(spine['channel_style'])}")
        lines.append(f"- Source reference: {video.get('source_url')}")
        lines.append("")
    lines.append("## Shot Lists")
    lines.append("")
    lines.append("| Shot | Duration | Structure | Framing | Action | Notes |")
    lines.append("|---:|---:|---|---|---|---|")
    lines.append(f"| 1 | 0-2s | Hook | style-specific first frame | Use a winning hook template | {style_adjustment(spine['channel_style'])} |")
    lines.append(f"| 2 | 2-8s | Meat | proof-first shot | Deliver {spine['meats'][0].lower()} evidence | Keep the promise visible. |")
    lines.append(f"| 3 | 8-18s | Meat | sequence cuts | Add {spine['meats'][1].lower()} support | Escalate stakes or clarity. |")
    lines.append("| 4 | 18-25s | Payoff | reveal/result frame | Show the result, lesson, or reversal | Make the value obvious without context. |")
    lines.append(f"| 5 | 25-30s | CTA | final frame | {cta_for_path(spine['primary_path'], spine['promise'])} | Define what to do, how, when, what they get, and what happens next. |")
    lines.append("")
    lines.append("## Thumbnail Concepts")
    lines.append("")
    for index, video in enumerate(top[:5], 1):
        lines.append(f"- {index}. {thumbnail_concept(video, brand)} Source: {video.get('source_url')}")
    lines.append("")
    lines.append("## Storyboard Prompts")
    lines.append("")
    lines.append(f"- Frame 1: vertical first-frame hook for {spine['avatar']}, pattern tag from the hook library, clear tension.")
    lines.append(f"- Frame 2: {spine['meats'][0].lower()} proof frame that makes `{spine['promise']}` visible.")
    lines.append(f"- Frame 3: payoff/reversal frame for {spine['channel_style']} delivery, brand-safe and realistic.")
    lines.append(f"- Frame 4: CTA frame for `{spine['primary_path']}` path, showing the next step and payoff.")
    lines.append("")
    lines.append("## Optional Image Generation Workflow")
    lines.append("")
    lines.append("- Use the storyboard prompts as source-cited direction for image generation only after the script and claims are approved.")
    lines.append("- Generate storyboard frames, not copies of source creators, source footage, logos, private people, or distinctive sets.")
    lines.append("- Keep each generated frame tied to the brand setting, offer, audience, and proof points.")
    lines.append("")
    lines.append("## Signal Library Next Step")
    lines.append("")
    lines.append("- Save these signals into the reusable library with `signal_library.py add --signals signals.json --top-only`.")
    lines.append("- Search prior signals before making a new sprint so strong hook templates compound across future campaigns.")
    lines.append("")
    lines.append("## 14-Day Sprint Matrix")
    lines.append("")
    lines.append("| Day | Test mix | Hook template | Pattern tag | Meat | Channel style adjustment | Path / CTA | Source |")
    lines.append("|---:|---|---|---|---|---|---|---|")
    for row in build_sprint_rows(hook_library, spine, 14):
        lines.append(
            f"| {row['day']} | {md_escape(row['test_type'])} | {md_escape(row['hook_template'])} | "
            f"{md_escape(row['pattern_tag'])} | {md_escape(row['meat_type'])} | {md_escape(row['channel_style_adjustment'])} | "
            f"{md_escape(row['primary_path'])}: {md_escape(row['cta'])} | [source]({row['source_url']}) |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an industry-agnostic Attract Signal Markdown report.")
    parser.add_argument("--signals", type=Path, required=True, help="signals.json produced by analyze_signals.py")
    parser.add_argument("--brand", type=Path, default=None, help="Optional brand.yaml context file")
    parser.add_argument("--out", type=Path, required=True, help="Write Markdown report to this path")
    parser.add_argument("--calendar", type=Path, default=None, help="Optional CSV 14-day sprint matrix output")
    parser.add_argument("--transcripts-dir", type=Path, default=None, help="Optional directory containing transcript JSON files named <video_id>.json")
    parser.add_argument("--top", type=int, default=10, help="Number of top signals to include")
    parser.add_argument("--no-google-doc", action="store_true", help="Only write local files; skip the default Google Doc copy")
    parser.add_argument("--doc-title", default=None, help="Google Doc title. Defaults to 'Attract Signal Brief - <brand/report>'.")
    parser.add_argument("--doc-parent", default=None, help="Optional Google Drive folder ID for the generated Doc")
    parser.add_argument("--no-pageless", action="store_true", help="Create the Google Doc with normal pages instead of pageless mode")
    parser.add_argument("--open-doc", action="store_true", help="Open the created Google Doc in the default browser")
    parser.add_argument("--require-google-doc", action="store_true", help="Fail if the default Google Doc publishing step fails")
    args = parser.parse_args()

    signals = load_json(args.signals)
    brand = load_brand(args.brand)
    transcripts = load_transcripts(args.transcripts_dir)
    report = generate_report(signals, brand, args.top, transcripts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    if args.calendar:
        ranked = signals.get("top_signals") or signals.get("videos") or []
        measured_ranked = [item for item in ranked if has_performance_metrics(item)]
        top = (measured_ranked or ranked)[: args.top]
        keywords = top_keywords(top)
        spine = infer_spine(top, brand, keywords)
        hook_library = build_hook_library(top, transcripts, spine)
        write_calendar(args.calendar, build_sprint_rows(hook_library, spine, 14))
    result: Dict[str, Any] = {
        "markdown": str(args.out),
        "calendar": str(args.calendar) if args.calendar else None,
        "google_doc": None,
    }
    if not args.no_google_doc:
        try:
            publish_result = publish_google_doc(
                args.out,
                args.doc_title or default_doc_title(brand, args.out),
                parent=args.doc_parent,
                pageless=not args.no_pageless,
            )
            result["google_doc"] = publish_result
            if args.open_doc:
                open_google_doc(publish_result)
        except Exception as exc:
            message = f"WARNING: local report was generated, but Google Doc publishing failed: {exc}"
            if args.require_google_doc:
                raise RuntimeError(message) from exc
            result["google_doc_error"] = str(exc)
            print(message, file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
