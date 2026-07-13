from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/media/attract-signal/scripts"
sys.path.insert(0, str(SCRIPTS))

import reddit_intelligence as core  # noqa: E402
import reddit_parity as parity  # noqa: E402
import reddit_signal as cli  # noqa: E402


class RedditParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.key = os.environ.pop("OPENAI_API_KEY", None)

    def tearDown(self) -> None:
        if self.key is not None:
            os.environ["OPENAI_API_KEY"] = self.key

    def _run(self, root: Path) -> tuple[core.SignalStore, dict]:
        store = core.SignalStore(root / "state.sqlite3")
        store.save_audience({
            "id": "tattoo", "topic": "tattoo studio", "aliases": ["tattoo booking"],
            "dedicated_subreddits": ["TattooArtists", "tattooing", "tattooadvice"],
        })
        run = core.run_research(
            topic="tattoo studio", inputs=[ROOT / "tests/fixtures/reddit-conversations.json"],
            audience_id="tattoo", brand_path=None, days=30, quality="balanced",
            output_dir=root / "report", store=store,
        )
        parity.postprocess_run(store, run)
        return store, run

    def test_parity_migrations_comment_fts_and_community_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, run = self._run(Path(directory))
            try:
                tables = {row[0] for row in store.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )}
                self.assertTrue({"communities", "saved_searches", "opportunities", "comment_classifications"} <= tables)
                self.assertEqual(run["metrics"]["classified_comments"], sum(len(row["comments"]) for row in run["threads"]))
                self.assertGreaterEqual(len(run["communities"]), 3)
                self.assertTrue(all(row["growth"] is None for row in run["communities"]))
                queue = Path(directory) / "labels.csv"
                self.assertEqual(parity.sample_evaluation(store, queue, 3), 3)
                labeling_html = queue.with_suffix(".html").read_text(encoding="utf-8")
                self.assertIn("Content-Security-Policy", labeling_html)
                self.assertIn("human reviewer", labeling_html)
            finally:
                store.close()

    def test_advanced_search_and_saved_search_use_strict_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self._run(Path(directory))
            try:
                rows = parity.run_search(store, '"pay" lens:money_talk min_comments:20 relevance:0.72')
                self.assertEqual(len(rows), 1)
                self.assertIn(rows[0]["purchase_intent"], {"evaluating", "willing_to_pay"})
                self.assertIn("money_talk", rows[0]["lenses"])
                saved = parity.save_search(store, "money", 'lens:money_talk subreddit:tattooing', "tattoo")
                self.assertEqual(len(parity.list_saved_searches(store)), 1)
                self.assertEqual(saved["query"], "lens:money_talk subreddit:tattooing")
                with self.assertRaises(ValueError):
                    parity.parse_search("unknown_filter:value")
            finally:
                store.close()

    def test_opportunity_state_machine_is_append_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self._run(Path(directory))
            try:
                rows = parity.list_opportunities(store)
                self.assertGreater(len(rows), 0)
                opportunity_id = rows[0]["id"]
                updated = parity.update_opportunity(store, opportunity_id, "triaged", "Worth drafting")
                self.assertEqual(updated["status"], "triaged")
                with self.assertRaises(ValueError):
                    parity.update_opportunity(store, opportunity_id, "published", None)
                event_count = store.connection.execute(
                    "SELECT COUNT(*) FROM opportunity_events WHERE opportunity_id=?", (opportunity_id,),
                ).fetchone()[0]
                self.assertEqual(event_count, 2)
            finally:
                store.close()

    def test_retrieval_adapter_uses_plan_file_and_argument_array(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "last30days"
            (skill / "scripts").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nversion: 3.11.9\n---\n", encoding="utf-8")
            fixture = json.loads((ROOT / "tests/fixtures/reddit-conversations.json").read_text(encoding="utf-8"))
            script = (
                "import json\n"
                f"print(json.dumps({fixture!r}))\n"
            )
            (skill / "scripts/last30days.py").write_text(script, encoding="utf-8")
            previous = os.environ.get("LAST30DAYS_SKILL_DIR")
            os.environ["LAST30DAYS_SKILL_DIR"] = str(skill)
            store = core.SignalStore(root / "state.sqlite3")
            try:
                result = parity.retrieve_reddit(
                    store=store, topic="tattoo studio", audience_id=None, days=30,
                    backend="public", output_dir=root / "sources",
                )
                self.assertEqual(result["version"], "3.11.9")
                self.assertEqual(len(result["artifacts"]), 2)
                command = json.loads(store.connection.execute(
                    "SELECT command_json FROM retrieval_jobs LIMIT 1"
                ).fetchone()[0])
                self.assertIn("--plan", command)
                self.assertIn("--search=reddit", command)
            finally:
                store.close()
                if previous is None:
                    os.environ.pop("LAST30DAYS_SKILL_DIR", None)
                else:
                    os.environ["LAST30DAYS_SKILL_DIR"] = previous

    def test_due_monitor_persists_new_fixture_then_reports_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous_home = os.environ.get("ATTRACT_SIGNAL_HOME")
            os.environ["ATTRACT_SIGNAL_HOME"] = str(root)
            store = core.SignalStore(root / "state.sqlite3")
            fixture = ROOT / "tests/fixtures/reddit-conversations.json"
            store.save_audience({
                "id": "watch", "topic": "tattoo studio", "enabled": True,
                "dedicated_subreddits": ["TattooArtists", "tattooing", "tattooadvice"],
                "cadence_hours": 24,
            })
            retrieval = {"artifacts": [fixture], "receipts": [{"status": "verified", "items": 5}]}
            try:
                with mock.patch.object(cli, "retrieve_reddit", return_value=retrieval):
                    first = cli.run_due(store, "balanced")
                    self.assertEqual(first["results"][0]["status"], "complete")
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM threads").fetchone()[0], 5)
                    with store.connection:
                        store.connection.execute("UPDATE audiences SET last_success_at=NULL WHERE id='watch'")
                    second = cli.run_due(store, "balanced")
                    self.assertEqual(second["results"][0]["status"], "unchanged")
            finally:
                store.close()
                if previous_home is None:
                    os.environ.pop("ATTRACT_SIGNAL_HOME", None)
                else:
                    os.environ["ATTRACT_SIGNAL_HOME"] = previous_home


if __name__ == "__main__":
    unittest.main()
