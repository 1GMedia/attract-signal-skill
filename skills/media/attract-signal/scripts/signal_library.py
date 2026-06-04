#!/usr/bin/env python3
"""Maintain a reusable local Attract Signal library."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_library(path: Path) -> Dict[str, Any]:
    if path.exists():
        return load_json(path)
    return {"version": 1, "updated_at": None, "signals": []}


def signal_key(signal: Dict[str, Any]) -> str:
    return str(signal.get("source_url") or signal.get("id") or signal.get("title"))


def upsert(existing: List[Dict[str, Any]], incoming: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_key = {signal_key(item): item for item in existing}
    for item in incoming:
        row = dict(item)
        row["library_added_at"] = row.get("library_added_at") or datetime.now(timezone.utc).isoformat()
        by_key[signal_key(row)] = row
    return sorted(by_key.values(), key=lambda item: (item.get("cross_channel_signal_score") or item.get("signal_score") or 0), reverse=True)


def cmd_add(args: argparse.Namespace) -> int:
    library = load_library(args.library)
    payload = load_json(args.signals)
    incoming = payload.get("top_signals") if args.top_only else payload.get("videos")
    incoming = incoming or payload.get("top_signals") or []
    library["signals"] = upsert(library.get("signals") or [], incoming)
    library["updated_at"] = datetime.now(timezone.utc).isoformat()
    args.library.parent.mkdir(parents=True, exist_ok=True)
    args.library.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"library": str(args.library), "signals": len(library["signals"])}, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    library = load_library(args.library)
    for index, signal in enumerate((library.get("signals") or [])[: args.limit], 1):
        score = signal.get("cross_channel_signal_score") or signal.get("signal_score") or "unknown"
        print(f"{index}. [{score}] {signal.get('title') or signal.get('id')} — {signal.get('source_url')}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    library = load_library(args.library)
    query = args.query.lower()
    rows = []
    for signal in library.get("signals") or []:
        haystack = " ".join(str(signal.get(key) or "") for key in ("title", "description", "channel", "source_url", "platform")).lower()
        if query in haystack:
            rows.append(signal)
    print(json.dumps({"query": args.query, "count": len(rows), "signals": rows[: args.limit]}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Reusable local library for Attract Signal outputs.")
    parser.add_argument("--library", type=Path, default=Path.home() / ".attract-signal" / "signal-library.json")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="Add signals JSON into the library")
    add.add_argument("--signals", required=True, type=Path)
    add.add_argument("--top-only", action="store_true")
    add.set_defaults(func=cmd_add)
    list_cmd = sub.add_parser("list", help="List top library signals")
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.set_defaults(func=cmd_list)
    search = sub.add_parser("search", help="Search library signals")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=cmd_search)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

