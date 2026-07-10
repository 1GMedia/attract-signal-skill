from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/media/attract-signal/scripts/analyze_reddit_conversations.py"
SPEC = importlib.util.spec_from_file_location("analyze_reddit_conversations", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AnalyzeRedditConversationsTest(unittest.TestCase):
    def test_json_fixture_covers_all_five_lenses_and_ignores_x(self) -> None:
        fixture = ROOT / "tests/fixtures/reddit-conversations.json"
        conversations = MODULE.dedupe(MODULE.load_conversations(fixture))
        MODULE.score_conversations(conversations, "tattoo studio", MODULE.date(2026, 7, 10), 30)
        payload = MODULE.build_payload(
            conversations,
            "tattoo studio",
            [fixture],
            MODULE.date(2026, 7, 10),
            30,
            25,
        )

        self.assertEqual(payload["conversation_count"], 5)
        for lens in MODULE.LENSES:
            self.assertGreaterEqual(len(payload["lenses"][lens]), 1, lens)
        self.assertTrue(all(row["source_url"].startswith("https://www.reddit.com/") for row in payload["top_conversations"]))
        money_quotes = [item["exact_quote"] for item in payload["lenses"]["money_talk"]]
        self.assertTrue(any("$99 per month" in quote for quote in money_quotes))

    def test_markdown_parser_preserves_urls_comments_and_exact_language(self) -> None:
        fixture = ROOT / "tests/fixtures/last30days-reddit.md"
        conversations = MODULE.load_conversations(fixture)

        self.assertEqual(len(conversations), 2)
        self.assertEqual(conversations[0].subreddit, "TattooArtists")
        self.assertEqual(conversations[0].upvotes, 120)
        self.assertEqual(conversations[0].comment_count, 42)
        self.assertEqual(conversations[0].top_comments[0]["author"], "u/inkedperson")
        self.assertIn("tired of answering", conversations[0].body)
        self.assertTrue(conversations[1].source_url.endswith("/alternatives/"))

        MODULE.score_conversations(conversations, "tattoo booking", MODULE.date(2026, 7, 10), 30)
        payload = MODULE.build_payload(
            conversations,
            "tattoo booking",
            [fixture],
            MODULE.date(2026, 7, 10),
            30,
            25,
        )
        self.assertTrue(any(row["kind"] == "comment" for row in payload["exact_language"]))

    def test_cli_writes_json_and_markdown(self) -> None:
        fixture = ROOT / "tests/fixtures/reddit-conversations.json"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "signals.json"
            markdown = Path(directory) / "signals.md"
            exit_code = MODULE.main([
                str(fixture),
                "--topic", "tattoo studio",
                "--as-of", "2026-07-10",
                "--out", str(out),
                "--markdown", str(markdown),
            ])
            self.assertEqual(exit_code, 0)
            self.assertTrue(out.exists())
            self.assertTrue(markdown.exists())
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["conversation_count"], 5)
            self.assertIn("## Five Conversation Lenses", markdown.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
