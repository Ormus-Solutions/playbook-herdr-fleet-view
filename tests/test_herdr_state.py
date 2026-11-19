"""Spaces and agents from a Herdr snapshot (the synthetic one in examples/demo)."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import DEMO

import herdr_state

SNAPSHOT = json.loads((DEMO / "snapshot.json").read_text(encoding="utf-8"))


class ParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spaces = herdr_state.parse_snapshot(SNAPSHOT)
        self.agents = {a.where: a for s in self.spaces for a in s.agents}

    def test_spaces_in_herdr_order(self) -> None:
        self.assertEqual([s.name for s in self.spaces], ["acme-web", "demo-api", "notes", "system"])

    def test_done_means_waiting_for_you(self) -> None:
        self.assertEqual(self.agents["acme-web / docs / docs"].state, "waiting")
        self.assertEqual(self.agents["acme-web / build / web"].state, "blocked")
        self.assertEqual(self.agents["acme-web / build / api"].state, "working")

    def test_a_shell_pane_is_not_an_agent(self) -> None:
        demo_api = self.spaces[1]
        self.assertEqual(demo_api.panes, 3)
        self.assertEqual([a.name for a in demo_api.agents], ["worker", "review"])

    def test_agents_in_tab_then_pane_order(self) -> None:
        self.assertEqual([a.name for a in self.spaces[0].agents], ["api", "web", "docs"])

    def test_session_from_an_id_or_a_path(self) -> None:
        self.assertEqual(self.agents["acme-web / build / api"].session,
                         "0b8c1f2e-5a1d-4c3e-9f00-1a2b3c4d5e01")
        self.assertEqual(self.agents["demo-api / main / worker"].session,
                         "0b8c1f2e-5a1d-4c3e-9f00-1a2b3c4d5e03")
        self.assertEqual(self.agents["acme-web / docs / docs"].session, "")

    def test_bare_snapshot_works_too(self) -> None:
        bare = SNAPSHOT["result"]["snapshot"]
        self.assertEqual(len(herdr_state.parse_snapshot(bare)), 4)

    def test_unknown_state_and_name_fall_back(self) -> None:
        snap = {"workspaces": [{"workspace_id": "w1", "number": 1, "label": "x"}],
                "tabs": [], "panes": [],
                "agents": [{"workspace_id": "w1", "tab_id": "w1:t9", "pane_id": "w1:p9",
                            "agent": "claude", "agent_status": "new-state"}]}
        [a] = herdr_state.parse_snapshot(snap)[0].agents
        self.assertEqual((a.name, a.tab, a.state), ("w1:p9", "w1:t9", "unknown"))

    def test_not_a_snapshot(self) -> None:
        with self.assertRaises(TypeError):
            herdr_state.parse_snapshot({"result": {"type": "pong"}})


class LoadTest(unittest.TestCase):
    def test_a_missing_herdr_is_an_error_text(self) -> None:
        spaces, error = herdr_state.load_spaces("/nonexistent/herdr")
        self.assertEqual(spaces, [])
        self.assertIn("was not found", error)

    def test_from_a_saved_file(self) -> None:
        spaces, error = herdr_state.load_spaces("herdr", str(DEMO / "snapshot.json"))
        self.assertEqual(error, "")
        self.assertEqual(len(spaces), 4)


class FindTest(unittest.TestCase):
    def test_find_a_pane_and_a_tab_by_label(self) -> None:
        self.assertEqual(herdr_state.find(SNAPSHOT, "pane", "tokens"), ["w4:p9"])
        self.assertEqual(herdr_state.find(SNAPSHOT, "tab", "Fleet"), ["w4:t6"])

    def test_scoped_to_a_workspace(self) -> None:
        self.assertEqual(herdr_state.find(SNAPSHOT, "pane", "tokens", workspace="w1"), [])

    def test_the_command_prints_one_id(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = herdr_state.main(["find", "pane", "fleet", "--workspace", "w4",
                                     "--snapshot", str(DEMO / "snapshot.json")])
        self.assertEqual((code, out.getvalue()), (0, "w4:p8\n"))

    def test_a_pane_in_one_tab(self) -> None:
        # Undo closes the Fleet tab only when the fleet pane is in it.
        self.assertEqual(herdr_state.find(SNAPSHOT, "pane", "fleet", tab="w4:t6"), ["w4:p8"])
        self.assertEqual(herdr_state.find(SNAPSHOT, "pane", "fleet", tab="w1:t1"), [])

    def test_two_matches_are_named(self) -> None:
        # A second run of step 5 makes a second Fleet tab: the error names
        # both, so the person can close the one they do not want.
        snap = json.loads(json.dumps(SNAPSHOT))
        tabs = snap["result"]["snapshot"]["tabs"]
        tabs.append({**tabs[-1], "tab_id": "w4:t7", "number": 7})
        err = io.StringIO()
        with contextlib.redirect_stderr(err), tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text(json.dumps(snap), encoding="utf-8")
            code = herdr_state.main(["find", "tab", "Fleet", "--workspace", "w4",
                                     "--snapshot", str(path)])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue(),
                         "find: 2 tabs are labelled 'Fleet' (w4:t6, w4:t7); expected 1\n")

    def test_the_command_fails_when_nothing_matches(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = herdr_state.main(["find", "pane", "nope", "--workspace", "",
                                     "--snapshot", str(DEMO / "snapshot.json")])
        self.assertEqual(code, 1)
        self.assertIn("0 panes", err.getvalue())


if __name__ == "__main__":
    unittest.main()
