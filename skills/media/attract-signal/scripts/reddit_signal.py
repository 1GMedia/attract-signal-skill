#!/usr/bin/env python3
"""CLI for Attract Signal Reddit Intelligence v2."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import subprocess
import sys
import webbrowser
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from reddit_intelligence import (
    OpenAIRouter, SignalStore, default_home, doctor, normalize_inputs, render_dashboard,
    run_research, slugify, write_artifacts,
)
from reddit_parity import (
    export_opportunities, list_communities, list_opportunities, list_saved_searches,
    postprocess_run, release_lease, resolve_last30days, retrieve_reddit, run_search,
    sample_evaluation, save_search, update_opportunity, validate_gold, _lease,
)


def split_csv(value: Optional[str]) -> list[str]:
    return [item.strip().removeprefix("r/") for item in (value or "").split(",") if item.strip()]


def json_output(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def expand_inputs(values: list[str]) -> list[Path]:
    result: list[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if any(character in value for character in "*?["):
            matches = sorted(path.parent.glob(path.name), key=lambda item: item.stat().st_mtime, reverse=True)
            result.extend(matches[:1])
        else:
            result.append(path)
    return result


def normalize_input_pattern(value: str) -> str:
    expanded = str(Path(value).expanduser())
    if any(character in expanded for character in "*?["):
        path = Path(expanded)
        return str(path.parent.resolve() / path.name)
    return str(Path(expanded).resolve())


def research_command(args: argparse.Namespace, store: SignalStore) -> int:
    output_dir = args.out_dir or (
        default_home() / "reports" / (args.audience_id or slugify(args.topic)) /
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    inputs = expand_inputs(args.input or [])
    retrieval = None
    if not inputs or args.refresh:
        retrieval = retrieve_reddit(
            store=store, topic=args.topic, audience_id=args.audience_id, days=args.days,
            backend=args.reddit_backend, output_dir=output_dir / "sources",
            backfill_days=args.backfill_days or args.days,
            allow_paid_backfill=args.allow_paid_backfill,
        )
        inputs.extend(retrieval["artifacts"])
    run = run_research(
        topic=args.topic, inputs=inputs, audience_id=args.audience_id,
        brand_path=args.brand, days=args.days, quality=args.quality, output_dir=output_dir,
        store=store, aliases=split_csv(args.aliases), dedicated_subreddits=split_csv(args.dedicated_subreddits),
        negative_anchors=split_csv(args.negative_anchors),
    )
    if retrieval:
        run["retrieval_receipts"] = retrieval["receipts"]
        run["backend_health"]["live_retrieval"] = {
            "skill_dir": retrieval["skill_dir"], "version": retrieval["version"],
            "receipts": retrieval["receipts"],
        }
        with store.connection:
            store.connection.executemany(
                "UPDATE retrieval_jobs SET run_id=? WHERE id=?",
                ((run["run_id"], receipt["job_id"]) for receipt in retrieval["receipts"]),
            )
    postprocess_run(store, run)
    write_artifacts(run, output_dir, store)
    summary = {
        "run_id": run["run_id"], "corpus_status": run["corpus_status"], "metrics": run["metrics"],
        "model_ids": run["model_ids"], "backend_health": run["backend_health"],
        "alerts": run["alerts"], "artifacts": {
            "json": str(output_dir / "reddit-intelligence.json"),
            "markdown": str(output_dir / "reddit-intelligence.md"),
            "dashboard": str(output_dir / "dashboard.html"),
            "threads_csv": str(output_dir / "reddit-conversations.csv"),
            "opportunities_csv": str(output_dir / "content-opportunities.csv"),
            "sprint_csv": str(output_dir / "content-sprint.csv"),
            "query_plan": str(output_dir / "query-plan.json"),
        },
    }
    json_output(summary)
    return 0


def audience_command(args: argparse.Namespace, store: SignalStore) -> int:
    if args.audience_action == "save":
        current = store.get_audience(args.id) or {}
        payload = {
            "id": args.id, "topic": args.topic or current.get("topic"),
            "aliases": split_csv(args.aliases) if args.aliases is not None else current.get("aliases", []),
            "audience": args.audience if args.audience is not None else current.get("audience"),
            "competitors": split_csv(args.competitors) if args.competitors is not None else current.get("competitors", []),
            "dedicated_subreddits": split_csv(args.dedicated_subreddits) if args.dedicated_subreddits is not None else current.get("dedicated_subreddits", []),
            "subreddits": split_csv(args.subreddits) if args.subreddits is not None else current.get("subreddits", []),
            "window_days": args.days if args.days is not None else current.get("window_days", 30),
            "cadence_hours": args.cadence_hours if args.cadence_hours is not None else current.get("cadence_hours", 168),
            "input_paths": [normalize_input_pattern(item) for item in args.input] if args.input is not None else current.get("input_paths", []),
            "alert_rules": current.get("alert_rules", {}), "brand": current.get("brand", {}),
            "enabled": not args.disabled,
        }
        if not payload["topic"]:
            raise ValueError("--topic is required when creating a new audience")
        json_output(store.save_audience(payload))
        return 0
    if args.audience_action == "list":
        json_output(store.list_audiences())
        return 0
    if args.audience_action == "show":
        audience = store.get_audience(args.id)
        if not audience:
            raise ValueError(f"Saved audience not found: {args.id}")
        json_output(audience)
        return 0
    if args.audience_action == "delete":
        json_output({"id": args.id, "deleted": store.delete_audience(args.id)})
        return 0
    return 2


def alert_command(args: argparse.Namespace, store: SignalStore) -> int:
    if args.alert_action == "list":
        json_output(store.list_alerts(args.audience_id, args.pending))
        return 0
    json_output({"id": args.id, "acknowledged": store.acknowledge_alert(args.id)})
    return 0


def run_due(store: SignalStore, quality: str) -> dict[str, Any]:
    results = []
    for audience in store.due_audiences():
        try:
            output_dir = default_home() / "reports" / audience["id"] / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            owner = _lease(store, audience["id"])
            try:
                retrieval = retrieve_reddit(
                    store=store, topic=audience["topic"], audience_id=audience["id"],
                    days=audience["window_days"], backend="auto", output_dir=output_dir / "sources",
                    backfill_days=audience["window_days"], overlap_hours=48,
                )
                paths = retrieval["artifacts"]
                records, _ = normalize_inputs(paths)
                changed = False
                for record in records:
                    current = store.connection.execute(
                        "SELECT upvotes,comment_count FROM threads WHERE id=?", (record["id"],),
                    ).fetchone()
                    if not current or record["upvotes"] > current["upvotes"] or record["comment_count"] > current["comment_count"]:
                        changed = True
                        break
                if not changed:
                    results.append({"audience_id": audience["id"], "status": "unchanged", "retrieval_receipts": retrieval["receipts"]})
                    continue
                run = run_research(
                    topic=audience["topic"], inputs=paths, audience_id=audience["id"], brand_path=None,
                    days=audience["window_days"], quality=quality, output_dir=output_dir, store=store,
                )
                run["retrieval_receipts"] = retrieval["receipts"]
                with store.connection:
                    store.connection.executemany(
                        "UPDATE retrieval_jobs SET run_id=? WHERE id=?",
                        ((run["run_id"], receipt["job_id"]) for receipt in retrieval["receipts"] if receipt.get("job_id")),
                    )
                postprocess_run(store, run)
                write_artifacts(run, output_dir, store)
                results.append({"audience_id": audience["id"], "status": "complete", "run_id": run["run_id"], "output_dir": str(output_dir)})
            finally:
                release_lease(store, audience["id"], owner)
        except Exception as exc:
            results.append({"audience_id": audience["id"], "status": "failed", "error": str(exc)})
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "results": results}


def launchd_path() -> Path:
    return Path.home() / "Library/LaunchAgents/com.1gmedia.attract-signal-reddit-watch.plist"


def install_launchd(interval_hours: int) -> dict[str, Any]:
    path = launchd_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    log_dir = default_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": "com.1gmedia.attract-signal-reddit-watch",
        "ProgramArguments": [sys.executable, str(script), "watch", "run", "--due"],
        "StartInterval": int(interval_hours * 3600), "RunAtLoad": False,
        "StandardOutPath": str(log_dir / "reddit-watch.log"),
        "StandardErrorPath": str(log_dir / "reddit-watch-error.log"),
        "EnvironmentVariables": {"ATTRACT_SIGNAL_HOME": str(default_home())},
    }
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
    loaded = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], capture_output=True, text=True)
    return {"installed": loaded.returncode == 0, "path": str(path), "stderr": loaded.stderr.strip()}


def uninstall_launchd() -> dict[str, Any]:
    path = launchd_path()
    if path.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
        path.unlink()
    return {"installed": False, "path": str(path)}


def watch_command(args: argparse.Namespace, store: SignalStore) -> int:
    if args.watch_action == "run":
        json_output(run_due(store, args.quality))
    elif args.watch_action == "install":
        if sys.platform != "darwin":
            raise RuntimeError("Automatic scheduler installation currently targets macOS launchd; use cron or Task Scheduler to call `watch run --due` on other platforms.")
        json_output(install_launchd(args.interval_hours))
    else:
        json_output(uninstall_launchd())
    return 0


def latest_dashboard(store: SignalStore, audience_id: Optional[str]) -> Path:
    if audience_id:
        row = store.connection.execute(
            "SELECT output_dir FROM runs WHERE audience_id=? AND status='complete' ORDER BY completed_at DESC LIMIT 1",
            (audience_id,),
        ).fetchone()
    else:
        row = store.connection.execute(
            "SELECT output_dir FROM runs WHERE status='complete' ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise ValueError("No completed Reddit Intelligence run is available")
    path = Path(row["output_dir"]) / "dashboard.html"
    if not path.exists():
        payload_path = Path(row["output_dir"]) / "reddit-intelligence.json"
        if not payload_path.exists():
            raise FileNotFoundError(path)
        run = json.loads(payload_path.read_text(encoding="utf-8"))
        path.write_text(render_dashboard(run, store), encoding="utf-8")
    return path


def dashboard_command(args: argparse.Namespace, store: SignalStore) -> int:
    path = latest_dashboard(store, args.audience_id)
    if args.dashboard_action == "open":
        webbrowser.open(path.as_uri())
    json_output({"dashboard": str(path), "opened": args.dashboard_action == "open"})
    return 0


def batch_command(args: argparse.Namespace, store: SignalStore) -> int:
    router = OpenAIRouter(store, "offline-batch", "balanced")
    if not router.client:
        raise RuntimeError(router.error or "OpenAI Batch API is unavailable")
    if args.batch_action == "submit":
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        requests = payload["requests"] if isinstance(payload, dict) else payload
        result = router.submit_batch(args.stage, requests)
    else:
        result = router.retrieve_batch(args.id)
    if not result:
        raise RuntimeError(router.error or "Batch operation failed")
    json_output(result)
    return 0


def community_command(args: argparse.Namespace, store: SignalStore) -> int:
    if args.community_action in {"list", "discover"}:
        rows = list_communities(store, args.audience_id)
        json_output({"communities": rows, "count": len(rows)})
        return 0
    if args.community_action == "show":
        rows = [row for row in list_communities(store, args.audience_id) if row["id"] == args.id or row["name"].lower() == args.id.lower().removeprefix("r/")]
        if not rows:
            raise ValueError(f"Community not found: {args.id}")
        json_output(rows[0])
        return 0
    if args.community_action == "compare":
        requested = {item.lower().removeprefix("r/") for item in split_csv(args.communities)}
        rows = [row for row in list_communities(store, args.audience_id) if row["name"].lower() in requested]
        json_output({"communities": rows})
        return 0
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    names = payload if isinstance(payload, list) else payload.get("communities", [])
    now = datetime.now(timezone.utc).isoformat()
    imported = 0
    with store.connection:
        for item in names:
            name = item if isinstance(item, str) else item.get("name")
            if not name:
                continue
            name = name.removeprefix("r/")
            identifier = "community_" + hashlib.sha256(name.lower().encode()).hexdigest()[:20]
            store.connection.execute(
                """INSERT INTO communities(id,name,source,description,subscribers,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET description=excluded.description,
                subscribers=excluded.subscribers,updated_at=excluded.updated_at""",
                (identifier, name, "imported", item.get("description") if isinstance(item, dict) else None,
                 item.get("subscribers") if isinstance(item, dict) else None, now, now),
            )
            imported += 1
    json_output({"imported": imported})
    return 0


def search_command(args: argparse.Namespace, store: SignalStore) -> int:
    if args.search_action == "run":
        rows = run_search(store, args.query, args.limit)
        json_output({"query": args.query, "count": len(rows), "results": rows})
        return 0
    if args.search_action == "save":
        json_output(save_search(store, args.name, args.query, args.audience_id))
        return 0
    if args.search_action == "list":
        json_output(list_saved_searches(store))
        return 0
    if args.search_action == "show":
        row = store.connection.execute("SELECT * FROM saved_searches WHERE id=?", (args.id,)).fetchone()
        if not row:
            raise ValueError(f"Saved search not found: {args.id}")
        payload = dict(row)
        payload["results"] = run_search(store, payload["query"], args.limit)
        ran_at = datetime.now(timezone.utc).isoformat()
        with store.connection:
            store.connection.execute(
                "INSERT INTO saved_search_runs(id,saved_search_id,result_count,result_ids_json,ran_at) VALUES (?,?,?,?,?)",
                (f"search_run_{uuid.uuid4().hex[:20]}", args.id, len(payload["results"]),
                 json.dumps([item["id"] for item in payload["results"]]), ran_at),
            )
        payload["ran_at"] = ran_at
        json_output(payload)
        return 0
    with store.connection:
        deleted = store.connection.execute("DELETE FROM saved_searches WHERE id=?", (args.id,)).rowcount
    json_output({"id": args.id, "deleted": bool(deleted)})
    return 0


def opportunities_command(args: argparse.Namespace, store: SignalStore) -> int:
    if args.opportunity_action == "list":
        json_output(list_opportunities(store, args.status))
        return 0
    if args.opportunity_action == "show":
        rows = [row for row in list_opportunities(store) if row["id"] == args.id]
        if not rows:
            raise ValueError(f"Opportunity not found: {args.id}")
        row = rows[0]
        events = [dict(item) for item in store.connection.execute(
            "SELECT * FROM opportunity_events WHERE opportunity_id=? ORDER BY created_at", (args.id,),
        )]
        row["events"] = events
        if args.reply_guidance:
            row["reply_guidance"] = "Help first, disclose any affiliation, follow the subreddit rules, and avoid promotional claims not supported by the evidence. This tool never posts for you."
        json_output(row)
        return 0
    if args.opportunity_action == "update":
        json_output(update_opportunity(store, args.id, args.status, args.note))
        return 0
    count = export_opportunities(store, args.out, args.status)
    json_output({"path": str(args.out), "rows": count})
    return 0


def evaluation_command(args: argparse.Namespace, store: SignalStore) -> int:
    if args.evaluation_action == "sample":
        count = sample_evaluation(store, args.out, args.count)
        json_output({"path": str(args.out), "labeling_dashboard": str(args.out.with_suffix(".html")), "sampled": count, "gold": False})
        return 0
    status = validate_gold(args.input)
    if args.evaluation_action == "label":
        json_output(status)
        return 0
    if not status["ready"]:
        raise RuntimeError(f"Evaluation corpus is not release-ready: {status['human_reviewed']}/300 human-reviewed rows")
    evaluator = Path(__file__).with_name("evaluate_reddit_intelligence.py")
    completed = subprocess.run([sys.executable, str(evaluator), str(args.input)], capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    print(completed.stdout)
    return 0


def onboard_command(store: SignalStore) -> int:
    health = doctor(store)
    tutorial_id = "tutorial-reddit-intelligence"
    tutorial = store.get_audience(tutorial_id)
    if not tutorial:
        fixture = Path(__file__).resolve().parents[4] / "tests/fixtures/reddit-conversations.json"
        tutorial = store.save_audience({
            "id": tutorial_id, "topic": "tattoo studio", "audience": "tattoo studio owners",
            "dedicated_subreddits": ["TattooArtists", "tattooing", "tattooadvice"],
            "input_paths": [str(fixture)] if fixture.exists() else [], "enabled": False,
        })
    install = resolve_last30days()
    json_output({
        "status": "ready" if health["status"] == "ready" else "degraded",
        "coverage": "Free public Reddit retrieval through Last30Days; optional ScrapeCreators enrichment when configured.",
        "last30days": {"version": install.version, "path": str(install.root)},
        "tutorial_audience": tutorial,
        "next": [
            "Save an audience with `audience save`.",
            "Run `research --topic ...` for live retrieval or add `--input` for reproducible artifact analysis.",
            "Install a schedule only with the explicit `watch install` command.",
        ],
        "scheduler_created": False, "credentials_written": False, "paid_backfill_started": False,
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attract Signal Reddit Intelligence v2")
    parser.add_argument("--home", type=Path, help="Override ATTRACT_SIGNAL_HOME for this invocation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("onboard", help="Run local coverage checks and create a disabled tutorial audience")

    research = sub.add_parser("research", help="Retrieve and/or analyze Last30Days Reddit evidence")
    research.add_argument("--topic", required=True)
    research.add_argument("--audience-id")
    research.add_argument("--input", action="append", help="Repeat for scout/deep or merged backend artifacts")
    research.add_argument("--refresh", action="store_true", help="Merge supplied artifacts with fresh retrieval")
    research.add_argument("--reddit-backend", choices=("auto", "public", "scrapecreators"), default="auto")
    research.add_argument("--backfill-days", type=int, choices=range(1, 366), metavar="1..365")
    research.add_argument("--allow-paid-backfill", action="store_true")
    research.add_argument("--brand", type=Path)
    research.add_argument("--days", type=int, choices=range(1, 366), default=30, metavar="1..365")
    research.add_argument("--quality", choices=("balanced", "deep"), default="balanced")
    research.add_argument("--out-dir", type=Path)
    research.add_argument("--aliases")
    research.add_argument("--dedicated-subreddits")
    research.add_argument("--negative-anchors")

    audience = sub.add_parser("audience", help="Manage saved audiences")
    audience_sub = audience.add_subparsers(dest="audience_action", required=True)
    save = audience_sub.add_parser("save")
    save.add_argument("--id", required=True); save.add_argument("--topic"); save.add_argument("--audience")
    save.add_argument("--aliases"); save.add_argument("--competitors"); save.add_argument("--dedicated-subreddits")
    save.add_argument("--subreddits"); save.add_argument("--days", type=int, choices=(7, 30, 90))
    save.add_argument("--cadence-hours", type=int); save.add_argument("--input", action="append")
    save.add_argument("--disabled", action="store_true")
    audience_sub.add_parser("list")
    show = audience_sub.add_parser("show"); show.add_argument("--id", required=True)
    delete = audience_sub.add_parser("delete"); delete.add_argument("--id", required=True)

    watch = sub.add_parser("watch", help="Run or install local audience monitors")
    watch_sub = watch.add_subparsers(dest="watch_action", required=True)
    watch_run = watch_sub.add_parser("run"); watch_run.add_argument("--due", action="store_true"); watch_run.add_argument("--quality", choices=("balanced", "deep"), default="balanced")
    watch_install = watch_sub.add_parser("install"); watch_install.add_argument("--interval-hours", type=int, default=24)
    watch_sub.add_parser("uninstall")

    alerts = sub.add_parser("alerts", help="Review or acknowledge local alerts")
    alert_sub = alerts.add_subparsers(dest="alert_action", required=True)
    alert_list = alert_sub.add_parser("list"); alert_list.add_argument("--audience-id"); alert_list.add_argument("--pending", action="store_true")
    ack = alert_sub.add_parser("acknowledge"); ack.add_argument("--id", required=True)

    dashboard = sub.add_parser("dashboard", help="Locate or open the latest dashboard")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_action", required=True)
    for action in ("build", "open"):
        item = dashboard_sub.add_parser(action); item.add_argument("--audience-id")
    batch = sub.add_parser("batch", help="Submit or retrieve optional offline Responses API batches")
    batch_sub = batch.add_subparsers(dest="batch_action", required=True)
    batch_submit = batch_sub.add_parser("submit"); batch_submit.add_argument("--manifest", type=Path, required=True); batch_submit.add_argument("--stage", default="offline_classification")
    batch_status = batch_sub.add_parser("status"); batch_status.add_argument("--id", required=True)

    community = sub.add_parser("community", help="Discover and inspect Reddit communities")
    community_sub = community.add_subparsers(dest="community_action", required=True)
    for action in ("discover", "list"):
        item = community_sub.add_parser(action); item.add_argument("--audience-id")
    community_show = community_sub.add_parser("show"); community_show.add_argument("--id", required=True); community_show.add_argument("--audience-id")
    community_compare = community_sub.add_parser("compare"); community_compare.add_argument("--communities", required=True); community_compare.add_argument("--audience-id")
    community_import = community_sub.add_parser("import"); community_import.add_argument("--input", type=Path, required=True)

    search = sub.add_parser("search", help="Run and manage advanced local evidence searches")
    search_sub = search.add_subparsers(dest="search_action", required=True)
    search_run = search_sub.add_parser("run"); search_run.add_argument("query"); search_run.add_argument("--limit", type=int, default=100)
    search_save = search_sub.add_parser("save"); search_save.add_argument("--name", required=True); search_save.add_argument("--query", required=True); search_save.add_argument("--audience-id")
    search_sub.add_parser("list")
    search_show = search_sub.add_parser("show"); search_show.add_argument("--id", required=True); search_show.add_argument("--limit", type=int, default=100)
    search_delete = search_sub.add_parser("delete"); search_delete.add_argument("--id", required=True)

    opportunities = sub.add_parser("opportunities", help="Manage the content opportunity inbox")
    opportunity_sub = opportunities.add_subparsers(dest="opportunity_action", required=True)
    opportunity_list = opportunity_sub.add_parser("list"); opportunity_list.add_argument("--status")
    opportunity_show = opportunity_sub.add_parser("show"); opportunity_show.add_argument("--id", required=True); opportunity_show.add_argument("--reply-guidance", action="store_true")
    opportunity_update = opportunity_sub.add_parser("update"); opportunity_update.add_argument("--id", required=True); opportunity_update.add_argument("--status", required=True, choices=("triaged", "approved", "drafted", "published", "dismissed")); opportunity_update.add_argument("--note")
    opportunity_export = opportunity_sub.add_parser("export"); opportunity_export.add_argument("--out", type=Path, required=True); opportunity_export.add_argument("--status")

    evaluation = sub.add_parser("evaluation", help="Build and validate a human-reviewed evaluation corpus")
    evaluation_sub = evaluation.add_subparsers(dest="evaluation_action", required=True)
    evaluation_sample = evaluation_sub.add_parser("sample"); evaluation_sample.add_argument("--out", type=Path, required=True); evaluation_sample.add_argument("--count", type=int, default=300)
    for action in ("label", "run"):
        item = evaluation_sub.add_parser(action); item.add_argument("--input", type=Path, required=True)
    sub.add_parser("doctor", help="Check local health and compatibility")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.home:
        os.environ["ATTRACT_SIGNAL_HOME"] = str(args.home.expanduser().resolve())
    store = SignalStore()
    try:
        if args.command == "research":
            return research_command(args, store)
        if args.command == "audience":
            return audience_command(args, store)
        if args.command == "watch":
            return watch_command(args, store)
        if args.command == "alerts":
            return alert_command(args, store)
        if args.command == "dashboard":
            return dashboard_command(args, store)
        if args.command == "batch":
            return batch_command(args, store)
        if args.command == "community":
            return community_command(args, store)
        if args.command == "search":
            return search_command(args, store)
        if args.command == "opportunities":
            return opportunities_command(args, store)
        if args.command == "evaluation":
            return evaluation_command(args, store)
        if args.command == "onboard":
            return onboard_command(store)
        health = doctor(store)
        try:
            install = resolve_last30days()
            health["last30days_resolution"] = {
                "selected_realpath": str(install.root), "version": install.version,
                "python": str(install.python), "deduplicated": True,
            }
        except RuntimeError as exc:
            health["status"] = "degraded"
            health["last30days_resolution"] = {"error": str(exc)}
        json_output(health)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        if isinstance(exc, FileNotFoundError):
            code = "retrieval_failed"
        elif isinstance(exc, ValueError):
            code = "report_validation_failed"
        elif "model" in str(exc).lower() or "openai" in str(exc).lower():
            code = "model_unavailable"
        else:
            code = "retrieval_failed"
        json_output({"status": "error", "error_code": code, "error": str(exc)})
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
