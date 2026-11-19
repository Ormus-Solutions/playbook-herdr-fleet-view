"""The token economy: what the agents spent today, per space and per agent,
read from the agents' own usage logs.

Claude Code writes one transcript per session, as JSON lines, under
~/.claude/projects/<folder>/<session id>.jsonl (a subagent writes under
<session id>/subagents/, with the parent's session id on each line). Every
answer of the model is a line with "type": "assistant" and a "message" that
holds the model name and the token counts ("usage"). This module reads only
those numbers, the time, the folder and the session id. It never keeps or
prints the text of a conversation: transcripts can hold anything you typed.

Two rules make the numbers right:
- A call counts once. Claude Code writes one API call on several lines, one
  per content block, each with the same message id and the same usage. A sum
  over lines counts most calls two or three times.
- The money is a yardstick, not a bill: each call at the API list price from
  the config. A subscription plan has its own limits; the list price still
  shows which agents and habits cost the most.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from herdr_state import Agent

READER_KIND = "claude"  # the agent kind whose logs this module reads
NO_PANE = "(no live pane)"
PRICE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


@dataclass
class Call:
    when: datetime
    model: str       # the price key that matched the model name
    session: str
    folder: str
    context: int     # tokens the call read: input + cache read + cache write
    cache_read: int
    written: int     # cache writes
    output: int
    cost: float


@dataclass
class Row:
    """The calls of one agent (or of one folder that no live agent holds)."""
    label: str
    space: str
    agent: Agent | None = None
    calls: list[Call] = field(default_factory=list)


def price_key(model: str | None, prices: dict[str, dict[str, float]]) -> str | None:
    """The longest price key that appears in the model name, so a key such as
    "opus-4" can give an older model its own price next to "opus"."""
    name = (model or "").lower()
    keys = [k for k in prices if k.lower() in name]
    return max(keys, key=len) if keys else None


def cost_of(usage: dict[str, Any], price: dict[str, float]) -> float:
    """USD for one call. Prices are per million tokens."""
    split = usage.get("cache_creation") or {}
    w5 = split.get("ephemeral_5m_input_tokens")
    w1 = split.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:  # no split given: count every write as 5 min
        w5, w1 = usage.get("cache_creation_input_tokens") or 0, 0
    tokens = {
        "input": usage.get("input_tokens") or 0,
        "output": usage.get("output_tokens") or 0,
        "cache_read": usage.get("cache_read_input_tokens") or 0,
        "cache_write_5m": w5 or 0,
        "cache_write_1h": w1 or 0,
    }
    return sum(tokens[k] * price[k] for k in PRICE_KEYS) / 1_000_000


def parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def calls_in(lines: Iterable[str], since: datetime, until: datetime,
             prices: dict[str, dict[str, float]], session: str,
             seen: dict[str, Call]) -> None:
    """Add the calls of one transcript between `since` and `until` to `seen`,
    keyed by message id, so a call written on several lines counts once."""
    for n, line in enumerate(lines):
        if '"usage"' not in line:  # cheap test before the JSON parse
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict) or o.get("type") != "assistant":
            continue
        msg = o.get("message") or {}
        usage = msg.get("usage") or {}
        key = price_key(msg.get("model"), prices)
        when = parse_time(o.get("timestamp"))
        if not usage or key is None or when is None or not since <= when <= until:
            continue  # "<synthetic>" lines and unknown models have no price
        written = usage.get("cache_creation_input_tokens") or 0
        read = usage.get("cache_read_input_tokens") or 0
        call_id = msg.get("id") or o.get("requestId") or f"{session}:{n}"
        seen[call_id] = Call(
            when=when,
            model=key,
            session=o.get("sessionId") or session,
            folder=os.path.normpath(o.get("cwd") or "?"),
            context=(usage.get("input_tokens") or 0) + read + written,
            cache_read=read,
            written=written,
            output=usage.get("output_tokens") or 0,
            cost=cost_of(usage, prices[key]),
        )


def read_calls(roots: list[Path], since: datetime, until: datetime,
               prices: dict[str, dict[str, float]]) -> tuple[list[Call], int]:
    """Every call in the window, and how many transcripts were read. A file
    last written before the window is skipped without being opened."""
    seen: dict[str, Call] = {}
    files = 0
    cut = since.timestamp()
    for root in roots:
        for f in sorted(root.glob("**/*.jsonl")):
            try:
                if f.stat().st_mtime < cut:
                    continue
                with f.open(encoding="utf-8", errors="replace") as fh:
                    calls_in(fh, since, until, prices, f.stem, seen)
                files += 1
            except OSError:
                continue
    return sorted(seen.values(), key=lambda c: c.when), files


def attribute(calls: list[Call], agents: list[Agent]) -> dict[str, Row]:
    """Give each call to the live agent that made it.

    1. The session id the agent reported to Herdr, when there is one.
    2. Else the folder: the one live agent of this kind that works there.
       So earlier sessions in that folder today count for it too.
    3. Two or more live agents in the same folder: a row for the folder.
    4. No live agent there: a row "(no live pane)" for the folder (ended
       sessions, or agents started outside Herdr).
    """
    readable = [a for a in agents if a.kind == READER_KIND]
    by_session = {a.session: a for a in readable if a.session}
    by_folder: dict[str, dict[str, Agent]] = defaultdict(dict)
    for a in readable:
        for folder in a.folders:
            by_folder[folder][a.pane_id] = a
    rows: dict[str, Row] = {}
    for c in calls:
        agent = by_session.get(c.session)
        here = list(by_folder.get(c.folder, {}).values())
        if agent is None and len(here) == 1:
            agent = here[0]
        if agent is not None:
            label, space = agent.where, agent.space
        elif here:
            space = sorted(a.space for a in here)[0]
            label = f"{space} / {Path(c.folder).name} (shared folder)"
        else:
            label, space = f"{NO_PANE} {Path(c.folder).name}", NO_PANE
        row = rows.setdefault(label, Row(label=label, space=space, agent=agent))
        row.calls.append(c)
    return rows


def day_start(now: datetime, start: str) -> datetime:
    """The start of today in now's time zone, at "HH:MM"; yesterday's when
    now is earlier than that time."""
    hour, minute = (int(x) for x in start.split(":"))
    t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return t if t <= now else t - timedelta(days=1)


def share(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def report(calls: list[Call], agents: list[Agent], since: datetime, until: datetime,
           big_context: int, rebuild_share: float, files: int = 0) -> dict[str, Any]:
    """The numbers of the token pane, as plain data (this is also --json)."""
    rows = attribute(calls, agents)
    total = sum(c.cost for c in calls)
    hours = max(1, math.ceil((until - since).total_seconds() / 3600))

    def per_hour(cs: list[Call]) -> list[float]:
        out = [0.0] * min(24, hours)
        for c in cs:
            i = int((c.when - since).total_seconds() // 3600)
            if 0 <= i < len(out):
                out[i] += c.cost
        return [round(x, 4) for x in out]

    spaces: dict[str, list[Call]] = defaultdict(list)
    for row in rows.values():
        spaces[row.space] += row.calls
    by_space = [{
        "space": name,
        "cost": round(sum(c.cost for c in cs), 4),
        "share": round(share(sum(c.cost for c in cs), total), 4),
        "calls": len(cs),
        "per_hour": per_hour(cs),
    } for name, cs in spaces.items()]
    by_space.sort(key=lambda s: (s["space"] == NO_PANE, -s["cost"], s["space"]))

    by_agent, levers = [], []
    for row in sorted(rows.values(), key=lambda r: (r.space == NO_PANE, -sum(c.cost for c in r.calls))):
        cs = row.calls
        read = sum(c.context for c in cs)
        written = sum(c.written for c in cs)
        models: dict[str, float] = defaultdict(float)
        for c in cs:
            models[c.model] += c.cost
        last = max(cs, key=lambda c: c.when)
        item = {
            "label": row.label,
            "space": row.space,
            "kind": row.agent.kind if row.agent else "",
            "state": row.agent.state if row.agent else "",
            "model": max(models, key=lambda m: models[m]),
            "cost": round(sum(c.cost for c in cs), 4),
            "calls": len(cs),
            "mean_context": round(read / len(cs)),
            "write_share": round(share(written, read), 4),
            "last_context": last.context,
        }
        by_agent.append(item)
        if row.agent is not None and last.context >= big_context:
            levers.append(f"{row.label}: its last call read {tokens(last.context)} tokens. "
                          "/compact or /clear makes each next call cheaper.")
        if len(cs) >= 5 and item["write_share"] > rebuild_share:
            levers.append(f"{row.label}: {item['write_share']:.0%} of the tokens it read were "
                          "cache writes, so its cache is rebuilt often (a pause longer than "
                          "the cache lifetime, or a prompt start that changes).")

    no_reader = sorted({a.kind for a in agents if a.kind != READER_KIND})
    read_total = sum(c.context for c in calls)
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "transcripts": files,
        "total": {
            "cost": round(total, 4),
            "calls": len(calls),
            "tokens_read": read_total,
            "from_cache": round(share(sum(c.cache_read for c in calls), read_total), 4),
            "output": sum(c.output for c in calls),
        },
        "by_space": by_space,
        "by_agent": by_agent,
        "levers": levers,
        "no_reader": no_reader,
    }


def tokens(n: float) -> str:
    """1234 -> 1.2k, 7_900_000 -> 7.9M."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(int(n))
