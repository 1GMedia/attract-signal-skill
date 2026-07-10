#!/usr/bin/env python3
"""Turn Last30Days Reddit evidence into ranked Attract Signal conversation lenses.

The analyzer is deliberately deterministic and dependency-free. It accepts a
Last30Days raw Markdown report or normalized Reddit JSON, preserves source URLs
and exact language, and produces JSON plus an optional reviewable Markdown
brief. Semantic synthesis and content creation remain the agent's job.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Optional


LENSES = {
    "pain_points": {
        "label": "Pain Points",
        "patterns": (
            r"\b(frustrat(?:ed|ing)|struggl(?:e|ing)|problem|pain point|annoying|overwhelmed)\b",
            r"\b(broken|doesn['’]?t work|can['’]?t|cannot|difficult|hard to|hate|sucks?|worst)\b",
            r"\b(issue|bug|failure|failing|waste(?:d)?|tired of|fed up)\b",
        ),
        "content_job": "Name the pain in the audience's own words, then show a practical fix or decision path.",
    },
    "solution_requests": {
        "label": "Solution Requests",
        "patterns": (
            r"\b(looking for|need (?:a|an|help)|is there (?:a|an)|wish there (?:was|were))\b",
            r"\b(any (?:tool|app|service|recommendation)|recommend(?:ation|ations|ed)?|what do you use)\b",
            r"\b(how (?:do|can|would|should) (?:i|you|we)|where can i|advice|suggestions?)\b",
        ),
        "content_job": "Answer the explicit question with a useful framework, walkthrough, or shortlist.",
    },
    "money_talk": {
        "label": "Money Talk",
        "patterns": (
            r"(?:[$€£]\s?\d|\b\d+(?:\.\d+)?\s?(?:usd|dollars?|bucks?)\b)",
            r"\b(price|pricing|cost|costs|expensive|cheap|cheaper|budget|afford)\b",
            r"\b(pay|paid|paying|worth it|subscription|per month|monthly|annual|yearly|roi)\b",
        ),
        "content_job": "Create a price, value, ROI, or hidden-cost breakdown grounded in the cited discussion.",
    },
    "hot_discussions": {
        "label": "Hot Discussions",
        "patterns": (
            r"\b(unpopular opinion|hot take|controversial|debate|discussion|thoughts\?)\b",
            r"\b(agree|disagree|change my mind|am i wrong|who else|what does everyone think)\b",
        ),
        "content_job": "Frame the live debate fairly, then add a clear point of view or evidence-backed test.",
    },
    "seeking_alternatives": {
        "label": "Seeking Alternatives",
        "patterns": (
            r"\b(alternatives?|replacement|substitute|competitors?)\b",
            r"\b(switch(?:ed|ing)? (?:from|to)|moving away from|leave|leaving|migrate|migration)\b",
            r"\b(instead of|better than|versus|\bvs\.?\b|fed up with|cancel(?:led|ing)?)\b",
        ),
        "content_job": "Build an honest comparison or switching guide that states who each option is for.",
    },
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "how", "i",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "what",
    "with", "you", "your",
}


@dataclass
class Conversation:
    item_id: str
    title: str
    body: str
    source_url: str
    subreddit: str = "unknown"
    author: Optional[str] = None
    published_at: Optional[str] = None
    upvotes: int = 0
    comment_count: int = 0
    top_comments: list[dict[str, Any]] = field(default_factory=list)
    lenses: list[str] = field(default_factory=list)
    lens_matches: dict[str, int] = field(default_factory=dict)
    signal_score: int = 0
    rank_reason: list[str] = field(default_factory=list)
    exact_quote: str = ""


def parse_number(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower().replace(",", "")
    multiplier = 1
    if text.endswith("k"):
        multiplier, text = 1_000, text[:-1]
    elif text.endswith("m"):
        multiplier, text = 1_000_000, text[:-1]
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return max(0, int(float(match.group()) * multiplier)) if match else 0


def first_value(row: dict[str, Any], names: Iterable[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_url(value: Any) -> str:
    url = clean_text(value)
    if url.startswith("/r/") or url.startswith("/comments/"):
        return f"https://www.reddit.com{url}"
    return url


def parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = clean_text(value)
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def normalize_comments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    comments: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            text, author, score, url = clean_text(item), None, 0, ""
        elif isinstance(item, dict):
            text = clean_text(first_value(item, ("text", "body", "excerpt", "comment")))
            author = clean_text(first_value(item, ("author", "username", "user"))) or None
            score = parse_number(first_value(item, ("score", "upvotes", "ups", "likes")))
            url = normalize_url(first_value(item, ("url", "permalink", "link")))
        else:
            continue
        if text:
            comments.append({"text": text, "author": author, "upvotes": score, "source_url": url})
    comments.sort(key=lambda item: item["upvotes"], reverse=True)
    return comments[:10]


def looks_like_reddit(row: dict[str, Any], inherited_source: Optional[str]) -> bool:
    source = clean_text(first_value(row, ("source", "platform")) or inherited_source).lower()
    if source and source not in {"reddit", "r"}:
        return False
    if source == "reddit":
        return True
    url = clean_text(first_value(row, ("url", "source_url", "permalink"))).lower()
    return "reddit.com/" in url or first_value(row, ("subreddit", "container")) is not None


def extract_json_rows(payload: Any, inherited_source: Optional[str] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                if looks_like_reddit(item, inherited_source):
                    rows.append(item)
                else:
                    rows.extend(extract_json_rows(item, inherited_source))
        return rows
    if not isinstance(payload, dict):
        return rows

    if looks_like_reddit(payload, inherited_source) and any(
        first_value(payload, names) is not None
        for names in (("title", "name"), ("body", "selftext", "snippet", "evidence"), ("url", "permalink"))
    ):
        rows.append(payload)

    for key in ("reddit", "items", "posts", "threads", "results", "rows", "data", "ranked_candidates"):
        child = payload.get(key)
        if isinstance(child, (list, dict)):
            rows.extend(extract_json_rows(child, "reddit" if key == "reddit" else inherited_source))
    items_by_source = payload.get("items_by_source")
    if isinstance(items_by_source, dict) and "reddit" in items_by_source:
        rows.extend(extract_json_rows(items_by_source["reddit"], "reddit"))
    return rows


def row_to_conversation(row: dict[str, Any], index: int) -> Conversation:
    engagement = row.get("engagement") if isinstance(row.get("engagement"), dict) else {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    title = clean_text(first_value(row, ("title", "name", "headline")))
    body = clean_text(first_value(row, ("body", "selftext", "snippet", "evidence", "text", "description")))
    url = normalize_url(first_value(row, ("url", "source_url", "permalink", "link")))
    subreddit = clean_text(first_value(row, ("subreddit", "container", "community")))
    if not subreddit:
        subreddit = clean_text(first_value(metadata, ("subreddit", "container")))
    subreddit = re.sub(r"^r/", "", subreddit, flags=re.IGNORECASE) or "unknown"
    upvotes = parse_number(
        first_value(row, ("upvotes", "ups", "score", "points"))
        or first_value(engagement, ("score", "upvotes", "ups", "points"))
    )
    comment_count = parse_number(
        first_value(row, ("comment_count", "num_comments", "comments", "reply_count"))
        or first_value(engagement, ("num_comments", "comments", "reply_count"))
    )
    comments = normalize_comments(
        first_value(row, ("top_comments", "comments_data", "comment_samples"))
        or first_value(metadata, ("top_comments", "comments"))
    )
    published = first_value(row, ("published_at", "created_at", "created_utc", "date", "upload_date"))
    published_date = parse_date(published)
    item_id = clean_text(first_value(row, ("item_id", "id", "post_id", "name"))) or f"reddit-{index:04d}"
    return Conversation(
        item_id=item_id,
        title=title or body[:100] or f"Reddit conversation {index}",
        body=body,
        source_url=url,
        subreddit=subreddit,
        author=clean_text(first_value(row, ("author", "username", "user"))) or None,
        published_at=published_date.isoformat() if published_date else clean_text(published) or None,
        upvotes=upvotes,
        comment_count=comment_count,
        top_comments=comments,
    )


ITEM_START = re.compile(r"^\s*\d+\.\s+\[([^\]]+)\]\s+(.+?)\s*$", re.IGNORECASE)


def parse_last30days_markdown(text: str) -> list[Conversation]:
    lines = text.splitlines()
    conversations: list[Conversation] = []
    index = 0
    while index < len(lines):
        match = ITEM_START.match(lines[index])
        if not match:
            index += 1
            continue
        source, title = match.groups()
        block_end = index + 1
        while block_end < len(lines) and not ITEM_START.match(lines[block_end]):
            if lines[block_end].startswith("### ") or lines[block_end].startswith("## "):
                break
            block_end += 1
        if source.strip().lower() == "reddit":
            block = lines[index + 1:block_end]
            details = ""
            url = ""
            evidence = ""
            comments: list[dict[str, Any]] = []
            for line in block:
                stripped = line.strip()
                if stripped.startswith("- URL:"):
                    url = normalize_url(stripped.split(":", 1)[1])
                elif stripped.startswith("- Evidence:"):
                    evidence = clean_text(stripped.split(":", 1)[1])
                elif stripped.startswith("-") and "score:" in stripped and not details:
                    details = stripped.lstrip("- ")
                else:
                    comment_match = re.match(
                        r"^-\s+(u/[\w-]+|[^()]+?)\s+\(([-\d,]+)\s+(?:upvotes?|pts?)\):\s+(.+)$",
                        stripped,
                        re.IGNORECASE,
                    )
                    if comment_match:
                        author, score, comment = comment_match.groups()
                        comments.append({
                            "text": clean_text(comment),
                            "author": clean_text(author),
                            "upvotes": parse_number(score),
                            "source_url": url,
                        })
            date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", details)
            sub_match = re.search(r"\br/([A-Za-z0-9_]+)\b", details)
            upvote_match = re.search(r"([\d,.]+[kKmM]?)\s*(?:pts?|upvotes?)\b", details, re.IGNORECASE)
            comment_count_match = re.search(r"([\d,.]+[kKmM]?)\s*(?:cmt|comments?)\b", details, re.IGNORECASE)
            conversations.append(Conversation(
                item_id=f"reddit-md-{len(conversations) + 1:04d}",
                title=clean_text(title),
                body=evidence,
                source_url=url,
                subreddit=sub_match.group(1) if sub_match else "unknown",
                published_at=date_match.group(1) if date_match else None,
                upvotes=parse_number(upvote_match.group(1)) if upvote_match else 0,
                comment_count=parse_number(comment_count_match.group(1)) if comment_count_match else 0,
                top_comments=comments,
            ))
        index = max(block_end, index + 1)
    return conversations


def load_conversations(path: Path) -> list[Conversation]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = extract_json_rows(payload)
        return [row_to_conversation(row, index) for index, row in enumerate(rows, 1)]
    return parse_last30days_markdown(path.read_text(encoding="utf-8"))


def token_set(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9+#.-]*", value.lower())
        if len(token) > 1 and token not in STOP_WORDS
    }


def classify(conversation: Conversation, hot_threshold: float) -> None:
    text = f"{conversation.title}\n{conversation.body}".lower()
    matches: dict[str, int] = {}
    for lens, config in LENSES.items():
        count = sum(len(re.findall(pattern, text, flags=re.IGNORECASE)) for pattern in config["patterns"])
        if count:
            matches[lens] = count
    engagement = conversation.upvotes + (conversation.comment_count * 3)
    if engagement >= hot_threshold and engagement > 0:
        matches["hot_discussions"] = max(1, matches.get("hot_discussions", 0))
    conversation.lens_matches = matches
    conversation.lenses = list(matches)


def choose_exact_quote(conversation: Conversation) -> str:
    """Prefer the source text that carries the strongest matched signal."""
    candidates = [text for text in (conversation.title, conversation.body) if text]
    if not candidates:
        return ""

    def quote_strength(text: str) -> tuple[int, int, int]:
        matched = 0
        for lens in conversation.lenses:
            matched += sum(
                len(re.findall(pattern, text, flags=re.IGNORECASE))
                for pattern in LENSES[lens]["patterns"]
            )
        return matched, int("?" in text), min(len(text), 320)

    return max(candidates, key=quote_strength)[:320]


def score_conversations(conversations: list[Conversation], topic: str, as_of: date, window_days: int) -> None:
    engagement_values = [item.upvotes + item.comment_count * 3 for item in conversations]
    max_engagement = max(engagement_values, default=0)
    positive = [value for value in engagement_values if value > 0]
    hot_threshold = max(10.0, median(positive) * 1.5) if positive else math.inf
    topic_tokens = token_set(topic)

    for conversation in conversations:
        classify(conversation, hot_threshold)
        text_tokens = token_set(f"{conversation.title} {conversation.body}")
        if topic_tokens:
            relevance = len(topic_tokens & text_tokens) / len(topic_tokens)
        else:
            relevance = 0.60

        raw_engagement = conversation.upvotes + conversation.comment_count * 3
        engagement = math.log1p(raw_engagement) / math.log1p(max_engagement) if max_engagement else 0.0

        published = parse_date(conversation.published_at)
        if published:
            age = max(0, (as_of - published).days)
            recency = max(0.0, 1 - (age / max(window_days, 1)))
        else:
            recency = 0.45

        hit_count = sum(conversation.lens_matches.values())
        urgency = min(1.0, hit_count / 3)
        commercial = 0.0
        if "money_talk" in conversation.lenses:
            commercial += 0.55
        if "seeking_alternatives" in conversation.lenses:
            commercial += 0.45
        if "solution_requests" in conversation.lenses:
            commercial += 0.25
        commercial = min(1.0, commercial)

        blended = (
            relevance * 0.28
            + engagement * 0.23
            + recency * 0.16
            + urgency * 0.15
            + commercial * 0.18
        )
        conversation.signal_score = round(blended * 100)
        conversation.exact_quote = choose_exact_quote(conversation)
        reasons = []
        if relevance >= 0.7:
            reasons.append("strong topic match")
        if engagement >= 0.7:
            reasons.append("high engagement")
        if recency >= 0.7:
            reasons.append("recent")
        if commercial >= 0.5:
            reasons.append("commercial intent")
        if conversation.lenses:
            reasons.append("matches " + ", ".join(LENSES[lens]["label"] for lens in conversation.lenses))
        conversation.rank_reason = reasons or ["available Reddit evidence"]


def dedupe(conversations: list[Conversation]) -> list[Conversation]:
    unique: dict[str, Conversation] = {}
    for item in conversations:
        key = item.source_url.lower().rstrip("/") or clean_text(item.title).lower()
        existing = unique.get(key)
        if not existing or (item.upvotes + item.comment_count) > (existing.upvotes + existing.comment_count):
            unique[key] = item
    return list(unique.values())


def serialize_conversation(item: Conversation) -> dict[str, Any]:
    payload = asdict(item)
    payload["lens_labels"] = [LENSES[lens]["label"] for lens in item.lenses]
    return payload


def build_payload(
    conversations: list[Conversation],
    topic: str,
    inputs: list[Path],
    as_of: date,
    window_days: int,
    top: int,
) -> dict[str, Any]:
    ranked = sorted(
        conversations,
        key=lambda item: (item.signal_score, item.comment_count, item.upvotes),
        reverse=True,
    )
    subreddit_rows: dict[str, list[Conversation]] = defaultdict(list)
    for item in ranked:
        subreddit_rows[item.subreddit].append(item)
    audience_map = []
    for subreddit, items in sorted(
        subreddit_rows.items(),
        key=lambda pair: (len(pair[1]), sum(row.upvotes + row.comment_count for row in pair[1])),
        reverse=True,
    ):
        lens_counts = Counter(lens for item in items for lens in item.lenses)
        audience_map.append({
            "subreddit": subreddit,
            "conversation_count": len(items),
            "upvotes": sum(item.upvotes for item in items),
            "comments": sum(item.comment_count for item in items),
            "lens_counts": dict(lens_counts),
            "top_source_url": items[0].source_url,
        })

    by_lens = {
        lens: [serialize_conversation(item) for item in ranked if lens in item.lenses]
        for lens in LENSES
    }
    exact_language = []
    for item in ranked[:top]:
        if item.exact_quote and item.source_url:
            exact_language.append({
                "kind": "thread",
                "quote": item.exact_quote,
                "author": item.author,
                "subreddit": item.subreddit,
                "lenses": item.lenses,
                "source_url": item.source_url,
            })
        for comment in item.top_comments[:3]:
            comment_url = comment.get("source_url") or item.source_url
            if comment.get("text") and comment_url:
                exact_language.append({
                    "kind": "comment",
                    "quote": comment["text"],
                    "author": comment.get("author"),
                    "subreddit": item.subreddit,
                    "lenses": item.lenses,
                    "upvotes": comment.get("upvotes", 0),
                    "source_url": comment_url,
                })
    content_opportunities = []
    for lens, config in LENSES.items():
        items = [item for item in ranked if lens in item.lenses]
        content_opportunities.append({
            "lens": lens,
            "label": config["label"],
            "evidence_count": len(items),
            "content_job": config["content_job"],
            "top_source_url": items[0].source_url if items else None,
            "top_quote": items[0].exact_quote if items else None,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic or None,
        "as_of": as_of.isoformat(),
        "window_days": window_days,
        "input_files": [str(path) for path in inputs],
        "conversation_count": len(ranked),
        "lens_definitions": {
            lens: {"label": config["label"], "content_job": config["content_job"]}
            for lens, config in LENSES.items()
        },
        "audience_map": audience_map,
        "top_conversations": [serialize_conversation(item) for item in ranked[:top]],
        "lenses": by_lens,
        "exact_language": exact_language,
        "content_opportunities": content_opportunities,
        "notes": [
            "Classification is deterministic and multi-label; the agent should review ambiguous items semantically.",
            "Every finding retains its Reddit source URL; missing URLs are left blank, never invented.",
            "A complaint is not purchase intent unless the evidence also shows solution, money, or switching language.",
            "Use references/reddit-deep-research-prompt.md to turn this evidence into content strategy.",
        ],
    }


def md_escape(value: Any) -> str:
    return clean_text(value).replace("|", "\\|").replace("\n", " ")


def linked_source(url: str) -> str:
    return f"[Reddit]({url})" if url else "URL unavailable"


def render_markdown(payload: dict[str, Any], per_lens: int) -> str:
    topic = payload.get("topic") or "Reddit audience"
    lines = [
        f"# Deep Reddit Conversation Signals: {topic}",
        "",
        f"- As of: {payload['as_of']} ({payload['window_days']}-day window)",
        f"- Conversations analyzed: {payload['conversation_count']}",
        f"- Inputs: {', '.join(payload['input_files'])}",
        "",
        "## Audience and Subreddit Map",
        "",
        "| Subreddit | Conversations | Upvotes | Comments | Strongest lenses | Top source |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in payload["audience_map"]:
        labels = sorted(row["lens_counts"], key=row["lens_counts"].get, reverse=True)
        label_text = ", ".join(LENSES[lens]["label"] for lens in labels[:3]) or "No strong lens"
        lines.append(
            f"| r/{md_escape(row['subreddit'])} | {row['conversation_count']} | {row['upvotes']} | "
            f"{row['comments']} | {md_escape(label_text)} | {linked_source(row['top_source_url'])} |"
        )

    lines.extend([
        "",
        "## Most Important Conversations",
        "",
        "| Score | Lenses | Community | Exact audience language | Source |",
        "|---:|---|---|---|---|",
    ])
    for item in payload["top_conversations"]:
        labels = ", ".join(item["lens_labels"]) or "Unclassified"
        lines.append(
            f"| {item['signal_score']} | {md_escape(labels)} | r/{md_escape(item['subreddit'])} | "
            f"\"{md_escape(item['exact_quote'])}\" | {linked_source(item['source_url'])} |"
        )

    lines.extend(["", "## Five Conversation Lenses", ""])
    for lens, config in LENSES.items():
        items = payload["lenses"][lens][:per_lens]
        lines.extend([f"### {config['label']}", ""])
        if not items:
            lines.extend(["No qualifying conversations in the supplied evidence.", ""])
            continue
        lines.extend([
            "| Score | Community | Exact language | Upvotes | Comments | Source |",
            "|---:|---|---|---:|---:|---|",
        ])
        for item in items:
            lines.append(
                f"| {item['signal_score']} | r/{md_escape(item['subreddit'])} | \"{md_escape(item['exact_quote'])}\" | "
                f"{item['upvotes']} | {item['comment_count']} | {linked_source(item['source_url'])} |"
            )
        lines.extend(["", f"Content job: {config['content_job']}", ""])

    lines.extend(["## Exact Audience Language", ""])
    for row in payload["exact_language"][:15]:
        labels = ", ".join(LENSES[lens]["label"] for lens in row["lenses"]) or "unclassified"
        attribution = f" by {row['author']}" if row.get("author") else ""
        vote_text = f", {row.get('upvotes', 0)} upvotes" if row["kind"] == "comment" else ""
        lines.append(
            f"- \"{row['quote']}\" - {row['kind']}{attribution}{vote_text} in r/{row['subreddit']} - "
            f"{labels} - {linked_source(row['source_url'])}"
        )

    question_rows = [
        item for item in payload["top_conversations"]
        if "solution_requests" in item["lenses"] or "?" in item["title"] or "?" in item["exact_quote"]
    ]
    objection_rows = [
        item for item in payload["top_conversations"]
        if "pain_points" in item["lenses"] or "seeking_alternatives" in item["lenses"]
    ]
    lines.extend(["", "## Questions and Objections", ""])
    if question_rows:
        lines.append("Questions:")
        for item in question_rows[:per_lens]:
            lines.append(f"- \"{item['exact_quote']}\" - {linked_source(item['source_url'])}")
    if objection_rows:
        lines.extend(["", "Objections and blockers:"])
        for item in objection_rows[:per_lens]:
            lines.append(f"- \"{item['exact_quote']}\" - {linked_source(item['source_url'])}")
    if not question_rows and not objection_rows:
        lines.append("No explicit question or objection was found in the supplied evidence.")

    buying = payload["lenses"]["money_talk"][:per_lens] + payload["lenses"]["seeking_alternatives"][:per_lens]
    lines.extend(["", "## Buying and Switching Signals", ""])
    if buying:
        seen: set[str] = set()
        for item in buying:
            key = item["source_url"] or item["item_id"]
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- \"{item['exact_quote']}\" - {linked_source(item['source_url'])}")
    else:
        lines.append("No explicit money or switching signal was found. Do not infer purchase intent from complaints alone.")

    lines.extend([
        "",
        "## Content Opportunity Matrix",
        "",
        "| Lens | Evidence | Content job | Best source |",
        "|---|---:|---|---|",
    ])
    for row in payload["content_opportunities"]:
        lines.append(
            f"| {row['label']} | {row['evidence_count']} | {md_escape(row['content_job'])} | "
            f"{linked_source(row['top_source_url'] or '') if row['top_source_url'] else 'None'} |"
        )

    lines.extend([
        "",
        "## Handoff to Attract Signal",
        "",
        "1. Read `references/reddit-deep-research-prompt.md`.",
        "2. Treat this file as evidence, not as finished strategy.",
        "3. Convert the strongest pains, questions, objections, money language, and switching signals into original hooks, scripts, shot lists, and 14-day tests.",
        "4. Keep a Reddit URL beside every evidence-backed content angle.",
        "5. Never invent quotes, engagement, prices, or demand.",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify and rank Last30Days Reddit evidence through five audience-research lenses."
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="Last30Days raw Markdown or normalized Reddit JSON")
    parser.add_argument("--topic", default="", help="Topic used for relevance scoring and report title")
    parser.add_argument("--days", type=int, default=30, help="Research window in days")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Window end date in YYYY-MM-DD format")
    parser.add_argument("--top", type=int, default=25, help="Maximum conversations in the ranked output")
    parser.add_argument("--per-lens", type=int, default=10, help="Maximum rows per lens in Markdown")
    parser.add_argument("--out", type=Path, default=None, help="Write structured JSON to this path")
    parser.add_argument("--markdown", type=Path, default=None, help="Write a reviewable Markdown brief")
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of)
    conversations = dedupe([item for path in args.inputs for item in load_conversations(path)])
    score_conversations(conversations, args.topic, as_of, args.days)
    payload = build_payload(conversations, args.topic, args.inputs, as_of, args.days, args.top)
    output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(payload, args.per_lens), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
