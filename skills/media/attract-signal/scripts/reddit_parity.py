#!/usr/bin/env python3
"""Local-first parity services for Reddit Intelligence 2.0.

This module owns orchestration and durable workflows.  Last30Days remains the
retrieval engine and is invoked only with argument arrays and plan files.
"""
from __future__ import annotations

import csv
import base64
import hashlib
import html
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from reddit_intelligence import (
    LENS_LABELS, PURCHASE_LEVELS, SignalStore, deterministic_relevance,
    infer_purchase_intent, lens_hints, normalize_inputs, sha256_file, stable_id, text_tokens,
    topic_anchors, utc_now,
)


COMPATIBLE_LAST30DAYS = (3, 11)
COMMUNITY_ROLES = {"dedicated", "broad", "peer", "candidate", "excluded"}
OPPORTUNITY_TRANSITIONS: dict[str, set[str]] = {
    "new": {"triaged", "dismissed"}, "triaged": {"approved", "dismissed"},
    "approved": {"drafted", "dismissed"}, "drafted": {"published", "dismissed"},
    "published": set(), "dismissed": set(),
}
SEARCH_FILTERS = {
    "audience", "subreddit", "lens", "intent", "competitor", "theme", "status",
    "after", "before", "min_upvotes", "min_comments", "relevance",
}


@dataclass(frozen=True)
class Last30DaysInstall:
    root: Path
    version: str
    python: Path


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split(".")[:3])
    except ValueError:
        return ()


def _read_version(skill_md: Path) -> Optional[str]:
    for line in skill_md.read_text(encoding="utf-8", errors="replace").splitlines()[:80]:
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def resolve_last30days() -> Last30DaysInstall:
    """Resolve one canonical compatible Last30Days installation."""
    candidates: list[Path] = []
    configured = os.environ.get("LAST30DAYS_SKILL_DIR")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([
        Path.home() / ".agents/skills/last30days",
        Path.home() / ".codex/skills/last30days",
        Path.home() / ".claude/skills/last30days",
    ])
    unique: dict[Path, tuple[str, Path]] = {}
    unsupported: list[str] = []
    for candidate in candidates:
        skill_md = candidate / "SKILL.md"
        engine = candidate / "scripts/last30days.py"
        if not skill_md.exists() or not engine.exists():
            continue
        real = candidate.resolve()
        version = _read_version(skill_md)
        if not version:
            unsupported.append(f"{real} (version missing)")
            continue
        parts = _version_tuple(version)
        if parts[:2] != COMPATIBLE_LAST30DAYS:
            unsupported.append(f"{real} ({version})")
            continue
        unique[real] = (version, real)
    if not unique:
        detail = "; ".join(unsupported) or "no installations found"
        raise RuntimeError(f"No compatible Last30Days 3.11.x installation: {detail}")
    versions = {value[0] for value in unique.values()}
    if len(versions) > 1:
        highest = max(versions, key=_version_tuple)
    else:
        highest = next(iter(versions))
    roots = [root for version, root in unique.values() if version == highest]
    preferred = roots[0]
    if configured:
        configured_real = Path(configured).expanduser().resolve()
        if configured_real in roots:
            preferred = configured_real
    python = _resolve_python()
    return Last30DaysInstall(preferred, highest, python)


def _resolve_python() -> Path:
    configured = os.environ.get("LAST30DAYS_PYTHON")
    names = [configured] if configured else []
    names.extend(["python3.14", "python3.13", "python3.12"])
    for name in names:
        if not name:
            continue
        found = shutil.which(name) if not Path(name).is_absolute() else name
        if not found:
            continue
        probe = subprocess.run(
            [str(found), "-c", "import sys; raise SystemExit(sys.version_info < (3,12))"],
            capture_output=True, timeout=10,
        )
        if probe.returncode == 0:
            return Path(found).resolve()
    raise RuntimeError("Last30Days requires Python 3.12+; set LAST30DAYS_PYTHON")


def cached_doctor() -> dict[str, Any]:
    path = Path.home() / ".config/last30days/doctor-cache.json"
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unreadable", "path": str(path), "error": str(exc)}
    payload["status"] = payload.get("status", "cached")
    payload["path"] = str(path)
    return payload


def build_retrieval_plan(topic: str, audience: Optional[dict[str, Any]], deep: bool) -> dict[str, Any]:
    competitors = list((audience or {}).get("competitors", []))
    aliases = list((audience or {}).get("aliases", []))
    base = " ".join(dict.fromkeys([topic, *aliases])).strip()
    specs = [
        ("neutral", base, f"What are people saying about {topic}?", 1.0),
        ("pain", f"{base} problem frustration", f"What problems do people report with {topic}?", .95),
        ("solution", f"{base} recommendation tool", f"What solutions are people requesting for {topic}?", .9),
    ]
    if deep:
        specs.extend([
            ("money", f"{base} price cost worth", f"What are people willing to pay for around {topic}?", .9),
            ("switching", f"{base} alternative switching", f"Why are people switching solutions related to {topic}?", .95),
            ("comparison", f"{base} compare vs", f"What products are people comparing for {topic}?", .8),
        ])
        specs.extend(
            (f"competitor-{index}", f"{name} problem alternative", f"Why are users leaving or criticizing {name}?", .8)
            for index, name in enumerate(competitors[:3], 1)
        )
    return {
        "intent": "product", "freshness_mode": "balanced_recent", "cluster_mode": "debate",
        "source_weights": {"reddit": 1.0},
        "subqueries": [{
            "label": label, "search_query": query, "ranking_query": ranking,
            "sources": ["reddit"], "weight": weight,
        } for label, query, ranking, weight in specs[:9]],
        "notes": ["Attract Signal scout/deep Reddit retrieval plan"],
    }


def _lease(store: SignalStore, audience_id: str, ttl_minutes: int = 30) -> str:
    now = datetime.now(timezone.utc)
    owner = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    with store.connection:
        store.connection.execute("DELETE FROM retrieval_leases WHERE expires_at<=?", (now.isoformat(),))
        try:
            store.connection.execute(
                "INSERT INTO retrieval_leases(audience_id,owner,acquired_at,expires_at) VALUES (?,?,?,?)",
                (audience_id, owner, now.isoformat(), (now + timedelta(minutes=ttl_minutes)).isoformat()),
            )
        except Exception as exc:
            raise RuntimeError(f"A refresh is already running for audience {audience_id}") from exc
    return owner


def release_lease(store: SignalStore, audience_id: str, owner: str) -> None:
    with store.connection:
        store.connection.execute(
            "DELETE FROM retrieval_leases WHERE audience_id=? AND owner=?", (audience_id, owner),
        )


def _window_ends(backfill_days: int, as_of: date) -> list[tuple[int, date]]:
    result = []
    remaining = max(1, backfill_days)
    end = as_of
    while remaining > 0:
        span = min(30, remaining)
        result.append((span, end))
        remaining -= span
        end -= timedelta(days=span)
    return result


def _scout_ready(path: Path, topic: str, audience: Optional[dict[str, Any]]) -> bool:
    records, _ = normalize_inputs([path])
    aliases = list((audience or {}).get("aliases", []))
    dedicated = set((audience or {}).get("dedicated_subreddits", []))
    relevant = [
        row for row in records
        if deterministic_relevance(row, topic, aliases, dedicated, [])[0] >= .72
    ]
    communities = {row["subreddit"].lower() for row in relevant}
    comments = sum(row["comment_count"] for row in relevant)
    return len(relevant) >= 8 and comments >= 20 and (len(communities) >= 3 or len(relevant) >= 8)


def retrieve_reddit(
    *, store: SignalStore, topic: str, audience_id: Optional[str], days: int,
    backend: str, output_dir: Path, backfill_days: int = 0,
    allow_paid_backfill: bool = False, overlap_hours: int = 0,
) -> dict[str, Any]:
    install = resolve_last30days()
    audience = store.get_audience(audience_id) if audience_id else None
    if audience_id and not audience:
        raise ValueError(f"Saved audience not found: {audience_id}")
    if backend == "scrapecreators" and not os.environ.get("SCRAPECREATORS_API_KEY"):
        raise RuntimeError("ScrapeCreators requested but SCRAPECREATORS_API_KEY is not configured")
    if backfill_days > days and backend == "scrapecreators" and not allow_paid_backfill:
        raise RuntimeError("Paid historical backfill requires --allow-paid-backfill")
    effective_backend = backend
    if backfill_days > days and backend == "auto" and not allow_paid_backfill:
        effective_backend = "public"
    doctor = cached_doctor()
    output_dir.mkdir(parents=True, exist_ok=True)
    windows = _window_ends(backfill_days or days, date.today())
    artifacts: list[Path] = []
    receipts: list[dict[str, Any]] = []
    phases = [("scout", False), ("deep", True)]
    for window_index, (window_days, as_of) in enumerate(windows):
        for phase, deep in phases:
            if phase == "deep" and window_index > 0:
                continue
            plan = build_retrieval_plan(topic, audience, deep)
            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
                json.dump(plan, handle, ensure_ascii=False)
                plan_path = Path(handle.name)
            artifact = output_dir / f"last30days-{window_index:02d}-{phase}.json"
            command = [
                str(install.python), str(install.root / "scripts/last30days.py"), topic,
                "--emit=json", "--search=reddit", "--plan", str(plan_path),
                "--days", str(window_days), "--as-of", as_of.isoformat(),
            ]
            subreddits = list((audience or {}).get("subreddits", []))
            dedicated = list((audience or {}).get("dedicated_subreddits", []))
            if subreddits:
                command.extend(["--subreddits", ",".join(subreddits)])
            if dedicated:
                command.extend(["--dedicated-subreddits", ",".join(dedicated)])
            if deep:
                command.append("--deep")
            env = os.environ.copy()
            if effective_backend != "auto":
                env["LAST30DAYS_REDDIT_BACKEND"] = effective_backend
            job_id = stable_id("retrieval", audience_id or topic, as_of.isoformat(), phase, effective_backend)
            started = utc_now()
            receipt: dict[str, Any]
            with store.connection:
                store.connection.execute(
                    """INSERT OR REPLACE INTO retrieval_jobs(
                    id,audience_id,phase,backend,window_from,window_to,status,command_json,receipt_json,started_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (job_id, audience_id, phase, effective_backend,
                     (as_of - timedelta(days=window_days)).isoformat(), as_of.isoformat(), "running",
                     json.dumps(command), json.dumps({"doctor": doctor}), started),
                )
            try:
                completed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=600)
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or "Last30Days retrieval failed")
                payload = json.loads(completed.stdout)
                artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                count = len((payload.get("items_by_source") or {}).get("reddit", []))
                historical = as_of < date.today() or window_days > 30
                status = ("best_effort" if historical and effective_backend == "public" else "verified") if count else "partial"
                receipt = {"status": status, "items": count, "stderr": completed.stderr[-4000:]}
                artifacts.append(artifact)
            except Exception as exc:
                status = "failed"
                receipt = {"status": status, "error": str(exc)}
                if phase == "scout" and not artifacts:
                    raise
            finally:
                plan_path.unlink(missing_ok=True)
                with store.connection:
                    store.connection.execute(
                        "UPDATE retrieval_jobs SET status=?,receipt_json=?,completed_at=? WHERE id=?",
                        (status, json.dumps(receipt), utc_now(), job_id),
                    )
            if status != "failed":
                checksum = sha256_file(artifact)
                with store.connection:
                    store.connection.execute(
                        """INSERT OR IGNORE INTO source_artifacts(
                        id,retrieval_job_id,path,sha256,backend,window_status,created_at
                        ) VALUES (?,?,?,?,?,?,?)""",
                        (stable_id("artifact", checksum, effective_backend), job_id, str(artifact), checksum, effective_backend, status, utc_now()),
                    )
                receipts.append({"job_id": job_id, "phase": phase, "window": as_of.isoformat(), **receipt})
            if phase == "scout" and status != "failed" and _scout_ready(artifact, topic, audience):
                break
    return {
        "artifacts": artifacts, "receipts": receipts, "version": install.version,
        "skill_dir": str(install.root), "doctor": doctor, "overlap_hours": overlap_hours,
    }


def classify_comments(store: SignalStore, run: dict[str, Any]) -> int:
    """Promote captured comments to searchable, classified evidence."""
    topic = run["topic"]
    aliases: list[str] = []
    audience_id = run.get("audience_id")
    audience = store.get_audience(str(audience_id)) if audience_id else None
    if audience:
        aliases = audience.get("aliases", [])
    stored = 0
    with store.connection:
        for thread in run["threads"]:
            for comment in thread.get("comments", []):
                pseudo = {
                    "title": thread["title"], "body": comment["body"], "subreddit": thread["subreddit"],
                    "canonical_url": comment.get("source_url") or thread["canonical_url"],
                    "published_at": comment.get("published_at"), "upvotes": comment.get("upvotes", 0),
                    "comment_count": 0,
                }
                score, _ = deterministic_relevance(pseudo, topic, aliases, set(), [])
                label = "relevant" if score >= .72 else "uncertain" if score >= .45 else "irrelevant"
                lenses, _ = lens_hints(pseudo, float("inf")) if label == "relevant" else ([], {})
                intent = infer_purchase_intent(comment["body"], lenses) if label == "relevant" else "none"
                quote = comment["body"][:320]
                store.connection.execute(
                    """INSERT OR REPLACE INTO comment_classifications(
                    run_id,comment_id,relevance_label,relevance_score,lenses_json,purchase_intent,
                    exact_quote,sentiment,competitors_json,model_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (run["run_id"], comment["id"], label, score, json.dumps(lenses), intent, quote,
                     "negative" if "pain_points" in lenses else "neutral", "[]", None),
                )
                try:
                    store.connection.execute("DELETE FROM comments_fts WHERE comment_id=?", (comment["id"],))
                    store.connection.execute(
                        "INSERT INTO comments_fts(comment_id,thread_id,body,subreddit) VALUES (?,?,?,?)",
                        (comment["id"], thread["id"], comment["body"], thread["subreddit"]),
                    )
                except Exception:
                    pass
                stored += 1
    return stored


def update_communities(store: SignalStore, run: dict[str, Any]) -> list[dict[str, Any]]:
    audience_id = run.get("audience_id")
    all_rows = run["threads"] + run.get("excluded_threads", [])
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    relevant_ids = {row["id"] for row in run["threads"]}
    for row in all_rows:
        by_name[row["subreddit"]].append(row)
    result = []
    now = utc_now()
    with store.connection:
        for name, rows in by_name.items():
            community_id = stable_id("community", name.lower())
            relevant = [row for row in rows if row["id"] in relevant_ids]
            concentration = len(relevant) / max(1, len(rows))
            engagement = sum(row["upvotes"] + row["comment_count"] for row in relevant)
            confidence = round(min(1.0, .35 + .1 * len(rows)), 2)
            store.connection.execute(
                """INSERT INTO communities(id,name,source,created_at,updated_at) VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at""",
                (community_id, name, "observed", now, now),
            )
            store.connection.execute(
                """INSERT OR REPLACE INTO community_snapshots(
                id,community_id,audience_id,run_id,relevant_threads,total_threads,engagement,
                topical_concentration,coverage_confidence,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (stable_id("community_snapshot", community_id, run["run_id"]), community_id, audience_id,
                 run["run_id"], len(relevant), len(rows), engagement, concentration, confidence, now),
            )
            role = "dedicated" if concentration >= .8 and len(relevant) >= 2 else "candidate"
            growth: Optional[float] = None
            if audience_id:
                prior = store.connection.execute(
                    """SELECT relevant_threads,captured_at FROM community_snapshots
                    WHERE community_id=? AND audience_id=? AND run_id<>? ORDER BY captured_at DESC LIMIT 1""",
                    (community_id, audience_id, run["run_id"]),
                ).fetchone()
                if prior and datetime.fromisoformat(now) - datetime.fromisoformat(prior["captured_at"]) >= timedelta(days=7):
                    growth = (len(relevant) - prior["relevant_threads"]) / max(1, prior["relevant_threads"])
                store.connection.execute(
                    """INSERT INTO audience_communities(
                    audience_id,community_id,role,relevance,activity,growth,topical_concentration,
                    coverage_confidence,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(audience_id,community_id) DO UPDATE SET role=excluded.role,
                    relevance=excluded.relevance,activity=excluded.activity,growth=excluded.growth,
                    topical_concentration=excluded.topical_concentration,
                    coverage_confidence=excluded.coverage_confidence,last_seen_at=excluded.last_seen_at""",
                    (audience_id, community_id, role, concentration, float(len(relevant)), growth,
                     concentration, confidence, now, now),
                )
            result.append({
                "id": community_id, "name": name, "role": role, "relevant_threads": len(relevant),
                "total_threads": len(rows), "engagement": engagement, "topical_concentration": concentration,
                "coverage_confidence": confidence, "growth": growth,
                "growing": growth is not None and growth > 0,
                "breakout": growth is not None and growth >= 1 and len(relevant) >= 3,
            })
    return sorted(result, key=lambda row: (row["relevant_threads"], row["engagement"]), reverse=True)


def sync_opportunities(store: SignalStore, run: dict[str, Any]) -> int:
    now = utc_now()
    count = 0
    with store.connection:
        for item in run.get("content_opportunities", []):
            lenses = set()
            for row in run["threads"]:
                if row["id"] in item["evidence_ids"]:
                    lenses.update(row.get("lenses", []))
            trigger = (
                "active_switching" if "seeking_alternatives" in lenses else
                "money_signal" if "money_talk" in lenses else
                "solvable_pain" if "pain_points" in lenses else "emerging_theme"
            )
            priority = round(float(item["confidence"]) * 100)
            store.connection.execute(
                """INSERT INTO opportunities(
                id,audience_id,theme_id,trigger_type,status,priority,confidence,title,content_job,
                hook_direction,proof_type,cta,evidence_ids_json,source_urls_json,guidance,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET priority=excluded.priority,confidence=excluded.confidence,
                title=excluded.title,hook_direction=excluded.hook_direction,proof_type=excluded.proof_type,
                cta=excluded.cta,evidence_ids_json=excluded.evidence_ids_json,
                source_urls_json=excluded.source_urls_json,updated_at=excluded.updated_at""",
                (item["id"], run.get("audience_id"), item.get("theme_id"), trigger, "new", priority,
                 item["confidence"], item["working_title"], item["content_job"], item["hook_direction"],
                 item["proof_type"], item["cta"], json.dumps(item["evidence_ids"]),
                 json.dumps(item["source_urls"]), None, now, now),
            )
            store.connection.execute(
                """INSERT OR IGNORE INTO opportunity_events(id,opportunity_id,to_status,created_at)
                VALUES (?,?,?,?)""", (stable_id("opportunity_event", item["id"], "new"), item["id"], "new", now),
            )
            count += 1
        records = {row["id"]: row for row in run["threads"]}
        for theme in run.get("themes", []):
            members = [records[item] for item in theme["supporting_thread_ids"] if item in records]
            sentiment = Counter(row.get("sentiment", "neutral") for row in members)
            intent = Counter(row.get("purchase_intent", "none") for row in members)
            competitors = Counter(name for row in members for name in row.get("competitors", []))
            store.connection.execute(
                """INSERT OR REPLACE INTO theme_snapshots(
                id,theme_id,audience_id,run_id,thread_count,engagement,sentiment_json,intent_json,
                competitor_json,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (stable_id("theme_snapshot", theme["id"], run["run_id"]), theme["id"], run.get("audience_id"),
                 run["run_id"], theme["thread_count"], theme["engagement"], json.dumps(sentiment),
                 json.dumps(intent), json.dumps(competitors), now),
            )
    return count


def postprocess_run(store: SignalStore, run: dict[str, Any]) -> dict[str, Any]:
    comments = classify_comments(store, run)
    communities = update_communities(store, run)
    opportunities = sync_opportunities(store, run)
    run["communities"] = communities
    run["metrics"]["classified_comments"] = comments
    run["metrics"]["durable_opportunities"] = opportunities
    return run


def parse_search(query: str) -> tuple[list[str], dict[str, list[str]]]:
    terms: list[str] = []
    filters: dict[str, list[str]] = defaultdict(list)
    for token in shlex.split(query):
        if ":" in token:
            key, value = token.split(":", 1)
            if key in SEARCH_FILTERS:
                if not value:
                    raise ValueError(f"Empty search filter: {key}")
                filters[key].append(value)
                continue
            if key.replace("_", "").isalnum():
                raise ValueError(f"Unsupported search filter: {key}")
        terms.append(token)
    return terms, dict(filters)


def run_search(store: SignalStore, query: str, limit: int = 100) -> list[dict[str, Any]]:
    terms, filters = parse_search(query)
    clauses = ["1=1"]
    params: list[Any] = []
    if terms:
        fts = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        clauses.append("t.id IN (SELECT thread_id FROM threads_fts WHERE threads_fts MATCH ?)")
        params.append(fts)
    mapping = {
        "audience": ("r.audience_id", "="), "subreddit": ("t.subreddit", "="),
        "intent": ("c.purchase_intent", "="), "after": ("t.published_at", ">="),
        "before": ("t.published_at", "<="), "min_upvotes": ("t.upvotes", ">="),
        "min_comments": ("t.comment_count", ">="), "relevance": ("c.relevance_score", ">="),
    }
    for key, values in filters.items():
        if key in mapping:
            column, operator = mapping[key]
            for raw_value in values:
                value: Any = raw_value
                if key in {"min_upvotes", "min_comments"}:
                    value = int(value)
                elif key == "relevance":
                    value = float(value)
                clauses.append(f"{column}{operator}?")
                params.append(value)
        elif key == "lens":
            clauses.append("EXISTS (SELECT 1 FROM json_each(c.lenses_json) WHERE value=?)")
            params.extend(values[:1])
        elif key == "competitor":
            clauses.append("EXISTS (SELECT 1 FROM json_each(c.competitors_json) WHERE lower(value)=lower(?))")
            params.extend(values[:1])
        elif key == "theme":
            clauses.append("EXISTS (SELECT 1 FROM theme_memberships tm WHERE tm.thread_id=t.id AND tm.theme_id=?)")
            params.extend(values[:1])
        elif key == "status":
            clauses.append("EXISTS (SELECT 1 FROM opportunities o WHERE o.status=? AND o.evidence_ids_json LIKE '%'||t.id||'%')")
            params.extend(values[:1])
    sql = f"""SELECT t.*,c.relevance_label,c.relevance_score,c.lenses_json,c.purchase_intent,
    c.competitors_json,r.audience_id,r.id AS run_id FROM threads t
    JOIN classifications c ON c.thread_id=t.id JOIN runs r ON r.id=c.run_id
    WHERE {' AND '.join(clauses)} ORDER BY t.last_seen_at DESC,t.comment_count DESC LIMIT ?"""
    params.append(min(max(limit, 1), 1000))
    rows = store.connection.execute(sql, params).fetchall()
    seen = set()
    result = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        payload = dict(row)
        payload["lenses"] = json.loads(payload.pop("lenses_json"))
        payload["competitors"] = json.loads(payload.pop("competitors_json"))
        payload["provenance"] = json.loads(payload.pop("provenance_json"))
        result.append(payload)
    return result


def save_search(store: SignalStore, name: str, query: str, audience_id: Optional[str]) -> dict[str, Any]:
    parse_search(query)
    search_id = stable_id("search", audience_id, name)
    now = utc_now()
    with store.connection:
        store.connection.execute(
            """INSERT INTO saved_searches(id,name,audience_id,query,created_at,updated_at) VALUES (?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET query=excluded.query,updated_at=excluded.updated_at""",
            (search_id, name, audience_id, query, now, now),
        )
    return dict(store.connection.execute("SELECT * FROM saved_searches WHERE id=?", (search_id,)).fetchone())


def list_saved_searches(store: SignalStore) -> list[dict[str, Any]]:
    return [dict(row) for row in store.connection.execute("SELECT * FROM saved_searches ORDER BY updated_at DESC")]


def list_communities(store: SignalStore, audience_id: Optional[str] = None) -> list[dict[str, Any]]:
    if audience_id:
        rows = store.connection.execute(
            """SELECT c.*,ac.role,ac.relevance,ac.activity,ac.growth,ac.topical_concentration,
            ac.coverage_confidence,ac.first_seen_at,ac.last_seen_at FROM communities c
            JOIN audience_communities ac ON ac.community_id=c.id WHERE ac.audience_id=?
            ORDER BY ac.relevance DESC,ac.activity DESC""", (audience_id,),
        ).fetchall()
    else:
        rows = store.connection.execute("SELECT * FROM communities ORDER BY updated_at DESC").fetchall()
    return [dict(row) for row in rows]


def list_opportunities(store: SignalStore, status: Optional[str] = None) -> list[dict[str, Any]]:
    if status:
        rows = store.connection.execute(
            "SELECT * FROM opportunities WHERE status=? ORDER BY priority DESC,updated_at DESC", (status,),
        ).fetchall()
    else:
        rows = store.connection.execute("SELECT * FROM opportunities ORDER BY priority DESC,updated_at DESC").fetchall()
    result = []
    for row in rows:
        payload = dict(row)
        payload["evidence_ids"] = json.loads(payload.pop("evidence_ids_json"))
        payload["source_urls"] = json.loads(payload.pop("source_urls_json"))
        result.append(payload)
    return result


def update_opportunity(store: SignalStore, opportunity_id: str, status: str, note: Optional[str]) -> dict[str, Any]:
    row = store.connection.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    if not row:
        raise ValueError(f"Opportunity not found: {opportunity_id}")
    current = str(row["status"])
    if status not in OPPORTUNITY_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid opportunity transition: {current} -> {status}")
    now = utc_now()
    with store.connection:
        store.connection.execute(
            "UPDATE opportunities SET status=?,notes=COALESCE(?,notes),updated_at=? WHERE id=?",
            (status, note, now, opportunity_id),
        )
        store.connection.execute(
            "INSERT INTO opportunity_events(id,opportunity_id,from_status,to_status,note,created_at) VALUES (?,?,?,?,?,?)",
            (stable_id("opportunity_event", opportunity_id, current, status, now), opportunity_id, current, status, note, now),
        )
    return next(item for item in list_opportunities(store, status) if item["id"] == opportunity_id)


def export_opportunities(store: SignalStore, path: Path, status: Optional[str] = None) -> int:
    rows = list_opportunities(store, status)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "id", "status", "priority", "trigger_type", "title", "content_job", "hook_direction",
            "proof_type", "cta", "source_urls", "notes",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: " ".join(row[key]) if key == "source_urls" else row.get(key) for key in writer.fieldnames})
    return len(rows)


def sample_evaluation(store: SignalStore, path: Path, count: int = 300) -> int:
    """Create a stratified labeling queue; it is not gold until human-reviewed."""
    rows = store.connection.execute(
        """SELECT t.id,r.topic,t.title,t.body,t.canonical_url,t.subreddit,t.published_at,t.upvotes,t.comment_count,
        c.relevance_label AS suggested_relevance,c.lenses_json AS suggested_lenses,
        c.purchase_intent AS suggested_intent FROM threads t JOIN classifications c ON c.thread_id=t.id
        JOIN runs r ON r.id=c.run_id
        GROUP BY t.id ORDER BY (t.upvotes+t.comment_count) DESC LIMIT ?""", (max(count * 4, count),),
    ).fetchall()
    buckets: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        lenses = json.loads(row["suggested_lenses"] or "[]")
        bucket = f"{row['suggested_relevance']}|{row['subreddit']}|{lenses[0] if lenses else 'none'}"
        buckets[bucket].append(row)
    selected: list[Any] = []
    while len(selected) < count and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(selected) < count:
                selected.append(buckets[key].pop(0))
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "topic", "title", "body", "canonical_url", "subreddit", "published_at", "upvotes", "comment_count",
              "suggested_relevance", "suggested_lenses", "suggested_intent",
              "gold_relevance", "gold_lenses", "gold_intent", "reviewer", "reviewed_at"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            writer.writerow({**dict(row), "gold_relevance": "", "gold_lenses": "", "gold_intent": "", "reviewer": "", "reviewed_at": ""})
    render_labeling_dashboard(path, path.with_suffix(".html"))
    return len(selected)


def render_labeling_dashboard(csv_path: Path, output_path: Path) -> None:
    """Create an offline human-labeling surface; suggestions remain visibly non-gold."""
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    style = """body{font:15px/1.45 system-ui;margin:0;background:#0b0d12;color:#f7f8fb}header,main{max-width:1500px;margin:auto;padding:22px}h1{margin-bottom:4px}.note{color:#ffcf70}table{border-collapse:collapse;width:100%;background:#131722}th,td{border:1px solid #303748;padding:8px;vertical-align:top}th{position:sticky;top:0;background:#1c2230}input,select{background:#090c12;color:#fff;border:1px solid #46506a;padding:7px;width:100%}a{color:#75e0c0}.source{max-width:420px}.suggestion{color:#a8b2c5}button{padding:10px 14px;margin:12px 0} @media(max-width:900px){table{font-size:12px}}"""
    script = """const rows=[...document.querySelectorAll('tbody tr')];document.querySelector('#export').onclick=()=>{const q=s=>'"'+String(s??'').replaceAll('"','""')+'"';const head=['id','gold_relevance','gold_lenses','gold_intent','reviewer','reviewed_at'];const out=[head.join(',')];for(const r of rows){out.push([r.dataset.id,...[...r.querySelectorAll('input,select')].map(x=>x.value)].map(q).join(','))}const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([out.join('\\n')],{type:'text/csv'}));a.download='reddit-human-labels.csv';a.click()};"""
    csp = (
        "default-src 'none'; base-uri 'none'; object-src 'none'; form-action 'none'; "
        f"style-src 'sha256-{base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()}'; "
        f"script-src 'sha256-{base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()}'; connect-src 'none'"
    )
    body = []
    for row in rows:
        esc = lambda value: html.escape(str(value or ""), quote=True)
        body.append(
            f'<tr data-id="{esc(row["id"])}"><td class="source"><a href="{esc(row["canonical_url"])}">{esc(row["title"])}</a>'
            f'<p>{esc(row["body"][:500])}</p><small>r/{esc(row["subreddit"])} · {esc(row["upvotes"])} votes</small></td>'
            f'<td class="suggestion">{esc(row["suggested_relevance"])}<br>{esc(row["suggested_lenses"])}<br>{esc(row["suggested_intent"])}</td>'
            '<td><select><option value=""></option><option>relevant</option><option>irrelevant</option></select></td>'
            '<td><input aria-label="Gold lenses" placeholder="pain_points,money_talk"></td>'
            '<td><select><option value=""></option>' + ''.join(f'<option>{item}</option>' for item in PURCHASE_LEVELS) + '</select></td>'
            '<td><input aria-label="Reviewer"></td><td><input aria-label="Reviewed at" placeholder="YYYY-MM-DD"></td></tr>'
        )
    output_path.write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{html.escape(csp, quote=True)}"><title>Reddit gold labeling</title><style>{style}</style></head>'
        f'<body><header><h1>Reddit evaluation labeling</h1><p class="note">Model suggestions are hints only. A named human reviewer and date are required for gold status.</p>'
        f'<button id="export">Export human labels</button></header><main><table><thead><tr><th>Evidence</th><th>Suggestion</th><th>Gold relevance</th><th>Gold lenses</th><th>Gold intent</th><th>Reviewer</th><th>Date</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></main><script>{script}</script></body></html>', encoding="utf-8",
    )


def validate_gold(path: Path) -> dict[str, Any]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    reviewed = [row for row in rows if row.get("reviewer") and row.get("reviewed_at") and row.get("gold_relevance")]
    return {"rows": len(rows), "human_reviewed": len(reviewed), "ready": len(reviewed) >= 300}
