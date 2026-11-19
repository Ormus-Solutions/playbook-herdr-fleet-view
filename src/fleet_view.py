#!/usr/bin/env python3
"""Fleet view: what is going on, at a glance, plus the token economy.

Two views, one per Herdr pane:

    fleet   every Herdr space and its agents with their state (blocked,
            waiting, working, idle), and the load of each machine
    spend   the token economy: what the agents spent today, per space,
            per agent and per hour, and the levers that would cut it

Usage:
    python3 src/fleet_view.py --demo                 both views on the synthetic data
    python3 src/fleet_view.py fleet [--once|--json]  the live fleet view
    python3 src/fleet_view.py spend [--once|--json]  the live token view

Both only read. The live views redraw on a timer; ctrl+c quits. The design is
"data, then text": each view builds a plain report (what --json prints), and
a renderer turns it into lines. The tests pin both halves on synthetic data.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import config
import herdr_state
import machine
import spend

ROOT = Path(__file__).resolve().parents[1]
DEMO_CONFIG = ROOT / "examples" / "demo" / "config.toml"
BAR = 16
WIDTH = 78  # long lines wrap here, so a half-screen pane still reads well
SPARKS = "▁▂▃▄▅▆▇█"
COLORS = {"red": "31", "yellow": "33", "green": "32", "dim": "2", "bold": "1"}
STATE_COLOR = {"blocked": "red", "waiting": "yellow", "working": "green", "idle": "dim"}


class Paint:
    """ANSI colors in a live terminal only: never in a pipe, a test or with NO_COLOR."""

    def __init__(self, on: bool) -> None:
        self.on = on

    def __call__(self, text: str, color: str) -> str:
        if not self.on or color not in COLORS:
            return text
        return f"\033[{COLORS[color]}m{text}\033[0m"


def size(b: float | None) -> str:
    """Bytes in the shortest readable unit: 632M, 24.5G, 1.8T."""
    if b is None:
        return "?"
    if b == 0:
        return "0"
    for unit, n in (("T", 1024**4), ("G", 1024**3), ("M", 1024**2)):
        if b >= n:
            value = b / n
            return f"{value:.1f}{unit}" if value < 100 and unit != "M" else f"{value:.0f}{unit}"
    return f"{b / 1024:.0f}K"


def uptime(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m = int(seconds // 60)
    d, h, m = m // 1440, m // 60 % 24, m % 60
    return f"{d}d{h:02d}h" if d else f"{h}h{m:02d}m"


def bar(frac: float, paint: Paint) -> str:
    frac = min(max(frac, 0.0), 1.0)
    filled = round(frac * BAR)
    color = "red" if frac >= 0.9 else "yellow" if frac >= 0.7 else "green"
    return paint("█" * filled, color) + "░" * (BAR - filled)


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def wrap(text: str, first: str, rest: str) -> list[str]:
    return textwrap.wrap(text, WIDTH, initial_indent=first, subsequent_indent=rest)


# ---------------------------------------------------------------- fleet view


def fleet_report(cfg: dict[str, Any], readings: dict[str, dict[str, Any]],
                 now: datetime) -> dict[str, Any]:
    spaces, error = herdr_state.load_spaces(cfg["fleet"]["herdr"], cfg["fleet"]["snapshot_file"])
    counts = {s: 0 for s in herdr_state.ATTENTION}
    for space in spaces:
        for a in space.agents:
            counts[a.state] += 1
    return {
        "at": now.isoformat(timespec="seconds"),
        "herdr_error": error,
        "counts": counts,
        "spaces": [{
            "name": s.name,
            "panes": s.panes,
            "agents": [{"tab": a.tab, "name": a.name, "kind": a.kind, "state": a.state,
                        "where": a.where} for a in s.agents],
        } for s in spaces],
        "machines": [{"name": m["name"], **readings.get(m["name"], machine.failed("not read yet"))}
                     for m in cfg["machines"]],
    }


def machine_lines(m: dict[str, Any], paint: Paint) -> list[str]:
    name = f"  {m['name']:<14}"
    if not m.get("ok") and not m.get("stale_since"):
        return [name + paint(f"no answer: {m.get('error', '?')}", "yellow")]
    lines = [name + f"{plural(m['cores'], 'core')}, up {uptime(m.get('uptime'))}"]
    if m.get("stale_since"):
        lines.append("    " + paint(f"no answer now ({m['error']}); data from {m['stale_since']}",
                                    "yellow"))
    load = m["load"]
    lines.append(f"    load  {bar(load[0] / m['cores'], paint)}  {load[0] / m['cores']:4.0%}"
                 f"   {load[0]:.1f} now, {load[2]:.1f} over 15 min")
    if m.get("mem_total"):
        used = m["mem_total"] - m["mem_available"]
        swap = (m.get("swap_total") or 0) - (m.get("swap_free") or 0)
        swap_text = f"swap {size(swap)} used" if m.get("swap_total") else "no swap"
        lines.append(f"    RAM   {bar(used / m['mem_total'], paint)}  {used / m['mem_total']:4.0%}"
                     f"   {size(used)} of {size(m['mem_total'])}, {swap_text}")
    disk = m["disk_used"] / m["disk_total"] if m.get("disk_total") else 0.0
    lines.append(f"    disk  {bar(disk, paint)}  {disk:4.0%}"
                 f"   {size(m.get('disk_used'))} of {size(m.get('disk_total'))}")
    if m.get("note"):
        lines.append("    " + paint(m["note"], "dim"))
    if m.get("programs"):
        lines.append("    " + paint(f"{'RAM by program':<22}{'own + shared once':>17}{'plain RSS sum':>16}",
                                    "dim"))
        for p in m["programs"]:
            label = f"{p['name']} x{p['count']}"
            lines.append(f"      {label:<20}{size(p['ram']):>17}{size(p['rss_sum']):>16}")
    return lines


def render_fleet(r: dict[str, Any], paint: Paint, footer: str = "") -> str:
    n_agents = sum(r["counts"].values())
    parts = [paint(f"{n} {s}", STATE_COLOR.get(s, "")) for s, n in r["counts"].items() if n]
    head = f"{plural(len(r['spaces']), 'space')}, {plural(n_agents, 'agent')}"
    lines = [paint("Fleet", "bold") + f"  {r['at'][11:19]}   " + head
             + (": " + ", ".join(parts) if parts else "")]
    needs = [f"{a['where']} ({a['state']})" for s in r["spaces"] for a in s["agents"]
             if a["state"] in ("blocked", "waiting")]
    if needs:
        more = f", and {len(needs) - 5} more" if len(needs) > 5 else ""
        lines += wrap("Needs you: " + ", ".join(needs[:5]) + more, "", "  ")
    lines += ["", paint("Spaces", "bold")]
    if r["herdr_error"]:
        lines.append("  " + paint(f"Herdr gave no spaces: {r['herdr_error']}", "yellow"))
    for s in r["spaces"]:
        counts = {}
        for a in s["agents"]:
            counts[a["state"]] = counts.get(a["state"], 0) + 1
        summary = "  ".join(paint(f"{counts[st]} {st}", STATE_COLOR.get(st, ""))
                            for st in herdr_state.ATTENTION if st in counts)
        agents = plural(len(s["agents"]), "agent") if s["agents"] else f"no agents, {plural(s['panes'], 'pane')}"
        lines.append(f"  {s['name']:<14} {agents:<10} {summary}".rstrip())
        for a in s["agents"]:
            where = f"{a['tab']} / {a['name']}"
            lines.append(f"    {where:<24} {a['kind']:<8} {paint(a['state'], STATE_COLOR.get(a['state'], ''))}")
    lines += ["", paint("Machines", "bold")]
    for m in r["machines"]:
        lines += machine_lines(m, paint)
    if footer:
        lines += ["", paint(footer, "dim")]
    return "\n".join(lines) + "\n"


class Machines:
    """Reads every machine at once (ssh can take seconds each) and keeps the
    last good reading, so a machine that stops answering keeps its card,
    marked with the time of that data."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.last: dict[str, dict[str, Any]] = {}

    def read(self) -> dict[str, dict[str, Any]]:
        top = int(self.cfg["fleet"]["top_programs"])
        ms = self.cfg["machines"]
        with ThreadPoolExecutor(max_workers=max(1, len(ms))) as pool:
            fresh = dict(zip([m["name"] for m in ms],
                             pool.map(lambda m: machine.read_machine(m, top), ms)))
        out = {}
        for name, reading in fresh.items():
            if reading.get("ok"):
                self.last[name] = reading
                out[name] = reading
            elif name in self.last:
                old = self.last[name]
                when = datetime.fromtimestamp(old["read_at"]).strftime("%H:%M:%S")
                out[name] = {**old, "ok": False, "error": reading.get("error", "?"),
                             "stale_since": when}
            else:
                out[name] = reading
        return out


# ---------------------------------------------------------------- token view


def spend_report(cfg: dict[str, Any], now: datetime) -> dict[str, Any]:
    s = cfg["spend"]
    since = spend.day_start(now, s["day_start"])
    calls, files = spend.read_calls([Path(p) for p in s["logs"]], since, now, cfg["prices"])
    spaces, error = herdr_state.load_spaces(cfg["fleet"]["herdr"], cfg["fleet"]["snapshot_file"])
    agents = [a for space in spaces for a in space.agents]
    r = spend.report(calls, agents, since, now, s["big_context"], s["rebuild_share"], files)
    r["herdr_error"] = error
    return r


def spark(values: list[float], top: float, hours: int = 24) -> str:
    """One mark per hour: · for no spend, a block as high as the spend."""
    out = ""
    for v in values:
        if v <= 0:
            out += "·"
        else:
            out += SPARKS[min(len(SPARKS), math.ceil(v / top * len(SPARKS))) - 1]
    return out + " " * (hours - len(values))


def render_spend(r: dict[str, Any], paint: Paint, footer: str = "") -> str:
    since, until = datetime.fromisoformat(r["since"]), datetime.fromisoformat(r["until"])
    zone = until.tzname() or ""
    t = r["total"]
    lines = [
        paint("Token economy", "bold") + f"  {since:%Y-%m-%d %H:%M} to {until:%H:%M} {zone}".rstrip(),
        paint("API list prices: a yardstick, not a bill. Each call counted once.", "dim"),
        "",
        f"  ${t['cost']:.2f} today   {plural(t['calls'], 'call')}   "
        f"{spend.tokens(t['tokens_read'])} tokens read, {t['from_cache']:.0%} from the cache",
    ]
    if r.get("herdr_error"):
        lines.append("  " + paint(f"Herdr gave no agents, so every call shows by folder: "
                                  f"{r['herdr_error']}", "yellow"))
    top = max((v for s in r["by_space"] for v in s["per_hour"]), default=0) or 1
    width = max([len(s["space"]) for s in r["by_space"]] + [14])
    lines += ["", paint(f"{'By space':<{width + 2}}  spend  share  calls  each hour from {since:%H:%M}", "bold")]
    for s in r["by_space"]:
        lines.append(f"  {s['space']:<{width}} {'$' + format(s['cost'], '.2f'):>7}  {s['share']:5.0%}"
                     f"  {s['calls']:5}  {spark(s['per_hour'], top)}".rstrip())
    width = max([len(a["label"]) for a in r["by_agent"]] + [14])
    lines += ["", paint(f"{'By agent':<{width + 2}}  model     spend  calls  read/call  writes", "bold")]
    for a in r["by_agent"]:
        lines.append(f"  {a['label']:<{width}}  {a['model']:<8} {'$' + format(a['cost'], '.2f'):>7}"
                     f"  {a['calls']:5}  {spend.tokens(a['mean_context']):>9}  {a['write_share']:6.0%}")
    lines.append(paint("  read/call: tokens each call read. writes: their share written to the cache.",
                       "dim"))
    lines += ["", paint("Levers", "bold")]
    for lever in r["levers"]:
        lines += wrap(lever, "  - ", "    ")
    if not r["levers"]:
        lines.append("  none today")
    note = f"Read {plural(r['transcripts'], 'Claude Code transcript')}."
    if r["no_reader"]:
        note += f" No reader yet for {', '.join(r['no_reader'])}, so their spend is not shown."
    lines += [""] + [paint(line, "dim") for line in wrap(note, "", "")]
    if footer:
        lines.append(paint(footer, "dim"))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the program


def now_of(cfg: dict[str, Any]) -> datetime:
    """The config's clock (the demo fixes one, so its output never changes), else now."""
    return cfg["clock"] or datetime.now().astimezone()


def live(draw, interval: float) -> int:
    """Redraw on a timer. \033[H\033[2J moves the cursor home and clears the screen."""
    try:
        while True:
            text = draw()
            sys.stdout.write("\033[H\033[2J" + text)
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The fleet view and the token economy, for Herdr.")
    parser.add_argument("view", nargs="?", choices=["fleet", "spend"],
                        help="which view (with --demo and no view: both)")
    parser.add_argument("--config", type=Path, default=config.DEFAULT_PATH,
                        help=f"the config file (default: {config.DEFAULT_PATH})")
    parser.add_argument("--demo", action="store_true",
                        help="run once on the synthetic data in examples/demo/")
    parser.add_argument("--once", action="store_true", help="print once and exit")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON, for an agent")
    args = parser.parse_args(argv)
    if args.view is None and not args.demo:
        parser.error("name a view (fleet or spend), or use --demo")
    try:
        cfg = config.load(DEMO_CONFIG if args.demo else args.config)
    except config.ConfigError as e:
        print(f"fleet_view: {e}", file=sys.stderr)
        return 2
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.json
    paint = Paint(bool(color))
    machines = Machines(cfg)

    def fleet_text(footer: str = "") -> str:
        r = fleet_report(cfg, machines.read(), now_of(cfg))
        return json.dumps(r, indent=2) + "\n" if args.json else render_fleet(r, paint, footer)

    def spend_text(footer: str = "") -> str:
        r = spend_report(cfg, now_of(cfg))
        return json.dumps(r, indent=2) + "\n" if args.json else render_spend(r, paint, footer)

    if args.demo and args.view is None:
        sys.stdout.write(fleet_text() + "\n" + spend_text())
        return 0
    draw = fleet_text if args.view == "fleet" else spend_text
    if args.once or args.json or args.demo:
        sys.stdout.write(draw())
        return 0
    interval = cfg["fleet" if args.view == "fleet" else "spend"]["interval"]
    return live(lambda: draw(f"read only, every {interval:g} s; ctrl+c quits"), interval)


if __name__ == "__main__":
    sys.exit(main())
