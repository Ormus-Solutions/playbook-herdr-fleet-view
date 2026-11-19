"""The config: every problem names its key."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import DEMO, ROOT

import config

PRICE = """
[prices.opus]
input = 4.0
output = 20.0
cache_read = 0.2
cache_write_5m = 5.0
cache_write_1h = 8.0
"""


def load_text(text: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text(text, encoding="utf-8")
        return config.load(path)


class ConfigTest(unittest.TestCase):
    def test_the_example_config_loads(self) -> None:
        cfg = config.load(ROOT / "examples" / "config.example.toml")
        self.assertEqual([m["name"] for m in cfg["machines"]], ["local"])
        self.assertTrue(cfg["spend"]["logs"][0].endswith("/.claude/projects"))
        self.assertIsNone(cfg["clock"])

    def test_the_demo_config_reads_its_own_folder(self) -> None:
        cfg = config.load(DEMO / "config.toml")
        self.assertEqual(cfg["fleet"]["snapshot_file"], str(DEMO / "snapshot.json"))
        self.assertEqual(cfg["spend"]["logs"], [str(DEMO / "logs")])
        self.assertEqual(cfg["clock"].isoformat(), "2026-01-15T17:30:00+00:00")

    def test_defaults(self) -> None:
        cfg = load_text(PRICE)
        self.assertEqual(cfg["machines"], [{"name": "local"}])
        self.assertEqual(cfg["fleet"]["herdr"], "herdr")
        self.assertEqual(cfg["spend"]["day_start"], "00:00")

    def test_missing_config_says_what_to_do(self) -> None:
        with self.assertRaises(config.ConfigError) as caught:
            config.load(Path("/nonexistent/config.toml"))
        self.assertIn("examples/config.example.toml", str(caught.exception))

    def check_error(self, text: str, expected: str) -> None:
        with self.assertRaises(config.ConfigError) as caught:
            load_text(text)
        self.assertIn(expected, str(caught.exception))

    def test_errors_name_the_key(self) -> None:
        self.check_error("", "[prices]")
        self.check_error("[prices.opus]\ninput = 1\n", "needs a number for output")
        self.check_error(PRICE + '[spend]\nday_start = "25:00"\n', "'day_start'")
        self.check_error(PRICE + "[fleet]\ninterval = 0\n", "'interval' must be a number above 0")
        self.check_error(PRICE + '[[machines]]\nname = "a"\n[[machines]]\nname = "a"\n', "used twice")
        self.check_error(PRICE + '[[machines]]\nname = "a"\nssh = "a"\nfile = "a.json"\n', "not both")
        self.check_error(PRICE + '[[machines]]\nname = "a"\nssh = "-oProxyCommand=x"\n', "not an option")
        # A top-level key goes before the first [table]: after it, TOML files it under that table.
        self.check_error('clock = "2026-01-15T17:30:00"\n' + PRICE, "time zone")
        self.check_error("this is = not toml =", "config.toml")


if __name__ == "__main__":
    unittest.main()
