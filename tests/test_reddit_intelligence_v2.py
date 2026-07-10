from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/media/attract-signal/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("reddit_intelligence", SCRIPTS / "reddit_intelligence.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RedditIntelligenceV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_key = os.environ.pop("OPENAI_API_KEY", None)

    def tearDown(self) -> None:
        if self.previous_key is not None:
            os.environ["OPENAI_API_KEY"] = self.previous_key

    def test_high_engagement_off_topic_thread_cannot_cross_relevance_gate(self) -> None:
        fixture = ROOT / "tests/fixtures/reddit-relevance-adversarial.json"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            store = MODULE.SignalStore(home / "state.sqlite3")
            try:
                run = MODULE.run_research(
                    topic="tattoo studio booking software pain points alternatives pricing",
                    inputs=[fixture], audience_id=None, brand_path=None, days=30, quality="balanced",
                    output_dir=home / "report", store=store,
                )
            finally:
                store.close()

            self.assertEqual(run["corpus_status"], "limited")
            self.assertEqual(len(run["threads"]), 3)
            noise = next(row for row in run["excluded_threads"] if row["reddit_id"] == "noise1")
            self.assertEqual(noise["relevance_label"], "irrelevant")
            self.assertLess(noise["relevance_score"], MODULE.UNCERTAIN_THRESHOLD)
            self.assertNotIn("hot_discussions", noise.get("lenses", []))

    def test_artifacts_are_cited_and_dashboard_has_restrictive_csp(self) -> None:
        fixture = ROOT / "tests/fixtures/reddit-conversations.json"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            store = MODULE.SignalStore(home / "state.sqlite3")
            try:
                run = MODULE.run_research(
                    topic="tattoo studio", inputs=[fixture], audience_id=None, brand_path=None,
                    days=30, quality="balanced", output_dir=home / "report", store=store,
                    dedicated_subreddits=["TattooArtists", "tattooing", "tattooadvice"],
                )
            finally:
                store.close()
            payload = json.loads((home / "report/reddit-intelligence.json").read_text(encoding="utf-8"))
            dashboard = (home / "report/dashboard.html").read_text(encoding="utf-8")
            self.assertEqual(payload["metrics"]["relevant_threads"], 5)
            self.assertTrue(all(row["canonical_url"].startswith("https://www.reddit.com/") for row in payload["threads"]))
            self.assertIn("Content-Security-Policy", dashboard)
            self.assertIn("default-src &#x27;none&#x27;", dashboard)
            self.assertNotIn("OPENAI_API_KEY", dashboard)

    def test_audience_and_alert_upserts_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MODULE.SignalStore(Path(directory) / "state.sqlite3")
            try:
                first = store.save_audience({"id": "test", "topic": "test topic", "input_paths": ["a.json"]})
                second = store.save_audience({"id": "test", "topic": "test topic", "input_paths": ["a.json"]})
                self.assertEqual(first["created_at"], second["created_at"])
                self.assertEqual(len(store.list_audiences()), 1)
                self.assertEqual(store.integrity(), "ok")
            finally:
                store.close()

    def test_last30days_compatibility_is_major_minor_strict(self) -> None:
        self.assertTrue(MODULE.last30days_compatible("3.11.1"))
        self.assertFalse(MODULE.last30days_compatible("3.12.0"))
        self.assertFalse(MODULE.last30days_compatible("4.0.0"))

    def test_model_discovery_uses_verified_fallback_when_sol_alias_is_unavailable(self) -> None:
        previous = os.environ.get("ATTRACT_SIGNAL_MODEL_SOL")
        os.environ["ATTRACT_SIGNAL_MODEL_SOL"] = "gpt-5.6-sol-unverified"
        try:
            router = MODULE.OpenAIRouter.__new__(MODULE.OpenAIRouter)
            router.available_models = {"gpt-5.4-mini-2026-03-17", "gpt-5.5-2026-04-23"}
            router.models = {"filter": None, "analysis": None, "synthesis": None, "embedding": None}
            router.error = None
            router._resolve_models()
            self.assertEqual(router.models["filter"], "gpt-5.4-mini-2026-03-17")
            self.assertEqual(router.models["analysis"], "gpt-5.5-2026-04-23")
            self.assertEqual(router.models["synthesis"], "gpt-5.5-2026-04-23")
        finally:
            if previous is None:
                os.environ.pop("ATTRACT_SIGNAL_MODEL_SOL", None)
            else:
                os.environ["ATTRACT_SIGNAL_MODEL_SOL"] = previous

    def test_semantic_enrichment_rejects_non_verbatim_model_quote(self) -> None:
        record = {
            "id": "thread_1", "title": "Exact source title", "body": "Exact source body.",
            "subreddit": "test", "exact_quote": "Exact source title", "lenses": [],
            "purchase_intent": "none", "jobs_to_be_done": [], "desired_outcomes": [],
            "objections": [], "competitors": [], "sentiment": "neutral",
        }

        class FakeRouter:
            enabled = True
            quality = "balanced"
            calls = 0
            call_limit = 20
            models = {"analysis": "gpt-test"}

            def structured(self, *args, **kwargs):
                self.calls += 1
                return {"items": [{
                    "thread_id": "thread_1", "lenses": ["pain_points"], "purchase_intent": "none",
                    "jobs_to_be_done": ["fix the issue"], "desired_outcomes": [], "objections": [],
                    "competitors": [], "sentiment": "negative", "exact_quote": "A fabricated quote",
                }]}

        count = MODULE.semantic_enrich_records([record], FakeRouter())
        self.assertEqual(count, 1)
        self.assertEqual(record["exact_quote"], "Exact source title")

    def test_batch_submission_uses_responses_endpoint(self) -> None:
        class Result:
            id = "batch_123"
            status = "validating"

        class Files:
            def create(self, **kwargs):
                self.payload = kwargs["file"].getvalue().decode("utf-8")
                return type("Upload", (), {"id": "file_123"})()

        class Batches:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return Result()

        router = MODULE.OpenAIRouter.__new__(MODULE.OpenAIRouter)
        router.client = type("Client", (), {"files": Files(), "batches": Batches()})()
        router.run_id = "run_test"
        router.error = None
        result = router.submit_batch("classification", [{
            "custom_id": "thread_1", "body": {"model": "gpt-test", "input": "test"},
        }])
        self.assertEqual(result["id"], "batch_123")
        self.assertEqual(router.client.batches.kwargs["endpoint"], "/v1/responses")
        self.assertIn('"url": "/v1/responses"', router.client.files.payload)


if __name__ == "__main__":
    unittest.main()
