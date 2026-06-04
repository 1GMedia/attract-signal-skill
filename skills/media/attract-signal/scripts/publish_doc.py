#!/usr/bin/env python3
"""Publish a Markdown Attract Signal report to Google Docs with gogcli."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def run(cmd: List[str]) -> Dict[str, Any]:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Expected JSON from {' '.join(cmd)}, got:\n{proc.stdout}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Google Doc from a local Markdown report using gogcli.")
    parser.add_argument("--file", required=True, type=Path, help="Markdown report file")
    parser.add_argument("--title", required=True, help="Google Doc title")
    parser.add_argument("--parent", default=None, help="Optional Drive folder ID")
    parser.add_argument("--dry-run", action="store_true", help="Print intended command without creating a Doc")
    args = parser.parse_args()

    if shutil.which("gog") is None:
        print("ERROR: gogcli is required. Install with: brew install openclaw/tap/gogcli", file=sys.stderr)
        return 2
    if not args.file.exists():
        print(f"ERROR: report file not found: {args.file}", file=sys.stderr)
        return 2
    cmd = ["gog", "docs", "create", args.title, "--file", str(args.file), "--json"]
    if args.parent:
        cmd.extend(["--parent", args.parent])
    if args.dry_run:
        print(json.dumps({"dry_run": True, "command": cmd}, indent=2))
        return 0
    created = run(cmd)
    doc_id = (created.get("file") or {}).get("id") or created.get("id")
    if not doc_id:
        print(json.dumps(created, indent=2))
        raise RuntimeError("Google Doc was created but no document ID was returned")
    verified = run(["gog", "drive", "get", doc_id, "--json"])
    print(json.dumps({"created": created, "verified": verified}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

