"""The two views end to end, on the demo data."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import DEMO, ROOT

import config
import fleet_view


def run_main(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fleet_view.main(list(argv))
    return code, out.getvalue()


class DemoTest(unittest.TestCase):
    def test_demo_prints_the_expected_output(self) -> None:
        done = subprocess.run(["bash", str(ROOT / "examples" / "run.sh")],
                              capture_output=True, text=True, check=True)
        expected = (ROOT / "examples" / "expected-output.txt").read_text(encoding="utf-8")
        self.assertEqual(done.stdout, expected)

    def test_the_readme_preview_is_the_demo_output(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        preview = readme.split("## Preview", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
        expected = (ROOT / "examples" / "expected-output.txt").read_text(encoding="utf-8")
        self.assertEqual(preview, expected)

    def test_no_colors_in_a_pipe(self) -> None:
        code, out = run_main("--demo")
        self.assertEqual(code, 0)
        self.assertNotIn("\033[", out)

    def test_lines_fit_a_half_screen_pane(self) -> None:
        _, out = run_main("--demo")
        self.assertLessEqual(max(len(line) for line in out.splitlines()), 78)

    def test_json_for_an_agent(self) -> None:
        _, out = run_main("spend", "--demo", "--json")
        r = json.loads(out)
        self.assertEqual(r["total"]["calls"], sum(a["calls"] for a in r["by_agent"]))
        self.assertAlmostEqual(sum(s["cost"] for s in r["by_space"]), r["total"]["cost"], places=2)
        _, out = run_main("fleet", "--demo", "--json")
        r = json.loads(out)
        self.assertEqual(r["counts"]["blocked"], 1)
        self.assertEqual([m["ok"] for m in r["machines"]], [True, True, False])

    def test_demo_json_is_one_document(self) -> None:
        _, out = run_main("--demo", "--json")
        self.assertEqual(sorted(json.loads(out)), ["fleet", "spend"])

    def test_a_view_is_needed_without_demo(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            fleet_view.main([])

    def test_a_bad_config_exits_2(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = fleet_view.main(["fleet", "--once", "--config", "/nonexistent/config.toml"])
        self.assertEqual(code, 2)
        self.assertIn("no config at", err.getvalue())


class StaleTest(unittest.TestCase):
    def test_a_machine_that_stops_answering_keeps_its_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "box.json"
            shutil.copy(DEMO / "machines" / "local.json", path)
            cfg = config.load(DEMO / "config.toml")
            cfg["machines"] = [{"name": "box", "file": str(path)}]
            machines = fleet_view.Machines(cfg)
            self.assertTrue(machines.read()["box"]["ok"])
            path.write_text('{"ok": false, "error": "Connection timed out"}', encoding="utf-8")
            reading = machines.read()["box"]
        self.assertFalse(reading["ok"])
        self.assertEqual(reading["cores"], 16)  # the last good data stays
        text = "\n".join(fleet_view.machine_lines({"name": "box", **reading}, fleet_view.Paint(False)))
        self.assertIn("no answer now (Connection timed out); data from", text)

    def test_herdr_not_answering_still_shows_machines(self) -> None:
        cfg = config.load(DEMO / "config.toml")
        cfg["fleet"]["snapshot_file"] = ""
        cfg["fleet"]["herdr"] = "/nonexistent/herdr"
        r = fleet_view.fleet_report(cfg, fleet_view.Machines(cfg).read(), cfg["clock"])
        text = fleet_view.render_fleet(r, fleet_view.Paint(False))
        self.assertIn("Herdr gave no spaces", text)
        self.assertIn("build-box", text)


class IncompleteReadingTest(unittest.TestCase):
    def test_one_bad_card_not_a_crash(self) -> None:
        lines = fleet_view.machine_lines({"name": "box", "ok": True, "cores": 4},
                                         fleet_view.Paint(False))
        self.assertEqual(len(lines), 1)
        self.assertIn("the reading is incomplete", lines[0])


class LiveTest(unittest.TestCase):
    def test_ctrl_c_quits_cleanly(self) -> None:
        drawn = []

        def draw() -> str:
            if drawn:
                raise KeyboardInterrupt
            drawn.append(1)
            return "frame\n"

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fleet_view.live(draw, 0.01)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "\033[H\033[2Jframe\n")


class FormatTest(unittest.TestCase):
    def test_size_and_uptime(self) -> None:
        self.assertEqual([fleet_view.size(b) for b in (0, 632 * 1024**2, 24.5 * 1024**3, 1.8 * 1024**4)],
                         ["0", "632M", "24.5G", "1.8T"])
        self.assertEqual(fleet_view.uptime(3 * 86400 + 4 * 3600), "3d04h")
        self.assertEqual(fleet_view.uptime(5 * 3600 + 12 * 60), "5h12m")

    def test_spark_marks_hours_with_no_spend(self) -> None:
        self.assertEqual(fleet_view.spark([0, 1, 4], 4, hours=4), "·▂█ ")


if __name__ == "__main__":
    unittest.main()
