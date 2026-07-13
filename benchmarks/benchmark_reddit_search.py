#!/usr/bin/env python3
"""Build a 100k-row local index and enforce the sub-second search gate."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/media/attract-signal/scripts"))

from reddit_intelligence import SignalStore, utc_now  # noqa: E402
from reddit_parity import run_search  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        store = SignalStore(Path(directory) / "benchmark.sqlite3")
        now = utc_now()
        run_id = "run_benchmark"
        count = 100_000
        with store.connection:
            store.connection.execute(
                """INSERT INTO runs(id,topic,status,schema_version,quality,window_days,started_at,
                completed_at,input_checksums_json,backend_health_json,model_ids_json,metrics_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, "booking software", "complete", "2.0", "balanced", 30, now, now, "{}", "{}", "{}", "{}"),
            )
            threads = [(
                f"thread_{index}", f"reddit_{index}", f"https://www.reddit.com/r/SaaS/comments/{index}/benchmark",
                "SaaS", f"Booking software pain point {index}", "Need a reliable booking workflow",
                "2026-07-01", index % 100, index % 30, f"fingerprint_{index}", now, now, "[]",
            ) for index in range(count)]
            store.connection.executemany(
                """INSERT INTO threads(id,reddit_id,canonical_url,subreddit,title,body,published_at,
                upvotes,comment_count,text_fingerprint,first_seen_at,last_seen_at,provenance_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", threads,
            )
            store.connection.executemany(
                "INSERT INTO threads_fts(thread_id,title,body,subreddit) VALUES (?,?,?,?)",
                ((row[0], row[4], row[5], row[3]) for row in threads),
            )
            store.connection.executemany(
                """INSERT INTO classifications(run_id,thread_id,relevance_label,relevance_score,
                exclusion_reasons_json,lenses_json,purchase_intent,jobs_json,outcomes_json,
                objections_json,competitors_json,sentiment) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                ((run_id, f"thread_{index}", "relevant", .91, "[]", '["pain_points"]', "none",
                  "[]", "[]", "[]", "[]", "negative") for index in range(count)),
            )
        started = time.perf_counter()
        results = run_search(store, '"booking software" lens:pain_points min_comments:5', 100)
        elapsed = time.perf_counter() - started
        store.close()
    payload = {"rows": count, "results": len(results), "search_seconds": round(elapsed, 4), "passed": elapsed < 1.0}
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
