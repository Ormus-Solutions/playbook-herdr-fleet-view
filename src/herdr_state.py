#!/usr/bin/env python3
"""Every Herdr space and its agents, from one `herdr api snapshot`.

Herdr calls a space a workspace. A workspace holds tabs, a tab holds panes,
and a pane runs a terminal program. When that program is a coding agent
(Claude Code, Codex, Grok and more), Herdr recognizes it and keeps its state.

One snapshot answers everything the fleet view needs, so the view asks once
per refresh instead of once per space. The snapshot looks like this
(Herdr 0.9.5, protocol 22):

    {"id": "...", "result": {"type": "session_snapshot", "snapshot": {
        "workspaces": [{"workspace_id": "w1", "number": 1, "label": "acme-web", ...}],
        "tabs":       [{"tab_id": "w1:t1", "workspace_id": "w1", "number": 1, "label": "build"}],
        "panes":      [{"pane_id": "w1:p1", "tab_id": "w1:t1", "label": "api", ...}],
        "agents":     [{"pane_id": "w1:p1", "agent": "claude", "agent_status": "working",
                        "name": null, "cwd": "/work/acme-web", "agent_session": null, ...}]}}}

Run it as a program to find a pane or a tab by its label (the playbook's
steps use this, because a shell variable does not live from one step to the
next):

    python3 src/herdr_state.py find pane fleet
    python3 src/herdr_state.py find tab Fleet
    python3 src/herdr_state.py find pane fleet --tab w1:t2   (only in that tab)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Herdr's five agent states, in the words of the view. "done" means the agent
# finished a turn that nobody has looked at yet: it waits for you.
STATE_WORDS = {
    "blocked": "blocked",   # an approval or a question is on its screen
    "done": "waiting",      # it answered; the answer waits for you
    "working": "working",
    "idle": "idle",         # ready, nothing new
    "unknown": "unknown",   # an agent is there, its state is not clear
}
# The order of attention: what needs you first.
ATTENTION = ["blocked", "waiting", "working", "idle", "unknown"]
TIMEOUT = 5  # seconds for `herdr api snapshot`


@dataclass
class Agent:
    space: str
    tab: str
    name: str       # the agent's Herdr name, else the pane label, else the pane id
    kind: str       # claude, codex, grok, ...
    state: str      # one of ATTENTION
    folders: list[str] = field(default_factory=list)  # where it works
    session: str = ""  # the agent's own session id, when Herdr knows it
    pane_id: str = ""

    @property
    def where(self) -> str:
        return f"{self.space} / {self.tab} / {self.name}"


@dataclass
class Space:
    name: str
    panes: int
    agents: list[Agent] = field(default_factory=list)


def unwrap(data: dict[str, Any]) -> dict[str, Any]:
    """The snapshot itself, from the whole CLI answer or from its parts."""
    if "result" in data:
        data = data["result"]
    if "snapshot" in data:
        data = data["snapshot"]
    if not isinstance(data.get("workspaces"), list):
        raise TypeError("this is not a Herdr snapshot (no workspaces list)")
    return data


def session_of(agent: dict[str, Any]) -> str:
    """The session id an agent reported to Herdr. Herdr gives either the id or
    the path of the session file; a Claude Code transcript is named <id>.jsonl."""
    ref = agent.get("agent_session") or {}
    value = ref.get("value") or ""
    if ref.get("kind") == "path":
        return Path(value).stem
    return value


def parse_snapshot(data: dict[str, Any]) -> list[Space]:
    """Spaces in Herdr's order, each with its agents in tab and pane order."""
    snap = unwrap(data)
    tabs = {t["tab_id"]: t for t in snap.get("tabs", [])}
    panes = {p["pane_id"]: p for p in snap.get("panes", [])}
    pane_order = {pid: n for n, pid in enumerate(panes)}
    spaces = {}
    for w in sorted(snap["workspaces"], key=lambda w: w.get("number", 0)):
        spaces[w["workspace_id"]] = Space(name=w.get("label") or w["workspace_id"],
                                          panes=w.get("pane_count", 0))
    rows = []
    for a in snap.get("agents", []):
        space = spaces.get(a.get("workspace_id"))
        if space is None:
            continue
        tab = tabs.get(a.get("tab_id"), {})
        pane = panes.get(a.get("pane_id"), {})
        folders = []
        for key in ("cwd", "foreground_cwd"):
            folder = a.get(key) or pane.get(key)
            if folder and os.path.normpath(folder) not in folders:
                folders.append(os.path.normpath(folder))
        agent = Agent(
            space=space.name,
            tab=tab.get("label") or a.get("tab_id", "?"),
            name=a.get("name") or pane.get("label") or a.get("pane_id", "?"),
            kind=a.get("display_agent") or a.get("agent") or "agent",
            state=STATE_WORDS.get(a.get("agent_status", "unknown"), "unknown"),
            folders=folders,
            session=session_of(a),
            pane_id=a.get("pane_id", ""),
        )
        order = (tab.get("number", 0), pane_order.get(agent.pane_id, 0))
        rows.append((order, space, agent))
    for _, space, agent in sorted(rows, key=lambda r: r[0]):
        space.agents.append(agent)
    return list(spaces.values())


def ask_herdr(herdr: str = "herdr") -> dict[str, Any]:
    """Run `herdr api snapshot` and return its JSON. It only reads."""
    try:
        done = subprocess.run([herdr, "api", "snapshot"], capture_output=True,
                              text=True, timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        raise RuntimeError(f"'{herdr}' was not found; set [fleet] herdr in the config")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"herdr gave no answer in {TIMEOUT} s")
    if done.returncode != 0:
        lines = done.stderr.strip().splitlines() or ["no answer"]
        raise RuntimeError(f"herdr: {lines[-1][:80]}")
    return json.loads(done.stdout)


def load_spaces(herdr: str, snapshot_file: str = "") -> tuple[list[Space], str]:
    """The spaces, and an error text ("" when all went well). A saved snapshot
    file wins over asking Herdr: the demo and the tests use one."""
    try:
        if snapshot_file:
            data = json.loads(Path(snapshot_file).read_text(encoding="utf-8"))
        else:
            data = ask_herdr(herdr)
        return parse_snapshot(data), ""
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as e:
        return [], str(e) or e.__class__.__name__


def find(data: dict[str, Any], what: str, label: str, workspace: str = "",
         tab: str = "") -> list[str]:
    """The ids of the panes or tabs with this label, in one workspace or all,
    and (for panes) in one tab or all."""
    snap = unwrap(data)
    items = snap.get("panes" if what == "pane" else "tabs", [])
    key = "pane_id" if what == "pane" else "tab_id"
    return [i[key] for i in items
            if i.get("label") == label and (not workspace or i.get("workspace_id") == workspace)
            and (not tab or i.get("tab_id") == tab)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find a Herdr pane or tab by its label.")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("find", help="print the id of the pane or tab with this label")
    f.add_argument("what", choices=["pane", "tab"])
    f.add_argument("label")
    f.add_argument("--workspace", default=os.environ.get("HERDR_WORKSPACE_ID", ""),
                   help="only this workspace (default: the one this pane is in)")
    f.add_argument("--tab", default="", help="only panes in this tab (a tab id)")
    f.add_argument("--herdr", default="herdr", help="the herdr command")
    f.add_argument("--snapshot", default="", help="read a saved snapshot instead")
    args = parser.parse_args(argv)
    try:
        if args.snapshot:
            data = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        else:
            data = ask_herdr(args.herdr)
        ids = find(data, args.what, args.label, args.workspace, args.tab)
    except (OSError, ValueError, TypeError, RuntimeError) as e:
        print(f"find: {e}", file=sys.stderr)
        return 2
    if len(ids) != 1:
        named = f" ({', '.join(ids)})" if ids else ""
        print(f"find: {len(ids)} {args.what}s are labelled '{args.label}'{named}; expected 1",
              file=sys.stderr)
        return 1
    print(ids[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
