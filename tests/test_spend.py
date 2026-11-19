"""The token economy: count each call once, price it, give it to an agent."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from helpers import DEMO

import herdr_state
import spend

PRICES = {
    "opus": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write_5m": 5.0, "cache_write_1h": 8.0},
    "opus-4": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_write_5m": 6.25, "cache_write_1h": 10.0},
    "haiku": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write_5m": 0.125, "cache_write_1h": 0.2},
}
DAY = datetime(2026, 1, 15, tzinfo=UTC)
NOW = DAY.replace(hour=17, minute=30)


def line(msg_id: str, when: str, model: str = "claude-opus-5-5", session: str = "s1",
         cwd: str = "/work/acme-web", **usage: int) -> str:
    u = {"input_tokens": 10, "output_tokens": 100, "cache_read_input_tokens": 1000,
         "cache_creation_input_tokens": 0, **usage}
    return json.dumps({"type": "assistant", "timestamp": when, "sessionId": session, "cwd": cwd,
                       "message": {"id": msg_id, "model": model, "usage": u,
                                   "content": [{"type": "text", "text": "(synthetic)"}]}})


def calls_of(lines: list[str], until: datetime = NOW) -> list[spend.Call]:
    seen: dict[str, spend.Call] = {}
    spend.calls_in(lines, DAY, until, PRICES, "file-stem", seen)
    return list(seen.values())


class CountOnceTest(unittest.TestCase):
    def test_one_call_on_three_lines_counts_once(self) -> None:
        same = line("msg_1", "2026-01-15T09:00:00Z")
        self.assertEqual(len(calls_of([same, same, same])), 1)

    def test_the_demo_has_more_lines_than_calls(self) -> None:
        # Measure the trap on the synthetic transcripts: lines with usage vs calls.
        files = list((DEMO / "logs").glob("**/*.jsonl"))
        lines = [ln for f in files for ln in f.read_text(encoding="utf-8").splitlines()
                 if '"usage"' in ln and '"assistant"' in ln]
        calls, _ = spend.read_calls([DEMO / "logs"], DAY - timedelta(days=2), NOW, PRICES)
        self.assertGreater(len(lines), 2 * len(calls))

    def test_only_the_window(self) -> None:
        calls = calls_of([line("a", "2026-01-14T23:59:00Z"), line("b", "2026-01-15T00:00:00Z"),
                          line("c", "2026-01-15T17:31:00Z")])
        self.assertEqual([c.when.hour for c in calls], [0])

    def test_lines_with_no_price_are_skipped(self) -> None:
        self.assertEqual(calls_of([line("a", "2026-01-15T09:00:00Z", model="<synthetic>"),
                                   '{"type": "user", "usage": "not json"',
                                   json.dumps({"type": "user", "message": {"usage": {}}})]), [])

    def test_a_subagent_line_names_its_parent_session(self) -> None:
        [c] = calls_of([line("a", "2026-01-15T09:00:00Z", session="parent")])
        self.assertEqual(c.session, "parent")


class PriceTest(unittest.TestCase):
    def test_the_longest_key_wins(self) -> None:
        self.assertEqual(spend.price_key("claude-opus-4-8", PRICES), "opus-4")
        self.assertEqual(spend.price_key("claude-opus-5-5", PRICES), "opus")
        self.assertIsNone(spend.price_key("gpt-x", PRICES))

    def test_cost_with_the_cache_split(self) -> None:
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 2_000_000,
                 "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000,
                                    "ephemeral_1h_input_tokens": 1_000_000}}
        self.assertAlmostEqual(spend.cost_of(usage, PRICES["opus"]), 4 + 20 + 0.2 + 5 + 8)

    def test_writes_with_no_split_count_as_5_min(self) -> None:
        usage = {"cache_creation_input_tokens": 1_000_000}
        self.assertAlmostEqual(spend.cost_of(usage, PRICES["opus"]), 5.0)


def agent(name: str, folder: str, session: str = "", kind: str = "claude",
          space: str = "acme-web") -> herdr_state.Agent:
    return herdr_state.Agent(space=space, tab="build", name=name, kind=kind, state="working",
                             folders=[folder], session=session, pane_id=f"p-{name}")


class AttributeTest(unittest.TestCase):
    def test_by_session_first(self) -> None:
        calls = calls_of([line("a", "2026-01-15T09:00:00Z", session="s-api", cwd="/elsewhere")])
        rows = spend.attribute(calls, [agent("api", "/work/acme-web", session="s-api")])
        self.assertEqual(list(rows), ["acme-web / build / api"])

    def test_by_folder_when_one_agent_works_there(self) -> None:
        calls = calls_of([line("a", "2026-01-15T09:00:00Z")])
        rows = spend.attribute(calls, [agent("api", "/work/acme-web")])
        self.assertEqual(list(rows), ["acme-web / build / api"])

    def test_two_agents_in_one_folder_get_a_folder_row(self) -> None:
        calls = calls_of([line("a", "2026-01-15T09:00:00Z")])
        rows = spend.attribute(calls, [agent("api", "/work/acme-web"), agent("web", "/work/acme-web")])
        self.assertEqual(list(rows), ["acme-web / acme-web (shared folder)"])

    def test_no_live_agent(self) -> None:
        calls = calls_of([line("a", "2026-01-15T09:00:00Z", cwd="/work/old-app")])
        rows = spend.attribute(calls, [agent("api", "/work/acme-web")])
        self.assertEqual(list(rows), ["(no live pane) old-app"])
        self.assertEqual(rows["(no live pane) old-app"].space, spend.NO_PANE)

    def test_other_agent_kinds_are_not_matched(self) -> None:
        calls = calls_of([line("a", "2026-01-15T09:00:00Z")])
        rows = spend.attribute(calls, [agent("web", "/work/acme-web", kind="codex")])
        self.assertEqual(list(rows), ["(no live pane) acme-web"])


class ReportTest(unittest.TestCase):
    def test_levers(self) -> None:
        big = [line(f"b{n}", f"2026-01-15T1{n}:00:00Z", cache_read_input_tokens=250_000)
               for n in range(2)]
        rebuild = [line(f"r{n}", f"2026-01-15T0{n}:00:00Z", cwd="/work/demo-api",
                        cache_read_input_tokens=10_000, cache_creation_input_tokens=20_000)
                   for n in range(5)]
        agents = [agent("api", "/work/acme-web"), agent("worker", "/work/demo-api", space="demo-api")]
        r = spend.report(calls_of(big + rebuild), agents, DAY, NOW, 200_000, 0.30)
        self.assertEqual(len(r["levers"]), 2)
        self.assertIn("acme-web / build / api: its last call read 250k", r["levers"][1])
        self.assertIn("demo-api / build / worker: 67% of the tokens", r["levers"][0])

    def test_spend_per_hour_from_the_day_start(self) -> None:
        calls = calls_of([line("a", "2026-01-15T00:10:00Z"), line("b", "2026-01-15T02:10:00Z")])
        r = spend.report(calls, [agent("api", "/work/acme-web")], DAY, NOW, 200_000, 0.3)
        hours = r["by_space"][0]["per_hour"]
        self.assertEqual(len(hours), 18)
        self.assertGreater(hours[0], 0)
        self.assertEqual(hours[1], 0)
        self.assertGreater(hours[2], 0)

    def test_agents_with_no_reader_are_named(self) -> None:
        r = spend.report([], [agent("web", "/w", kind="codex")], DAY, NOW, 200_000, 0.3)
        self.assertEqual(r["no_reader"], ["codex"])
        self.assertEqual(r["total"]["calls"], 0)


class DayTest(unittest.TestCase):
    def test_day_start_today_or_yesterday(self) -> None:
        self.assertEqual(spend.day_start(NOW, "06:00"), DAY.replace(hour=6))
        early = DAY.replace(hour=5)
        self.assertEqual(spend.day_start(early, "06:00"), DAY.replace(hour=6) - timedelta(days=1))

    def test_tokens(self) -> None:
        self.assertEqual([spend.tokens(n) for n in (900, 12_345, 7_900_000)], ["900", "12k", "7.9M"])


class ReadCallsTest(unittest.TestCase):
    def test_a_file_written_before_the_window_is_not_opened(self) -> None:
        calls, files = spend.read_calls([DEMO / "logs"], datetime.now(UTC) + timedelta(days=1),
                                        datetime.now(UTC) + timedelta(days=2), PRICES)
        self.assertEqual((calls, files), ([], 0))

    def test_a_missing_folder_reads_nothing(self) -> None:
        self.assertEqual(spend.read_calls([Path("/nonexistent")], DAY, NOW, PRICES), ([], 0))


if __name__ == "__main__":
    unittest.main()
