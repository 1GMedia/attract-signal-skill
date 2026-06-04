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
    "business_type": "",
    "brand_url": "",
    "industry": "your industry",
    "audience": "your target audience",
    "offer": "your offer, product, or service",
    "tone": "clear, useful, and brand-safe",
    "promise": "",
    "primary_path": "",
    "channel_style": "",
    "product_mode": "",
    "product_name": "",
    "product_url": "",
    "discount_code": "",
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

BUSINESS_TYPE_PRESETS = {
    "creator": {
        "label": "Creator / Influencer channel",
        "primary_path": "sub",
        "channel_style": "face_led",
        "meats": ["Story", "Demonstration"],
        "product_mode": False,
    },
    "product_brand": {
        "label": "Product brand / ecommerce",
        "primary_path": "click",
        "channel_style": "product_led",
        "meats": ["Demonstration", "Testimonial"],
        "product_mode": True,
    },
    "service": {
        "label": "Service / agency / local business",
        "primary_path": "book_call",
        "channel_style": "face_led",
        "meats": ["Demonstration", "Testimonial"],
        "product_mode": False,
    },
    "b2b_saas": {
        "label": "B2B SaaS / software product",
        "primary_path": "book_call",
        "channel_style": "face_led",
        "meats": ["Demonstration", "Education"],
        "product_mode": False,
    },
    "education": {
        "label": "Education / coaching / info",
        "primary_path": "opt_in",
        "channel_style": "face_led",
        "meats": ["Education", "Story"],
        "product_mode": False,
    },
    "other": {
        "label": "Other / inferred",
        "primary_path": "",
        "channel_style": "",
        "meats": [],
        "product_mode": False,
    },
}

BUSINESS_TYPE_ALIASES = {
    "creator": "creator",
    "influencer": "creator",
    "influencer_channel": "creator",
    "product": "product_brand",
    "product_brand": "product_brand",
    "ecom": "product_brand",
    "ecomm": "product_brand",
    "ecommerce": "product_brand",
    "e-commerce": "product_brand",
    "shopify": "product_brand",
    "amazon": "product_brand",
    "dtc": "product_brand",
    "service": "service",
    "services": "service",
    "agency": "service",
    "local": "service",
    "local_business": "service",
    "b2b": "b2b_saas",
    "b2b_saas": "b2b_saas",
    "saas": "b2b_saas",
    "software": "b2b_saas",
    "software_product": "b2b_saas",
    "education": "education",
    "coaching": "education",
    "course": "education",
    "info": "education",
    "other": "other",
}


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


def normalize_business_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    key = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    direct = BUSINESS_TYPE_ALIASES.get(key) or BUSINESS_TYPE_ALIASES.get(raw)
    if direct:
        return direct
    if any(term in raw for term in ("saas", "software", "b2b")):
        return "b2b_saas"
    if any(term in raw for term in ("shopify", "ecom", "e-commerce", "product", "dtc", "amazon")):
        return "product_brand"
    if any(term in raw for term in ("service", "agency", "local")):
        return "service"
    if any(term in raw for term in ("education", "coaching", "course", "info")):
        return "education"
    if any(term in raw for term in ("creator", "influencer")):
        return "creator"
    return "other"


def business_preset(brand: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_business_type(brand.get("business_type"))
    if not normalized:
        return {}
    return BUSINESS_TYPE_PRESETS.get(normalized, BUSINESS_TYPE_PRESETS["other"])


def has_brand_context(brand: Dict[str, Any]) -> bool:
    if str(brand.get("assumption_note") or "").startswith("No brand.yaml supplied"):
        return False
    keys = ("brand_name", "business_type", "brand_url", "industry", "audience", "offer", "promise", "primary_path", "channel_style", "product_name", "product_url")
    for key in keys:
        value = str(brand.get(key) or "").strip()
        default = str(DEFAULT_BRAND.get(key) or "").strip()
        if value and value != default:
            return True
    return False


def boolish(value: Any) -> Optional[bool]:
    normalized = str(value or "").strip().lower()
    if normalized in ("true", "yes", "1", "on"):
        return True
    if normalized in ("false", "no", "0", "off"):
        return False
    return None


def normalize_path(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "subscribe": "sub",
        "follow": "sub",
        "lead": "opt_in",
        "lead_gen": "opt_in",
        "optin": "opt_in",
        "opt_in": "opt_in",
        "demo": "book_call",
        "book_demo": "book_call",
        "book_call": "book_call",
        "book_a_call": "book_call",
        "call": "book_call",
    }
    return aliases.get(normalized, normalized)


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
    if has_word(blob, ("claude", "codex", "openclaw", "agent", "agents", "obsidian", "mcp", "workflow", "workflows")):
        return "AI builders, creators, and operators looking for practical tool workflows"
    if has_word(blob, ("comedy", "comedian", "roast", "roasts", "kill", "tony", "hilarious", "impersonation")):
        return "comedy fans and open mic comics looking for punchy premises, tension, and tags"
    if has_word(blob, ("startup", "founder", "founders", "saas", "company", "yc", "apply")):
        return "founders, operators, and startup-curious builders"
    if has_phrase(blob, ("ball pit",)) or has_word(blob, ("clean", "cleaned", "dirty", "drain", "sink", "mess")):
        return "viewers who enjoy satisfying reveals, cleanup tension, and surprising everyday messes"
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
    if has_word(blob, ("claude", "codex", "openclaw", "agent", "agents", "obsidian", "mcp", "workflow", "workflows")):
        return "Make AI tools feel practical, repeatable, and useful now."
    if has_word(blob, ("comedy", "comedian", "roast", "roasts", "kill", "tony", "hilarious", "impersonation")):
        return "Turn live tension into quick laughs, tags, and memorable stage moments."
    if has_word(blob, ("startup", "ai", "saas", "company", "apply")):
        return "Make big startup shifts feel legible, urgent, and actionable."
    if has_word(blob, ("dirty", "clean", "cleaned", "drain", "sink", "mess")):
        return "Turn ordinary messes into curiosity-driven cleanup payoffs."
    if keywords:
        return f"Make {', '.join(keywords[:3])} feel worth watching through a clear hook and payoff."
    return "Give the avatar a fast reason to watch, a visible payoff, and a clear next step."


def infer_meat_type(video: Dict[str, Any]) -> str:
    text = video_text(video)
    if has_word(text, ("comedy", "comedian", "roast", "roasts", "hilarious", "impersonation")) or has_phrase(text, ("kill tony",)):
        return "Story"
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
    preset_style = str(business_preset(brand).get("channel_style") or "").strip()
    if preset_style:
        return preset_style
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
    explicit = normalize_path(brand.get("primary_path") or brand.get("path"))
    if explicit:
        return explicit
    preset_path = normalize_path(business_preset(brand).get("primary_path"))
    if preset_path:
        return preset_path
    if not has_brand_context(brand):
        return "sub"
    product_mode = str(brand.get("product_mode") or "").strip().lower()
    raw_offer = str(brand.get("offer") or "")
    offer = "" if raw_offer == DEFAULT_BRAND["offer"] else raw_offer.lower()
    industry = str(brand.get("industry") or "").lower()
    if product_mode in ("true", "yes", "1", "on") or any(term in f"{offer} {industry}" for term in ("shopify", "ecommerce", "e-commerce", "dtc", "product", "cleaner", "device", "tool", "bottle")):
        return "click"
    blob = " ".join(video_text(video) for video in top)
    title_blob = " ".join(str(video.get("title") or "") for video in top).lower()
    if has_word(title_blob, ("apply", "application", "applications")):
        return "apply"
    if has_word(blob, ("checkout", "buy", "code", "shop")):
        return "buy"
    if has_phrase(blob, ("link in", "watch full")) or has_word(blob, ("description", "download")):
        return "click"
    if has_phrase(blob, ("dm me", "message me")) or has_word(blob, ("comment",)):
        return "opt_in"
    return "sub"


def is_product_mode(brand: Dict[str, Any], primary_path: str, channel_style: str) -> bool:
    explicit = boolish(brand.get("product_mode"))
    if explicit is not None:
        return explicit
    preset = business_preset(brand)
    if preset.get("product_mode"):
        return True
    raw_offer = str(brand.get("offer") or "")
    offer = "" if raw_offer == DEFAULT_BRAND["offer"] else raw_offer.lower()
    industry = str(brand.get("industry") or "").lower()
    if primary_path in ("click", "buy") or channel_style == "product_led":
        return True
    return any(term in f"{offer} {industry}" for term in ("shopify", "ecommerce", "e-commerce", "dtc", "product", "cleaner", "device", "tool", "bottle"))


def resolve_product_label(brand: Dict[str, Any], topic: str = "general") -> str:
    name = str(brand.get("product_name") or "").strip()
    if name:
        return name
    offer = str(brand.get("offer") or "").strip()
    if offer and offer != DEFAULT_BRAND["offer"]:
        return offer
    if topic == "cleaning":
        return "the cleaner"
    return "the product"


def product_label(brand: Dict[str, Any], spine: Dict[str, Any]) -> str:
    return str(spine.get("product_label") or resolve_product_label(brand, channel_topic(spine)))


def infer_spine(top: List[Dict[str, Any]], brand: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    preset = business_preset(brand)
    preset_meats = list(preset.get("meats") or [])
    meats = preset_meats[:2] if preset_meats else dominant_meats(top)
    primary_path = infer_primary_path(top, brand)
    channel_style = infer_channel_style(top, brand)
    product_mode = is_product_mode(brand, primary_path, channel_style)
    business_type = normalize_business_type(brand.get("business_type"))
    spine = {
        "business_type": business_type or "inferred",
        "business_type_label": str(preset.get("label") or "Inferred from source/channel context"),
        "avatar": infer_avatar(top, brand),
        "promise": infer_promise(top, brand, keywords),
        "proof": ", ".join(meats),
        "meats": meats,
        "primary_path": primary_path,
        "channel_style": "product_led" if product_mode and channel_style == "face_led" and primary_path in ("click", "buy") else channel_style,
        "product_mode": product_mode,
    }
    spine["product_label"] = resolve_product_label(brand, channel_topic(spine))
    spine["product_url"] = str(brand.get("product_url") or "").strip()
    spine["discount_code"] = str(brand.get("discount_code") or "").strip()
    return spine


def channel_topic(spine: Dict[str, Any]) -> str:
    text = f"{spine.get('avatar', '')} {spine.get('promise', '')}".lower()
    if any(token in text for token in ("claude", "codex", "agent", "workflow", "workflows", "tools", "ai tools")):
        return "ai_tools"
    if any(token in text for token in ("comedy", "comic", "joke", "laugh", "stage", "roast", "open mic")):
        return "comedy"
    if any(token in text for token in ("startup", "founder", "saas", "ai", "funding")):
        return "startup"
    if any(token in text for token in ("mess", "clean", "cleanup", "dirty", "drain")):
        return "cleaning"
    if any(token in text for token in ("product", "tool", "buyer")):
        return "product"
    if any(token in text for token in ("game", "gaming")):
        return "gaming"
    return "general"


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


def filled_hooks_for_template(template: str, spine: Dict[str, Any], tag: str) -> List[str]:
    topic = channel_topic(spine)
    if topic == "cleaning":
        examples = {
            "Curiosity": ["How filthy is your shower drain really?", "How dirty is your kid's favorite stuffed animal?"],
            "Spectacle": ["When hair clogs the sink, try this gross pull test.", "When the drain fights back, watch what comes out."],
            "Transformation": ["I turned this crusty sink into a mirror in 20 minutes.", "I cleaned the grossest corner of this bathroom."],
            "Challenge": ["Can I clean this before the baby wakes up?", "Can I finish this room before the timer ends?"],
            "Narrative": ["I found something disgusting in a normal sink.", "This looked clean until I checked closer."],
            "Social Proof": ["Watch my family react to what came out of this drain.", "The owner did not think this would work."],
        }
    elif topic == "comedy":
        examples = {
            "Curiosity": ["What do you do that already sounds like a setup?", "Why does every open mic have this exact guy?"],
            "Spectacle": ["This crowd-work answer got weird instantly.", "One normal question turned into a full roast."],
            "Transformation": ["I turned one awkward answer into three tags.", "This boring fact became the whole bit."],
            "Challenge": ["Can I get a laugh from the worst job answer?", "Can I write five tags off one audience detail?"],
            "Narrative": ["He said one normal sentence and lost the room.", "This started like small talk and became a punchline."],
            "Social Proof": ["Watch the room react when the tag lands.", "The panel did not expect that second punchline."],
        }
    elif topic == "ai_tools":
        examples = {
            "Curiosity": ["Why does this Claude setup work so much better?", "What changes when your notes become agent memory?"],
            "Spectacle": ["This tiny markdown file 10x'd the whole workflow.", "I connected one tool and the agent got scary useful."],
            "Transformation": ["I turned scattered notes into an AI operating system.", "This workflow went from manual to agent-run fast."],
            "Challenge": ["Can I build this agent workflow in under a minute?", "Can this setup replace the annoying manual step?"],
            "Narrative": ["Most people use Claude like chat. This is the upgrade.", "I did not get agents until I tried this workflow."],
            "Social Proof": ["Watch how builders are turning notes into agents.", "Here is the setup serious AI operators keep using."],
        }
    elif topic == "startup":
        examples = {
            "Curiosity": ["Why are AI startups moving faster than SaaS?", "What does an AI-native company do differently?"],
            "Spectacle": ["OpenAI is giving YC companies a huge unfair advantage.", "This startup shift is wiping out old software moats."],
            "Transformation": ["I turned one founder lesson into a 30-second playbook.", "This is how a startup idea becomes obvious."],
            "Challenge": ["Can your startup explain its moat in one sentence?", "Can you spot the next AI-native wedge?"],
            "Narrative": ["The best founders are changing how companies think.", "Everyone is missing this startup pattern."],
            "Social Proof": ["Watch how top founders explain the same shift.", "Here is what the strongest YC companies have in common."],
        }
    elif topic == "product":
        examples = {
            "Curiosity": ["Does this tool actually solve the annoying part?", "What happens when this product gets stress-tested?"],
            "Spectacle": ["This tiny tool changed the whole result.", "I pushed this product until it failed."],
            "Transformation": ["I used this tool to fix the before state fast.", "This product turned a messy process into one step."],
            "Challenge": ["Can this product solve it in under 30 seconds?", "Can the cheap version beat the expensive one?"],
            "Narrative": ["I did not expect this product to work this well.", "This looked like a gimmick until the result."],
            "Social Proof": ["Watch a first-time user react to the result.", "The customer noticed the difference immediately."],
        }
    else:
        examples = {
            "Curiosity": ["What happens if you test this the hard way?", "How different is the result when you try this?"],
            "Spectacle": ["This simple test gets out of hand fast.", "Watch what happens when the stakes go up."],
            "Transformation": ["I turned the before state into a clear result.", "This went from messy to obvious fast."],
            "Challenge": ["Can this work before the timer ends?", "Can I get the result in one take?"],
            "Narrative": ["I did not expect this to happen.", "This started normal and got weird fast."],
            "Social Proof": ["Watch their reaction to the final result.", "They did not believe it until they saw it."],
        }
    fallback = examples.get(tag) or examples["Narrative"]
    return fallback[:2]


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
        entry["filled_hooks"] = filled_hooks_for_template(entry["template"], spine, entry["pattern_tag"])
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


def cta_variants(path: str, spine: Dict[str, Any]) -> List[Dict[str, str]]:
    topic = channel_topic(spine)
    normalized = normalize_path(path)
    product = product_label({}, spine)
    discount_code = str(spine.get("discount_code") or "").strip()
    if normalized == "sub":
        reason = {
            "cleaning": "the next gross cleaning test",
            "startup": "the next founder breakdown",
            "ai_tools": "the next AI workflow test",
            "comedy": "the next joke test",
            "product": "the next real product test",
            "gaming": "the next challenge run",
        }.get(topic, "the next test")
        return [
            {"id": "cta_sub_1", "text": f"Subscribe for {reason}."},
            {"id": "cta_sub_2", "text": "Subscribe. I am testing the next one tomorrow."},
        ]
    if normalized == "click":
        if spine.get("product_mode"):
            return [
                {"id": "cta_click_1", "text": f"Tap the link to try {product}."},
                {"id": "cta_click_2", "text": f"Use code {discount_code} at checkout today." if discount_code else f"Get {product} from the product page."},
            ]
        return [
            {"id": "cta_click_1", "text": "Tap the link for the full breakdown."},
            {"id": "cta_click_2", "text": "Link is in the description if you want the next step."},
        ]
    if normalized == "opt_in":
        return [
            {"id": "cta_optin_1", "text": "Comment SIGNAL and I will send the checklist."},
            {"id": "cta_optin_2", "text": "Comment TEST if you want the template."},
        ]
    if normalized == "buy":
        if spine.get("product_mode"):
            return [
                {"id": "cta_buy_1", "text": f"Use code {discount_code} to try {product} today." if discount_code else f"Buy {product} from the product page."},
                {"id": "cta_buy_2", "text": f"Try {product} while this test is fresh."},
            ]
        return [
            {"id": "cta_buy_1", "text": "Use code SIGNAL if you want to try it."},
            {"id": "cta_buy_2", "text": "Grab it today while the test is fresh."},
        ]
    if normalized == "apply":
        return [
            {"id": "cta_apply_1", "text": "Apply when you are ready."},
            {"id": "cta_apply_2", "text": "Application link is in the description."},
        ]
    if normalized == "book_call":
        return [
            {"id": "cta_book_call_1", "text": "Book the walkthrough if this solves your bottleneck."},
            {"id": "cta_book_call_2", "text": "Grab a quick call from the link."},
        ]
    return [{"id": "cta_default_1", "text": "Follow for the next test."}]


def cta_by_id(ctas: List[Dict[str, str]]) -> Dict[str, str]:
    return {cta["id"]: cta["text"] for cta in ctas}


def style_adjustment(channel_style: str) -> str:
    return {
        "face_led": "Put the creator or subject on camera early; use reaction and voiceover to carry stakes.",
        "product_led": "Open on product plus mess, hand enters frame, show application, then reveal the result.",
        "faceless": "Open on mess plus bold on-screen text, use hands/b-roll and captions; no talking head needed.",
    }.get(channel_style, "Match the channel's native framing while preserving hook, proof, payoff, CTA.")


def style_id(channel_style: str) -> str:
    return {
        "face_led": "style_face_1",
        "product_led": "style_product_1",
        "faceless": "style_faceless_1",
    }.get(channel_style, "style_custom_1")


def style_library(channel_style: str) -> Dict[str, str]:
    sid = style_id(channel_style)
    styles = {sid: style_adjustment(channel_style)}
    if sid != "style_product_1":
        styles["style_product_1"] = style_adjustment("product_led")
    if sid != "style_faceless_1":
        styles["style_faceless_1"] = style_adjustment("faceless")
    return styles


def product_demo_step(brand: Dict[str, Any], spine: Dict[str, Any]) -> str:
    product = product_label(brand, spine)
    if spine.get("product_mode"):
        return f"Show {product}, apply it to the mess, then reveal the result."
    return "Show the proof fast, then make the payoff visible."


def script_meat_line(video: Dict[str, Any], brand: Dict[str, Any], spine: Dict[str, Any]) -> str:
    if spine.get("product_mode"):
        product = product_label(brand, spine)
        if channel_topic(spine) == "cleaning":
            return f"Show {product} hitting the mess, then reveal the visible lift/wipe-away result."
        return f"Show {product} in use, then reveal the specific result."
    return f"Show the {infer_meat_type(video).lower()} proof fast, then make the payoff visible."


def conversion_tracking_note(spine: Dict[str, Any]) -> str:
    path = normalize_path(spine["primary_path"])
    if path in ("click", "buy"):
        return "Track UTM sessions, add-to-carts, purchases, conversion rate, and revenue in Shopify for each sprint row."
    if path == "opt_in":
        return "Track comments/DM requests, opt-ins, qualified replies, and downstream booked calls or sales."
    if path == "book_call":
        return "Track booking link clicks, booked calls, qualified calls, show rate, and closed revenue by sprint row."
    if path == "apply":
        return "Track application link clicks, started applications, submitted applications, and qualified applicants."
    return "Track watch time, retention, follows/subs, comments, and saves for each sprint row."


def creator_hook_line(hook_entry: Dict[str, Any], index: int = 0) -> str:
    filled = hook_entry.get("filled_hooks") or []
    if filled:
        return filled[index % len(filled)]
    return str(hook_entry.get("raw_hook") or hook_entry.get("template") or "Start with the winning hook.")


def concept_title(video: Dict[str, Any], brand: Dict[str, Any], spine: Dict[str, Any], index: int) -> str:
    subject = brand.get("industry")
    if not subject or subject == DEFAULT_BRAND["industry"]:
        subject = spine.get("promise") or "This Channel"
    pattern = hook_pattern_tag(video)
    meat = infer_meat_type(video)
    if meat == "Demonstration":
        meat = "Demo"
    return f"Concept {index}: {pattern} {meat} for {str(subject).title()}"


def build_sprint_rows(hook_library: Dict[str, List[Dict[str, Any]]], spine: Dict[str, Any], days: int = 14) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    winners = hook_library.get("winners") or []
    adjacent = hook_library.get("adjacent") or []
    ctas = cta_variants(spine["primary_path"], spine)
    sid = style_id(spine["channel_style"])
    if not winners:
        return rows
    for day in range(1, days + 1):
        if day <= 10:
            hook = winners[(day - 1) % len(winners)]
            test_type = "70% proven winner"
            hook_template_value = hook["template"]
            script_line = creator_hook_line(hook, day - 1)
            source_url = hook["source_url"]
            pattern_tag = hook["pattern_tag"]
            meat_type = hook["meat_type"]
        elif day <= 13 and adjacent:
            hook = adjacent[(day - 11) % len(adjacent)]
            test_type = "20% winner-adjacent"
            hook_template_value = hook["hook"]
            base = winners[(day - 11) % len(winners)]
            script_line = creator_hook_line(base, 1)
            source_url = hook["source_url"]
            pattern_tag = hook["pattern_tag"]
            meat_type = spine["meats"][(day - 1) % len(spine["meats"])]
        else:
            test_type = "10% new experiment"
            hook_template_value = "What if [avatar] could get [promise/payoff] under [new constraint]?"
            script_line = "What if this works better than the obvious way?"
            source_url = winners[(day - 1) % len(winners)]["source_url"]
            pattern_tag = "Challenge"
            meat_type = spine["meats"][(day - 1) % len(spine["meats"])]
        rows.append({
            "day": str(day),
            "test_type": test_type,
            "hook_template": hook_template_value,
            "script_line_0_2": script_line,
            "pattern_tag": pattern_tag,
            "meat_type": meat_type,
            "product_step": product_demo_step({}, spine),
            "style_id": sid,
            "primary_path": spine["primary_path"],
            "cta_variant_id": ctas[(day - 1) % len(ctas)]["id"],
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


def thumbnail_concept(video: Dict[str, Any], brand: Dict[str, Any], spine: Optional[Dict[str, Any]] = None) -> str:
    hook = infer_hook(video)
    subject = (spine or {}).get("promise") or brand.get("industry") or "the channel promise"
    if "transformation" in hook:
        return f"Split-frame before/after result tied to {subject}; big contrast, 3-5 word overlay, proof visible."
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
            "script_line_0_2",
            "pattern_tag",
            "meat_type",
            "product_step",
            "style_id",
            "primary_path",
            "cta_variant_id",
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
    ctas = cta_variants(spine["primary_path"], spine)
    cta_lookup = cta_by_id(ctas)
    styles = style_library(spine["channel_style"])
    lines: List[str] = []
    lines.append(f"# Attract Signal Strategy Report: {brand.get('brand_name', 'Your Brand')}")
    lines.append("")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Avatar: {spine['avatar']}")
    lines.append(f"- Promise: {spine['promise']}")
    lines.append(f"- Proof: {spine['proof']}")
    lines.append(f"- Path: {spine['primary_path']}")
    lines.append(f"- Business type: {spine['business_type_label']}")
    lines.append(f"- Product mode: {'on' if spine.get('product_mode') else 'off'}")
    if spine.get("product_mode"):
        product_source = f" ({spine['product_url']})" if spine.get("product_url") else ""
        lines.append(f"- Product: {product_label(brand, spine)}{product_source}")
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
    lines.append("- In the next 2 hours: batch-film the 14 sprint hooks below, post 1/day, log watch time plus path conversions, then feed winners back into the next scan.")
    lines.append(f"- Measurement: {conversion_tracking_note(spine)}")
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
    lines.append(f"| Business type | {md_escape(spine['business_type_label'])} | This preset supplies defaults only when `brand.yaml` leaves path/style/product mode blank. |")
    lines.append(f"| Channel style | {md_escape(spine['channel_style'])} | {md_escape(style_adjustment(spine['channel_style']))} |")
    lines.append(f"| Product mode | {'on' if spine.get('product_mode') else 'off'} | {'Feature the product in the meat: show product, application, and result.' if spine.get('product_mode') else 'Use this when the brand needs click/buy content or product-led proof.'} |")
    if spine.get("product_mode") and spine.get("product_url"):
        lines.append(f"| Product source | [{md_escape(product_label(brand, spine))}]({spine['product_url']}) | Use this source for product naming and claims; do not invent product details. |")
    lines.append("")
    lines.append("## Hook Library")
    lines.append("")
    lines.append("### Top 5 Winning Hooks")
    lines.append("")
    lines.append("| Rank | Raw hook | Template | Ready-to-read hooks | Pattern tag | Meat | Source |")
    lines.append("|---:|---|---|---|---|---|---|")
    for index, hook in enumerate(hook_library["winners"], 1):
        filled = "<br>".join(md_escape(line) for line in (hook.get("filled_hooks") or []))
        lines.append(
            f"| {index} | {md_escape(hook['raw_hook'])} | {md_escape(hook['template'])} | {filled} | "
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
    lines.append(f"- Channel style: `{spine['channel_style']}`.")
    for sid, note in styles.items():
        lines.append(f"- `{sid}`: {note}")
    lines.append(f"- Primary path: `{spine['primary_path']}`.")
    if spine.get("product_mode"):
        lines.append(f"- Product step: {product_demo_step(brand, spine)}")
    for cta in ctas:
        lines.append(f"- `{cta['id']}`: {cta['text']}")
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
            f"{md_escape(hook_template(video))} -> {md_escape(infer_meat_type(video))} -> {md_escape(ctas[0]['id'])} |"
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
        hook_entry = hook_library["winners"][index - 1] if index - 1 < len(hook_library["winners"]) else {}
        lines.append(f"### {concept_title(video, brand, spine, index)}")
        lines.append("")
        lines.append(f"- Source inspiration: {video.get('source_url')}")
        lines.append(f"- `script_line_0_2`: {creator_hook_line(hook_entry, 0)}")
        lines.append(f"- `builder_note`: Based on template `{hook_template(video)}` and pattern `{hook_pattern_tag(video)}`.")
        lines.append(f"- Pattern tag: {hook_pattern_tag(video)}")
        lines.append(f"- Meat: {infer_meat_type(video)}")
        if spine.get("product_mode"):
            lines.append(f"- Product step: {product_demo_step(brand, spine)}")
        lines.append(f"- Script beat: hook, {infer_meat_type(video).lower()} meat, payoff, then `{ctas[0]['id']}`.")
        lines.append(f"- Avoid copying: do not reuse the source creator's exact premise, wording, setting, or edit sequence.")
        lines.append("")
    lines.append("## Script Drafts")
    lines.append("")
    for index, video in enumerate(top[:3], 1):
        hook_entry = hook_library["winners"][index - 1] if index - 1 < len(hook_library["winners"]) else {}
        cta = ctas[(index - 1) % len(ctas)]
        lines.append(f"### Script {index}: {concept_title(video, brand, spine, index)}")
        lines.append("")
        lines.append(f"- `script_line_0_2`: {creator_hook_line(hook_entry, 0)}")
        lines.append(f"- `script_line_meat`: {script_meat_line(video, brand, spine)}")
        lines.append("- `script_line_payoff`: Here is the part that makes the result worth the watch.")
        lines.append(f"- `script_line_cta`: {cta['text']}")
        lines.append(f"- `builder_note`: Template `{hook_template(video)}`, pattern `{hook_pattern_tag(video)}`, meat `{infer_meat_type(video)}`, style `{style_id(spine['channel_style'])}`.")
        lines.append(f"- Source reference: {video.get('source_url')}")
        lines.append("")
    lines.append("## Shot Lists")
    lines.append("")
    lines.append("| Shot | Duration | Structure | Framing | Action | Notes |")
    lines.append("|---:|---:|---|---|---|---|")
    lines.append(f"| 1 | 0-2s | Hook | style-specific first frame | Use a winning ready-to-read hook | {style_id(spine['channel_style'])}: {style_adjustment(spine['channel_style'])} |")
    lines.append(f"| 2 | 2-8s | Meat | proof-first shot | {product_demo_step(brand, spine) if spine.get('product_mode') else 'Deliver ' + spine['meats'][0].lower() + ' evidence'} | Keep the promise visible. |")
    lines.append(f"| 3 | 8-18s | Meat | sequence cuts | Add {spine['meats'][1].lower()} support | Escalate stakes or clarity. |")
    lines.append("| 4 | 18-25s | Payoff | reveal/result frame | Show the result, lesson, or reversal | Make the value obvious without context. |")
    lines.append(f"| 5 | 25-30s | CTA | final frame | Use `{ctas[0]['id']}` or `{ctas[-1]['id']}` | Define what to do, how, when, what they get, and what happens next. |")
    lines.append("")
    lines.append("## Thumbnail Concepts")
    lines.append("")
    for index, video in enumerate(top[:5], 1):
        lines.append(f"- {index}. {thumbnail_concept(video, brand, spine)} Source: {video.get('source_url')}")
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
    lines.append("| Day | Test mix | Hook template | Script line 0-2s | Pattern tag | Meat | Product step | Style | CTA | Source |")
    lines.append("|---:|---|---|---|---|---|---|---|---|---|")
    for row in build_sprint_rows(hook_library, spine, 14):
        cta_text = cta_lookup.get(row["cta_variant_id"], row["cta_variant_id"])
        lines.append(
            f"| {row['day']} | {md_escape(row['test_type'])} | {md_escape(row['hook_template'])} | {md_escape(row['script_line_0_2'])} | "
            f"{md_escape(row['pattern_tag'])} | {md_escape(row['meat_type'])} | {md_escape(row['product_step'])} | {md_escape(row['style_id'])} | "
            f"{md_escape(row['cta_variant_id'])}: {md_escape(cta_text)} | [source]({row['source_url']}) |"
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
