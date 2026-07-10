#!/usr/bin/env python3
"""CLI for Attract Signal Reddit Intelligence v2."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from reddit_intelligence import OpenAIRouter, SignalStore, default_home, doctor, render_dashboard, run_research, slugify


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
    run = run_research(
        topic=args.topic, inputs=expand_inputs(args.input), audience_id=args.audience_id,
        brand_path=args.brand, days=args.days, quality=args.quality, output_dir=output_dir,
        store=store, aliases=split_csv(args.aliases), dedicated_subreddits=split_csv(args.dedicated_subreddits),
        negative_anchors=split_csv(args.negative_anchors),
    )
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
            paths = expand_inputs(audience["input_paths"])
            if not paths:
                raise FileNotFoundError("saved audience has no input artifact")
            output_dir = default_home() / "reports" / audience["id"] / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            run = run_research(
                topic=audience["topic"], inputs=paths, audience_id=audience["id"], brand_path=None,
                days=audience["window_days"], quality=quality, output_dir=output_dir, store=store,
            )
            results.append({"audience_id": audience["id"], "status": "complete", "run_id": run["run_id"], "output_dir": str(output_dir)})
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attract Signal Reddit Intelligence v2")
    parser.add_argument("--home", type=Path, help="Override ATTRACT_SIGNAL_HOME for this invocation")
    sub = parser.add_subparsers(dest="command", required=True)

    research = sub.add_parser("research", help="Analyze Last30Days Reddit artifacts")
    research.add_argument("--topic", required=True)
    research.add_argument("--audience-id")
    research.add_argument("--input", action="append", required=True, help="Repeat for scout/deep or merged backend artifacts")
    research.add_argument("--brand", type=Path)
    research.add_argument("--days", type=int, choices=(7, 30, 90), default=30)
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
        json_output(doctor(store))
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
